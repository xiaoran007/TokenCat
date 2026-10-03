# TokenCat

<img src="macos/Branding/TokenCatAppIcon.png" width="96" height="96" alt="TokenCat's round, front-facing cat logo">

[![PyPI](https://img.shields.io/pypi/v/tokencat?style=flat-square&logo=pypi&logoColor=white&label=PyPI&color=0f766e)](https://pypi.org/project/tokencat/)
[![Python](https://img.shields.io/pypi/pyversions/tokencat?style=flat-square&logo=python&logoColor=white&label=Python&color=2563eb)](https://pypi.org/project/tokencat/)
[![License](https://img.shields.io/pypi/l/tokencat?style=flat-square&label=License&color=4b5563)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-111827?style=flat-square&logo=linux&logoColor=white)](#limits)
[![Local first](https://img.shields.io/badge/privacy-local%20first-16a34a?style=flat-square)](#privacy)
[![Read only](https://img.shields.io/badge/mode-read%20only-7c3aed?style=flat-square)](#privacy)

TokenCat is a local-first usage inspector for AI coding agents. This branch adds an independent native macOS menu bar app backed by a shared Rust core. The existing Python CLI remains available while CLI integration with the new core is developed separately.

Run `tokencat` to get a terminal dashboard for Codex, Claude Code, Gemini CLI, Antigravity, OpenCode, GitHub Copilot Chat/Agent, and GitHub Copilot CLI. TokenCat reads the telemetry files those tools already keep locally; it does not proxy requests, rewrite endpoints, read credentials, or print prompt and response bodies.

<!-- ![TokenCat dashboard demo](https://files.catbox.moe/rsuhuk.png) -->
![TokenCat dashboard demo](https://files.catbox.moe/wo8lwy.png)

## Why TokenCat

- One dashboard for several coding agents: Codex, Claude Code, Gemini CLI, Antigravity, OpenCode, VS Code Copilot Chat/Agent, and Copilot CLI.
- Zero-provider setup for normal use: install it and run `tokencat`.
- Privacy-first scanning: local files only, anonymous session IDs by default, no OAuth/session token reporting.
- Cost estimates with clear coverage: bundled pricing works offline, and unknown models stay visible instead of being guessed.
- Useful terminal views: dashboard, sessions, models, daily usage, doctor, pricing, and JSON output for scripts.
- Multi-machine rollups: trusted TokenCat nodes can be aggregated with `--lan`, including SSH snapshot hosts from `~/.ssh/config`.

## Install

### Native macOS app (source build)

The native app requires macOS 14 or newer, a Rust toolchain, and Xcode's Swift toolchain with the macOS 26 SDK or newer. It runs independently of Python and pipx. Build it locally from this checkout:

```bash
bash macos/scripts/build-app.sh
open build/TokenCat.app
```

The script compiles the Rust static library and Swift app, bundles the app icon, vector logos and localization resources, and applies a local ad-hoc signature. Local source builds do not require a publisher's Developer ID certificate or notarization. Distribution of prebuilt apps is a separate release workflow. Move the app to `/Applications` before enabling **Launch at Login** in Settings.

The round, front-facing cat appears in the app icon, menu panel and dashboard. The menu bar uses a monochrome vector template that follows the system appearance, with wider facial cutouts for small sizes. Editable SVG artwork and the app icon live in [`macos/Branding`](macos/Branding); regenerate the SVG, PDF templates, PNG and ICNS after changing the curves with `swift macos/scripts/generate-icons.swift` on macOS. The generator uses only system frameworks and `iconutil`.

The menu bar label shows today's estimated API-equivalent cost. Its panel leads with recorded tokens and a secondary cost estimate, followed by coding tools, top models, a token timeline, and recent tasks. The panel and dashboard share a Today / 7 days / 30 days selector; opening a task preserves that selected period. Open the dashboard for model, project, session, and subagent details. English (US) and Simplified Chinese are included, with system language, appearance, number formatting, and time zone support.

The menu reserves a visible content viewport and keeps its refresh and dashboard controls visible while longer content scrolls. It contains local usage statistics, with no account, subscription, or quota-management sections. The dashboard adapts its overview cards to the window width. Switch the dashboard activity chart between known API cost and recorded tokens, then hover or click to inspect a time bucket in the configured time zone. Usage without matching prices remains explicitly unpriced.

Token totals lead with K/M/B/T notation and show the exact count in smaller text. These abbreviations and familiar terms such as Token, Dashboard, Cache read/write, and Subagent stay in English in the Chinese interface. The settings button and **Command–comma** open the same reusable settings window. On macOS 26 and 27, the menu uses native Liquid Glass; earlier systems retain the existing material. Reduce Transparency and increased contrast use an opaque surface for readability.

Model, project, and task pages have independent searches and can sort by cost, tokens, or latest usage. Task search includes subagents; task rows show the whole linked family's cost, while task details separate direct usage from the family total and let you navigate between parents and children. Changing the time range or data settings clears incompatible snapshots while fresh data loads. Turning off project paths immediately clears snapshots containing visible paths.

The native app supports **Codex, Claude Code, OpenCode, and Antigravity**. Gemini CLI and Copilot are outside the native app's scope; their existing Python CLI adapters are unchanged. LAN aggregation and CLI packaging changes remain separate work.

Native collection uses a persistent SQLite ledger in `~/Library/Application Support/TokenCat/usage.sqlite3`. Complete JSONL records, parser state, and file offsets are committed together. Refresh defaults to two seconds and resumes immediately on wake. Incomplete trailing records wait for completion; repeated responses, archived copies, and Claude message revisions reconcile by logical event identity. Provider log rotation does not erase previously collected usage.

Settings can override each harness's local data roots. Native collection reads the following allowlisted usage and session metadata; project paths remain hidden in the interface by default:

| Harness | Native data sources |
| --- | --- |
| Codex | `sessions` and `archived_sessions` JSONL under `~/.codex`. |
| Claude Code | `projects` JSONL under `~/.claude` and `~/.config/claude`. |
| OpenCode | `~/.local/share/opencode/opencode.db`, or the corresponding `XDG_DATA_HOME` directory. |
| Antigravity | `conversations/*.db` under `~/.gemini/antigravity` and `~/.gemini/antigravity-cli`. |

OpenCode collection uses individual `step-finish` usage records when available, avoiding both lost intermediate requests and double counting with message totals. It handles message revisions, excludes historical context copied into forked sessions, and reads active SQLite WAL transactions. Only usage, model/service identity, timestamps, project directories, and parent-session relationships are projected from the database; conversation and tool bodies are excluded.

Antigravity collection was checked against the application's protobuf descriptors. Its model and API-provider enum fields are not token counters; uncached input and cache reads are separate, and output already includes thinking. The collector links `gen_metadata` to `steps.metadata` for actual per-request timestamps and usage not yet flushed to the generation table. Requests without a confirmed date are reported separately and excluded from period totals rather than assigned the database modification time. App/CLI copies reconcile by stable request identity and revision. Selective SQLite reads obtain only the required metadata ranges, including local project URIs and parent-conversation IDs; agent scripts, prompt/response bodies, headers, and credentials are not read. Conversations with multiple workspaces are not assigned arbitrarily to one project.

Antigravity refresh uses read-only incremental BLOB handles for protobuf framing and allowlisted metadata ranges. Each Rust engine retains its own read-only source connections and parsed usage metadata, checking `PRAGMA data_version` on the same connection to detect updates, including WAL writes. Unchanged databases reuse metadata; changed databases are reparsed in a consistent transaction. Each source connection has a 256 KiB SQLite page-cache budget. Replaced files reopen, removed paths release their cache entries, and source read failures discard the entry and remain visible in scan diagnostics. Changing the core configuration creates a new engine and releases the previous cache. The refresh interval remains unchanged.

Native pricing uses a pinned [LiteLLM snapshot](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) bundled with the app, or a validated downloaded snapshot. Automatic online checks are enabled by default every **24 hours** while the app is running; Settings offers **6, 24, or 168 hours**, an on/off switch, and a manual online refresh button. Conditional requests use ETags. The downloaded catalog and its timestamps are stored together in `~/Library/Application Support/TokenCat/pricing/litellm-cache.json`; a failed update leaves the loaded prices intact and shows the update status in Settings. Selecting a custom catalog JSON disables automatic and manual network updates until it is reset.

The collection harness and the recorded model service (`model_provider`) are separate identities. Price resolution prefers official model-provider records, then an explicitly identified third-party record. It does not substitute a similar-looking model name or select arbitrarily among ambiguous matches. The one deliberate mapping is **`codex-auto-review` → `gpt-5.6-luna`**; the cost details expose this mapping and its pricing source. Missing models, unmatched identities, and missing prices appear as neutral **no price record** information rather than an error. Their recorded tokens still contribute to token totals.

Costs use LiteLLM's standard token rates and remain API-equivalent estimates, including for subscription users; Priority, Flex, Batch, tool charges, and regional billing adjustments are not applied. The catalog identity, retrieval date, and pricing sources are visible in the dashboard. Reasoning is part of output, and cached input is separated from uncached input. An explicitly zero rate means free; a missing rate remains unknown. Missing cache TTL or incomplete long-context information produces uncertainty instead of a guessed exact amount. The currently selected snapshot applies to every displayed period; it does not reconstruct historical invoices, subscription charges, or time-limited promotional rates. Updating prices leaves the underlying token ledger unchanged.

Run the test suites from the checkout:

```bash
.venv/bin/pytest -q
bash macos/scripts/test.sh
```

The native test script links the Swift package to the exact Rust archive produced by the tests. On Linux, run `cargo test --locked --manifest-path native/Cargo.toml` for the core alone. The Rust collector supports macOS and Linux; the SwiftUI app currently targets macOS only.

#### Isolated Antigravity refresh experiment

The [standalone benchmark](experiments/antigravity-refresh/run.py) compares the original collector, three prototypes, and the implemented production collector. The original workspace and its test fixture helpers are pinned to Git revision `8f41381` (override with `--baseline-ref`); the production variant uses the current checkout. Prototypes use selective SQLite incremental BLOB reads, BLOB reads plus a metadata cache, and the same cache with a 256 KiB SQLite page-cache budget per read-only connection. The runner copies workspaces into a temporary directory, uses offline release builds, and runs Rust tests for each variant. It does not replace the running app, its linked library, or its usage database. All source databases and skipped body fields are synthetic.

```bash
.venv/bin/python experiments/antigravity-refresh/run.py --output /tmp/tokencat-refresh-results
```

This experiment requires macOS, the baseline Git revision, and the existing Cargo dependency cache. Prototypes enable the already installed rusqlite crate's `blob` feature in the temporary copies; production already enables it. Results include per-scan wall time and process CPU time, whole-program peak RSS, test logs, and generated source variants. `--workspace` can reuse the temporary compilation directory recorded in `workspace.txt`; `--resume --variants production` reuses recorded baseline results and measures only production. The small profile has 4 databases with 20 generations each and 4 KiB skipped fields; the large profile has 8 databases with 80 generations each and 256 KiB skipped fields. Unchanged scans use the median of 9 rounds. Cold ingestion, WAL updates to historical rows, WAL appends, checkpointing, and atomic database replacement each use one round. “Cold” means the collector's first scan, not an empty operating-system file cache. All variants must produce identical usage events, session metadata, and scan reports for every scenario.

Recorded on macOS ARM64, October 2, 2026, with the app still running. The large-profile unchanged scan produced:

| Implementation | Wall time | Process CPU time | Whole-program peak RSS |
| --- | ---: | ---: | ---: |
| Original collector | 1294.16 ms | 1291.58 ms | 38.52 MiB |
| Incremental BLOB reads | 40.22 ms | 40.15 ms | 38.03 MiB |
| BLOB reads + metadata cache | 4.67 ms | 4.67 ms | 58.94 MiB |
| Cache with 256 KiB SQLite page-cache budget | 4.65 ms | 4.65 ms | 42.05 MiB |

The bounded-cache variant's large-profile historical WAL update took 13.42 ms versus 1241.18 ms for the current collector; a WAL append took 12.34 ms versus 1362.02 ms. These changed-source measurements are single samples. Each variant passed all 84 existing Rust tests, and the Python suite passed all 94 tests. [Recorded results](experiments/antigravity-refresh/results.json) include every scenario and the comparison digests. Peak RSS includes fixture creation and all scans, so it is not the cache's isolated allocation or the app's memory footprint. Runs used a fixed variant order; small timing differences should not be treated as significant.

The [final implementation measurement](experiments/antigravity-refresh/production-results.json), taken after test compilation finished, recorded **5.63 ms wall time, 5.49 ms process CPU time, and 42.83 MiB whole-program peak RSS** for the large unchanged profile. All event, session metadata, and scan-report digests matched the original baseline. The production implementation passed 90 Rust tests, 45 Swift tests, and 94 Python tests. These synthetic collection results do not measure whole-app CPU or memory.

Implemented production changes:

1. A read-only incremental BLOB handle per metadata row replaces per-byte `SELECT substr(...)` queries. The reader accesses exactly the existing protobuf framing and allowlisted metadata ranges, retaining the consistent SQLite read transaction and parser validation. Skipped body ranges are not prefetched.
2. A read-only connection and parsed usage metadata per discovered Antigravity database belong to the Rust `Engine`. The cache compares `PRAGMA data_version` on that same connection across scans; SQLite main-file modification times alone cannot detect WAL updates. Device/inode identity detects replaced files. Only changed databases are reparsed. If the version changes while parsing, the result remains uncached so the following scan reparses it.
3. Each source connection uses a 256 KiB page-cache budget (`PRAGMA cache_size=-256`, a connection-local setting; this is not a hard process-memory cap). Removed paths release connections and metadata, and the entire cache is released with its engine. Production uses engine ownership, unlike the experimental thread-local cache. Read errors discard the source cache entry and remain visible, without silently returning an old cached snapshot. Tests cover lifecycle, warning replay, error recovery, WAL changes, and concurrent appends.

The reader and cache are committed separately. Rebuild manually with `bash macos/scripts/build-app.sh`, quit the old app, and launch the newly built app before measuring windows closed and open, including CPU, memory, and long-running behavior. This benchmark isolates Antigravity collection; it does not predict whole-app CPU usage or measure SwiftUI rendering, other providers, or dashboard queries.

### Existing CLI

TokenCat requires Python 3.9 or newer.

```bash
pipx install tokencat
```

Upgrade later with:

```bash
pipx upgrade tokencat
```

Optional mDNS discovery and advertising for HTTP LAN nodes requires the `mdns` extra:

```bash
pipx install "tokencat[mdns]"
```

To try a checkout of this repository:

```bash
pipx install .
```

With mDNS support from a checkout:

```bash
pipx install ".[mdns]"
```

## Quick Start

Open the default 7-day dashboard:

```bash
tokencat
```

Look farther back:

```bash
tokencat --since 30d
tokencat --since 2026-01-01
```

Check what TokenCat can see on this machine:

```bash
tokencat doctor
```

## LAN and SSH Nodes

TokenCat can roll up trusted machines without sending prompts or responses. Each node exposes or returns a read-only snapshot.

SSH-configured machines and containers are the recommended path and do not need a long-running HTTP server or mDNS. If a host appears in `~/.ssh/config` and has `tokencat` available remotely, `tokencat nodes --trust` can add it as an SSH snapshot node. Later, `tokencat --lan` runs `ssh <host> tokencat snapshot --json` and aggregates the returned snapshot.

Aggregate trusted nodes:

```bash
tokencat dashboard --lan
tokencat summary --lan
tokencat sessions --lan
```

Remove trusted nodes:

```bash
tokencat nodes --remove
```

You can also start an HTTP node on another machine. Install `tokencat[mdns]` when you want the node to advertise itself over mDNS:

```bash
export TOKENCAT_NODE_TOKEN="choose-a-shared-secret"
tokencat serve --lan
```

`tokencat serve` starts in the background by default:

```bash
tokencat serve --status
tokencat serve --logs
tokencat serve --stop
```

For foreground debugging:

```bash
tokencat serve --lan --foreground
```

Discover and trust nodes:

```bash
tokencat nodes --trust
```

Without the `mdns` extra, `tokencat nodes --trust` still lists SSH candidates from `~/.ssh/config`; it only skips automatic mDNS discovery.

If mDNS is blocked by Docker Desktop, VPNs, or network policy, trust a node by URL:

```bash
tokencat nodes --url http://127.0.0.1:8765 --trust
```

## Advanced Usage
Focus on one provider:

```bash
tokencat dashboard --provider codex
tokencat sessions --provider claude --limit 20
tokencat models --provider gemini
tokencat daily --provider copilot
tokencat sessions --provider opencode
```

Change the terminal theme:

```bash
tokencat --theme light
tokencat dashboard --theme dark
```

Use structured output:

```bash
tokencat summary --json
tokencat sessions --json --show-title --show-path
```

## JSON Output

Commands with `--json` emit stable envelopes with:

- `generated_at`
- `filters`
- `providers`
- `summary` or `items`
- `warnings`

This makes TokenCat easy to pipe into local scripts, dashboards, or personal automation.

## Configuration

This section describes the existing Python CLI. Native-app data roots, settings, and storage paths are described in [Native macOS app](#native-macos-app-source-build).

Most users do not need a config file. TokenCat discovers local agent data from the standard locations for each tool.

| Provider | What TokenCat Reads | Optional Configuration |
| --- | --- | --- |
| Codex | `~/.codex/sessions/**/*.jsonl`, `~/.codex/archived_sessions/*.jsonl`, and `~/.codex/state_*.sqlite` as a fallback. | None. |
| Claude Code | `projects/**/*.jsonl` under the Claude config root. | Set `CLAUDE_CONFIG_DIR` to one or more comma-separated roots. Without it, TokenCat checks `$XDG_CONFIG_HOME/claude`, `~/.config/claude`, and legacy `~/.claude`. |
| Gemini CLI | `~/.gemini/tmp/**/chats/session-*.json` plus non-sensitive settings metadata from `~/.gemini/settings.json`. | None. |
| Antigravity | Usage metadata from `conversations/*.db` under `~/.gemini/antigravity` and `~/.gemini/antigravity-cli`. TokenCat queries only the `gen_metadata` table. | None. |
| OpenCode | Assistant message model, token, and timestamp fields plus session metadata from `~/.local/share/opencode/opencode.db`. TokenCat does not read message or tool bodies. | Honors `XDG_DATA_HOME` when set. |
| GitHub Copilot | VS Code `workspaceStorage/*/chatSessions/*.json|*.jsonl` and Copilot CLI shutdown summaries under `~/.copilot/session-state/*/events.jsonl`. | None. Active Copilot CLI sessions without a shutdown summary are reported as partial in `doctor`. |

Common environment variables:

| Variable | Used For |
| --- | --- |
| `CLAUDE_CONFIG_DIR` | Overrides Claude Code data roots. Multiple roots can be separated with commas. |
| `XDG_DATA_HOME` | Locates the OpenCode SQLite database under `opencode/opencode.db`. |
| `COLORFGBG` | Helps `--theme auto` detect light terminals. TokenCat falls back to the dark palette when it cannot tell. |
| `TOKENCAT_NODE_NAME` | Sets the display name for this machine when using TokenCat nodes. Defaults to the hostname. |
| `TOKENCAT_NODE_TOKEN` | Default bearer-token environment variable for HTTP LAN nodes. |

Local TokenCat state is kept under `~/.tokencat/`:

- `~/.tokencat/pricing/` stores the refreshed pricing cache.
- `~/.tokencat/node.json` stores this machine's node identity.
- `~/.tokencat/nodes/trust.json` stores trusted LAN or SSH nodes.
- `~/.tokencat/logs/node.log` and `~/.tokencat/node.pid` are used by the detached node server.

## Commands

| Command | Purpose |
| --- | --- |
| `tokencat` / `tokencat dashboard` | Terminal dashboard with provider health, token totals, pricing coverage, timeline, top models, and recent sessions. |
| `tokencat summary` | Compact totals by provider, model count, tokens, and estimated API cost. |
| `tokencat sessions` | Session list with anonymous IDs by default. Use `--show-title` and `--show-path` when you want local metadata. |
| `tokencat models` | Model-level aggregation across providers. |
| `tokencat daily` | Daily usage totals for the selected window. |
| `tokencat doctor` | Detection and health report for local providers and pricing data. |
| `tokencat pricing show` | Inspect catalog freshness, coverage, and unknown models. |
| `tokencat pricing refresh` | Refresh the user pricing cache under `~/.tokencat/pricing/`. |
| `tokencat serve` | Start a read-only local snapshot node. |
| `tokencat nodes` | Discover, trust, inspect, or remove LAN and SSH nodes. |
| `tokencat snapshot --json` | Emit a machine-readable snapshot for remote aggregation. |

Useful flags:

```bash
--provider codex|claude|gemini|antigravity|copilot|opencode
--since 7d
--until 2026-05-31
--daily | --weekly | --monthly    # dashboard usage buckets
--theme auto|dark|light
--json
--no-price
--lan
```

Session listings also support:

```bash
--limit 50
--model gpt-5-codex
--show-title
--show-path
```

## Pricing

This section describes the existing Python CLI's pricing behavior; the native app uses the separate catalog workflow documented [above](#native-macos-app-source-build). The CLI estimates API-equivalent cost when a model can be matched to known pricing data.

- Pricing works offline with the bundled catalog shipped in the package.
- On first pricing use, TokenCat silently tries to refresh a local cache under `~/.tokencat/pricing/`.
- If the refresh fails, it quietly falls back to the bundled catalog.
- `tokencat pricing refresh` refreshes the local cache manually.
- Resolution is source-aware: direct source pricing first, then official API pricing for the model family, then OpenRouter as the marketplace fallback.
- The internal `codex-auto-review` label is estimated using `gpt-5.4-mini` pricing because OpenAI does not publish a direct model mapping for that label.
- JSON output includes `pricing_source` and `pricing_model` when a row is priced.
- Unknown, renamed, redirected, or unattributed models remain visible with explicit pricing status.

Current pricing references:

- [OpenAI API pricing](https://openai.com/api/pricing/)
- [OpenAI Codex pricing](https://developers.openai.com/codex/pricing/)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Anthropic models and pricing](https://docs.anthropic.com/en/docs/models-overview)
- [xAI models](https://docs.x.ai/docs/models)
- [OpenRouter pricing](https://openrouter.ai/pricing)
- [GitHub Copilot plans](https://docs.github.com/en/copilot/about-github-copilot/subscription-plans-for-github-copilot)

## Privacy

TokenCat is intentionally conservative.

- Reads local telemetry files only.
- Does not proxy, intercept, or replay model requests.
- Does not rewrite provider endpoints.
- Does not read OAuth/session credentials for reporting.
- Does not print raw prompt or response bodies.
- Uses anonymous session IDs by default.
- Shows titles and paths only when you pass `--show-title` or `--show-path`.

## Limits

- TokenCat supports macOS and Linux, including typical Docker/containerized Linux environments where the relevant agent state is mounted or available locally.
- Windows is not yet supported.
- SSH LAN rollups work in the base install. mDNS discovery and advertising for HTTP LAN nodes requires `tokencat[mdns]`.
- mDNS can be unreliable through Docker Desktop, VPNs, or restrictive networks. Use `tokencat nodes --url ... --trust` or SSH nodes in those environments.
- Copilot CLI usage is counted from shutdown summaries; active CLI sessions without shutdown summaries are detected but not counted yet.
- Cost is an estimate, not your actual bill.

## License

TokenCat is licensed under GNU GPLv3. See [LICENSE](LICENSE).
