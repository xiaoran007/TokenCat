# Native architecture and decisions

In version 0.8.0, the SwiftUI macOS app uses a Rust core through a C ABI, while the Python CLI retains its own collectors and pricing workflow. Native support covers Codex, Claude Code, OpenCode, and Antigravity. The 0.8.0 CLI additionally supports Gemini CLI and GitHub Copilot.

## CLI migration scope

The target architecture is one Rust business core with SwiftUI and CLI interfaces. Python remains the CLI entry point and handles arguments, terminal presentation, and binding lifecycle; collection, filtering, aggregation, and pricing belong to Rust. This integration is planned, not yet implemented.

CLI versions after 0.8.0 will no longer support Gemini CLI or GitHub Copilot. The initial migration targets only the local dashboard (`tokencat` and `tokencat dashboard`). Other CLI commands are deferred. Remote functionality will be developed separately with a new interaction and execution model; preserving the current remote protocol and command behavior is outside this migration.

The existing native `Dashboard` provides token and cost totals, model rankings, per-session summaries, catalog metadata, and scan warnings. Supporting the current terminal dashboard requires these additions or presentation decisions:

- Add harness filtering and explicit calendar granularity to `Query`; current timeline selection is automatic hourly/daily and does not support weekly/monthly buckets. Filtering must happen before all aggregates are calculated.
- Add model/harness breakdowns and session counts to timeline buckets; current buckets contain only a timestamp and summary. Define whether weekly/monthly session counts mean distinct sessions or summed daily activity before implementing them.
- Recent-session rows already contain anonymous labels, harnesses, usage, costs, and activity times. Keeping the model column requires additional session model information. The old Python attribution classification has no direct native equivalent.
- Native harness rows indicate usage within the query window, not source detection status. Preserving the current source-status indicators requires per-harness scan diagnostics; otherwise the interface must label them as active harnesses.

Presentation must follow native semantics: reasoning is already included in output, cache reads and writes are separate, and uncertain prices retain their minimum/maximum range. Session counts must exclude structural ancestor rows with no own events, and model counts must distinguish unidentified models. Pricing coverage can use native priced/total tokens; legacy fallback and attribution metrics should not be inferred from unrelated fields. Python must not rebuild a second aggregation or pricing pipeline to fill these gaps.

## Privacy and collection

Provider sources are read-only. TokenCat must not proxy requests, rewrite endpoints, access OAuth/session credentials for reporting, or expose prompt/response bodies. Only usage, model-service identity, timestamps, and selected session relationships and project metadata enter the native ledger. Paths remain hidden by default.

`CoreWorker` owns the Rust handle on a serial utility queue. Scanning and querying run off the main actor. A configuration change closes the old handle and opens a new engine; the Swift model discards results whose captured configuration no longer matches current settings. Usage polling waits for each refresh to finish before sleeping, avoiding overlapping scans.

The native ledger lives in `~/Library/Application Support/TokenCat/usage.sqlite3`. Complete JSONL records, parser state, and byte offsets commit together. Incomplete trailing records wait for the next scan. Stable event identities reconcile repeated records, archived copies, and revisions. Source deletion or rotation preserves already collected usage.

OpenCode uses individual `step-finish` records when available, excluding historical context copied into forked sessions and avoiding duplicate message totals. Reasoning belongs to output. Source reads use a consistent SQLite snapshot, including committed WAL data.

## Antigravity metadata and identity

Synthetic SQLite/protobuf fixtures in [the integration tests](../native/tokencat-core/tests/antigravity.rs) contain invented counters, request IDs, models, dates, and body sentinels. No user conversations or credentials are copied into fixtures.

Field definitions were checked against protobuf descriptors in the official installed Antigravity `language_server` on September 30, 2026:

| Message | Selected fields |
| --- | --- |
| `CortexStepGeneratorMetadata` | `chat_model=1`, packed `step_indices=2` |
| `ChatModelMetadata` | `usage=4`, `chat_start_metadata=9`, `response_model=19`, `response_model_full=22` |
| `ChatStartMetadata` | `created_at=4`, a protobuf timestamp |
| `ModelUsageStats` | `model=1` (enum), `input_tokens=2`, `output_tokens=3`, `cache_write_tokens=4`, `cache_read_tokens=5`, `api_provider=6` (enum), `message_id=7`, `thinking_output_tokens=9`, `response_output_tokens=10`, `response_id=11`, `provider_assigned_message_id=12` |
| `CortexStepMetadata` | `created_at=1`, `finished_generating_at=7`, `completed_at=8`, `model_usage=9`, `last_completed_chunk_at=22`, `model_info=24`, `started_at=32` |
| `ModelInfo` | `model_name=8` |
| `CortexTrajectoryMetadata` | `parent_conversation_id=5`, `workspace_uris=7` |

Verified API-provider enums include Google Vertex=3, Google Gemini=24, Anthropic Vertex=26, Google Evergreen=30, and OpenAI Vertex=31. Model and provider enums are not token counters. Input is uncached input; cache reads are separate. Output already includes thinking and response, so adding reasoning again would double count.

Read-only inspection of 416 generation records found output included thinking plus response; 398 lacked generation creation timestamps. Linked steps supplied actual request dates, and two requests had usage only in steps. These observations motivated synthetic regressions rather than retained user data.

Generations link to step metadata for timestamps and usage not yet flushed to the generation table. Undated usage remains separate from time-window totals; database modification time is not a substitute for a request date. Conflicting workspace URIs do not assign an arbitrary project.

Positional and request aliases retain stable ledger identities when response IDs or corresponding steps arrive later. App/CLI replicas reconcile by request identity and revision, including after restart. Confirmed duplicate ledger events merge before the updated alias map commits.

## Refresh cache decision

The original Antigravity collector parsed every database before comparing its fingerprint. Its protobuf reader issued a SQLite `substr` query for each framing byte, repeatedly traversing large values even when bodies were skipped.

The implementation uses one read-only incremental BLOB handle per metadata row, reading exactly the existing framing and allowlisted ranges. It does not prefetch body ranges or load whole `data`/`metadata` values, `step_payload`, response headers, agent scripts, or static configuration.

Each `Engine` owns source connections and parsed usage metadata. Cache validity uses `PRAGMA data_version` on the same persistent connection; main-file modification times alone miss WAL writes. A changed version reparses that database in a consistent read transaction. If an outside commit occurs across parsing, the result stays uncached for the next scan. Cached diagnostics replay on unchanged scans.

Device/inode changes close and reopen replaced sources. Deleted paths release entries; read failures discard the connection and snapshot while remaining visible in scan diagnostics. Closing the engine releases all entries. Single-scan collector APIs create a temporary cache; long-lived engines retain theirs.

Each connection uses `PRAGMA cache_size=-256`, a connection-local 256 KiB page-cache budget, not a hard process-memory cap. This reduces memory retained by multiple SQLite connections without changing provider database settings on disk. The refresh interval remains two seconds by default.

[Final isolated benchmark results](../experiments/antigravity-refresh/production-results.json), recorded on macOS ARM64 on October 2, 2026:

| Large unchanged profile | Original | Production |
| --- | ---: | ---: |
| Median wall time | 1294.16 ms | 5.63 ms |
| Median process CPU time | 1291.58 ms | 5.49 ms |
| Whole-program peak RSS | 38.52 MiB | 42.83 MiB |

An unbounded prototype retained about 59 MiB peak RSS; the page-cache budget was chosen to retain the speed improvement with less memory. The large profile has 8 databases, 80 generations each, and 256 KiB skipped fields per generation. Unchanged measurements use 9 rounds. Cold ingestion, historical WAL edits, appends, checkpointing, and consistent atomic database replacement each use one round. Usage events, session metadata, and scan reports match the original baseline in every scenario.

Peak RSS includes synthetic fixture creation and all scans. The original baseline is reused from the initial comparison, and the app stayed running during measurement. These figures isolate Antigravity collection; they do not measure whole-app CPU, SwiftUI rendering, other collectors, dashboard queries, or long-term memory behavior.

## Pricing decisions

The native app bundles a pinned LiteLLM catalog and optionally loads a validated downloaded or custom catalog. Downloaded prices and update timestamps are stored together in `~/Library/Application Support/TokenCat/pricing/litellm-cache.json`. Conditional HTTP requests use ETags; failed updates retain loaded prices. A custom catalog disables automatic and manual network updates.

Collection harness and model service (`model_provider`) are separate identities. Native matching prefers official model-service records, then an explicitly identified third-party record. It does not guess similar model names or choose among ambiguous records. The explicit native mapping is `codex-auto-review` to `gpt-5.6-luna`; the Python CLI currently maps it to `gpt-5.4-mini`. Pricing details disclose the mapping and source.

Missing prices stay unknown, while an explicit zero rate means free. Missing cache TTL or long-context detail can produce uncertainty. Reasoning is part of output. Estimates use standard token rates and exclude Priority, Flex, Batch, tool charges, and regional adjustments. The selected catalog applies to every displayed period; updates do not alter the token ledger or reconstruct historical invoices.
