# Native architecture and decisions

From CLI version 0.9.0, the SwiftUI macOS app and Python CLI share one Rust business core. Published 0.8.0 artifacts and tags retain their original Python CLI implementation; they are not rebuilt or replaced by this change.

## CLI architecture and scope

Python remains the CLI entry point and handles arguments, configuration, terminal presentation, JSON serialization, and binding lifecycle. Collection, filtering, usage aggregation, and pricing belong to Rust. `tokencat` and `tokencat dashboard` use the existing dashboard callbacks, date parsing, themes, and renderer, with the promoted native data adapter. The obsolete Python collectors, pricing catalog/pipeline, aggregation/filtering pipeline, and remote stack have been removed.

Only the local dashboard and its JSON export are exposed. Other CLI commands and remote functionality are deferred; future remote work will use a new interaction and execution model. CLI versions after 0.8.0 no longer support Gemini CLI or GitHub Copilot as harnesses. Antigravity can still report Gemini models.

The root `tokencat` distribution uses maturin and packages `src/tokencat` with `tokencat._native`. `bindings/python/` contains the PyO3 extension and its separate Cargo workspace/lockfile; it depends directly on `native/tokencat-core`, keeping Python dependencies out of macOS builds. The separate candidate distribution, namespace, and command are retired. Each invocation opens its own engine, scans and queries, then closes it. A mutex serializes binding calls while native work releases the GIL. Missing extensions and invalid catalogs are errors; Python collectors are never used as a fallback.

The CLI ledger defaults to `~/.tokencat/usage.sqlite3`, separate from the app ledger and legacy Python price cache. If this ledger is absent and a candidate ledger exists at `~/.tokencat-candidate/usage.sqlite3`, the first valid dashboard invocation copies it with SQLite's backup API, including committed WAL data. The result is published atomically without overwriting an existing CLI ledger; the candidate original remains intact. Migration errors fail explicitly. This preserves candidate history even when source records have disappeared. The CLI uses native bundled prices without price downloads. Independent app and CLI ledgers retain their own collected history, so source deletion or different source roots can produce different totals with the same query and pricing catalog.

The native adapter requests details and maps query results to the existing dashboard presentation records, without Python collection, pricing, or usage aggregation. Date parsing and daily/weekly/monthly selection belong to the shared CLI; its inclusive end bound is converted to native's exclusive millisecond bound. For weekly/monthly views a separate native daily query supplies the existing JSON daily report. Output is converted to non-reasoning output plus reasoning so the existing renderer adds reasoning exactly once. Optional cache-write and cost-range fields extend the shared view without changing legacy output. Provider badges describe usage within the window; legacy attribution stays unset and native incompleteness is reported as a warning. JSON uses the existing serializer, anonymous session labels, and no observed states or raw identifiers. Diagnostic warnings can still contain source paths. `--no-price` keeps the existing upper-layer behavior: pricing metadata is omitted and cost estimates are disabled in reports; the core may still calculate prices internally.

The native `Dashboard` provides token and cost totals, model rankings, per-session summaries, catalog metadata, and scan warnings. Its JSON query contract now also supports:

- `providers`: omitted or `null` selects all harnesses; `[]` selects none. Filtering happens before pricing and every usage aggregate, and also filters observed states by harness. Scan diagnostics remain global, and observed states retain their existing latest-state semantics rather than following the usage time window.
- `granularity`: `auto` (default), `hour`, `day`, `week`, or `month`. Auto retains the macOS behavior: hours for windows up to three days, days otherwise. Weeks start on Monday and months on the first day, in the requested time zone. Bounds remain `[since_ms, until_ms)`; partial and empty buckets are retained.
- `include_details`: defaults to `false`. When true, each timeline bucket adds `details`, containing `session_count` and model/harness `models` rows. Counts are distinct (harness, session) pairs with events in that bucket, including weekly/monthly buckets; structural ancestors do not count. Session rows also provide `primary_model` when identified, selected by the most tokens within the query window, with model-name tie breaking. Unidentified usage can win this selection and leaves the field absent.

For example, a detailed weekly query uses:

```json
{"since_ms": 0, "until_ms": 604800000, "timezone": "UTC", "providers": ["codex", "claude"], "granularity": "week", "include_details": true}
```

Bucket model rows retain the existing summary fields, including cost ranges and coverage, and keep different harnesses separate even when they use the same model. Session models and bucket details are computed only when requested. The C ABI, `schema_version: 1`, existing response fields, and macOS query defaults remain unchanged. Without details, the new response fields are omitted. Swift ignores added JSON fields; no macOS product changes are needed to consume this core version.

Native harness rows indicate usage within the query window, not source detection status. Keeping source-detection indicators would require per-harness scan diagnostics; they are outside the local dashboard scope.

Presentation must follow native semantics: reasoning is already included in output, cache reads and writes are separate, and uncertain prices retain their minimum/maximum range. Session counts must exclude structural ancestor rows with no own events, and model counts must distinguish unidentified models. Pricing coverage can use native priced/total tokens; legacy fallback and attribution metrics should not be inferred from unrelated fields. Python must not rebuild a second aggregation or pricing pipeline to fill these gaps.

## Privacy and collection

Provider sources are read-only. TokenCat must not proxy requests, rewrite endpoints, access OAuth/session credentials for reporting, or expose prompt/response bodies. Only usage, model-service identity, timestamps, and selected session relationships and project metadata enter the native ledger. Paths remain hidden by default.

`CoreWorker` owns the Rust handle on a serial utility queue. Scanning and querying run off the main actor. A configuration change closes the old handle and opens a new engine; the Swift model discards results whose captured configuration no longer matches current settings. Usage polling waits for each refresh to finish before sleeping, avoiding overlapping scans.

The native ledger lives in `~/Library/Application Support/TokenCat/usage.sqlite3`. Complete JSONL records, parser state, and byte offsets commit together. Incomplete trailing records wait for the next scan. Stable event identities reconcile repeated records, archived copies, and revisions. Source deletion or rotation preserves already collected usage.

OpenCode uses individual `step-finish` records when available, excluding historical context copied into forked sessions and avoiding duplicate message totals. Reasoning belongs to output. Source reads use a consistent SQLite snapshot, including committed WAL data.

## Native upper-estimate policy

The native analyzer favors higher defensible usage observations when source metadata is ambiguous. This accounting policy lives entirely in Rust; it requires no changes to the macOS app, CLI presentation, C ABI, or dashboard JSON schema. Estimates describe available local evidence, not a guaranteed upper bound on requests absent from local logs.

- Input, cache read and cache write are mutually exclusive; output includes reasoning. Reasoning and cache-write TTL details are subsets, never additional total tokens. Cache write remains supported by all four adapters.
- Codex modern records use response IDs. Legacy records suppress unchanged cumulative consumption, but when cumulative deltas and last-response values disagree, select the higher complete normalized candidate. Category resets also retain positive deltas. Repeated last values without cumulative counters or a shared response ID are ambiguous requests, not proven duplicates. Contradictory input/cache or output/reasoning counters normalize upward and mark the event incomplete.
- An initial Codex cumulative total exceeding the last response retains the residual as historical usage with uncertain dates bounded above by the first report. Historical model attribution stays unknown; it is not priced as the current configured model. Baseline recovery does not add this residual again after recorded responses.
- Claude identities include request and message IDs when available, reconciling copied transcripts across sessions. UUIDs or deterministic source positions retain usage with missing message IDs. Revisions keep the higher coherent observation rather than splicing category maxima; cache-write aggregates retain larger TTL detail sums.
- OpenCode retains the larger of reported total and observed category sum, preserving unallocated tokens rather than inventing a classification. Known output or reasoning remains in output even if the other component is missing. Such partial records are marked incomplete.
- Antigravity compares aggregate output with thinking plus visible output and keeps the larger value. Generation/step snapshots keep the higher coherent observation. Retry usage in `ChatModelMetadata.retry_infos=17` and `CortexStepMetadata.retry_infos=28`, nested `RetryInfo.usage=2`, is collected as independent requests and reconciled by request identity. These retry wire paths follow the [reviewed ccusage parser](https://github.com/ccusage/ccusage/blob/3cee49479a16af37a7b4df7b0fd976537ec97018/rust/adapters/antigravity/src/parser.rs#L608-L685); they are not an additional official descriptor verification. Malformed retries do not discard valid sibling or primary usage.

Uncertain dates are stored as internal possible time intervals. Queries include each overlapping event once in summaries and model/session/provider/project totals, never in calendar buckets or latest-event timestamps. Therefore totals can exceed the timeline sum. Existing query warnings explain the difference. The legacy scan `undated_events`/`undated_tokens` fields count excluded usage; retained uncertain-date events do not increment them, so existing frontends do not incorrectly describe them as outside totals. Missing dates are not replaced with file modification time or today. Available session dates constrain intervals; first observation bounds the latest possible date when no source bound exists. Copied replay does not advance that observation bound.

Pricing preserves the existing minimum/maximum fields. Unallocated reported tokens contribute to maximum cost at the highest available rate for the identified model, considering possible context tiers. Token categories and pricing coverage remain factual; unknown models remain unpriced. Cache TTL and reasoning-rate ambiguity continue to produce cost ranges through the existing fields.

Analyzer-versioned cursors replay readable sources once and atomically replace superseded results. This also handles changed file identities at the same path. Copies sharing an obsolete ledger identity retire together, avoiding duplicate old/new results when a copy is unavailable. Normal rotation/deletion continues to retain ledger history. Existing higher observations for the same stable request identity remain retained; independent unavailable source history cannot be reconstructed and is preserved as collected.

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

Generations link to step metadata for timestamps and usage not yet flushed to the generation table. Usage with unresolved dates contributes once to overlapping upper-estimate totals, outside the calendar timeline; database modification time is not a substitute for a request date. Conflicting workspace URIs do not assign an arbitrary project.

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
