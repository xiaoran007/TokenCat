# TokenCat

TokenCat is a local-first, read-only CLI for inspecting AI coding agent usage on your own machine.

v0.1 focuses on:

- Codex local telemetry and archived session logs
- Gemini CLI local session files
- GitHub Copilot CLI detection and explicit unsupported diagnostics when no safe CLI telemetry source is available
- A dashboard-style default entry with optional API-equivalent price estimates

TokenCat never proxies requests, changes endpoints, touches OAuth/session credentials, or uploads prompt/response bodies.

## License

This project is licensed under GNU GPLv3. See [LICENSE](/Users/xiaoran/Desktop/code/TokenCat/LICENSE).

## Install

Python 3.11+ is required.

```bash
pipx install .
```

For development:

```bash
python3 -m pip install -e '.[dev]'
```

## Commands

```bash
tokencat
tokencat --since 30d
tokencat dashboard --provider gemini
tokencat sessions --provider codex --limit 20
tokencat models --provider gemini --json
tokencat doctor
tokencat pricing show
tokencat pricing refresh
```

`tokencat` without any subcommand now opens the default 7-day dashboard.

Dashboard and read commands support:

- `--provider codex|gemini|copilot`
- `--since` and `--until` using `7d`, `24h`, or ISO date/datetime
- `--json`
- `--no-price` to disable local price estimation

Session listing also supports:

- `--limit`
- `--model`
- `--show-title`
- `--show-path`

## Support Matrix

| Provider | v0.1 status | Notes |
| --- | --- | --- |
| Codex | Supported | Reads `~/.codex/archived_sessions/*.jsonl` and falls back to `~/.codex/state_*.sqlite`. |
| Gemini CLI | Supported | Reads `~/.gemini/tmp/**/chats/session-*.json` and non-sensitive settings metadata. |
| GitHub Copilot CLI | Detection only | Reports `partial`, `unsupported`, or `not_found`; does not treat IDE plugin state as CLI usage telemetry. |

## Dashboard UX

The default dashboard is human-first and terminal-native:

- A headline status bar with provider health and pricing source
- Metric cards for sessions, total tokens, estimated cost, pricing coverage, models, and providers
- A daily usage table for the current time window
- Top models and recent sessions panels for quick drill-down

The goal is a denser, more technical CLI feel without switching to a full-screen TUI.

## Pricing

TokenCat can estimate API-equivalent cost for models that have an exact entry in the local pricing catalog.

- Pricing is offline by default through a bundled catalog shipped with the package.
- `tokencat pricing refresh` can refresh the catalog from official pricing pages and cache it under `~/.tokencat/pricing/catalog.json`.
- Unknown or historically renamed models are intentionally marked `unknown` instead of being guessed.
- Cost totals always include a pricing coverage figure so unknown or unattributed tokens are visible.

Current pricing references:

- [OpenAI API pricing](https://openai.com/api/pricing/)
- [OpenAI Codex pricing](https://developers.openai.com/codex/pricing/)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [GitHub Copilot plans](https://docs.github.com/en/copilot/about-github-copilot/subscription-plans-for-github-copilot)

## Privacy Defaults

- Default output is redacted: no session title, no cwd, no source file path.
- Raw prompt/response bodies are never emitted.
- OAuth/session tokens and auth files are never read for reporting.
- Stable anonymous session IDs are derived from provider + raw session ID using `sha256`.
- Price refresh writes only TokenCat's own cache and never mutates provider logs.

To opt into more local metadata for session listings:

```bash
tokencat sessions --show-title --show-path
```

## JSON Output

JSON commands use a stable v0.1 top-level shape:

- `generated_at`
- `filters`
- `providers`
- `summary` or `items`
- `warnings`

The dashboard JSON nests its richer view under `summary` with:

- `overview`
- `daily`
- `top_models`
- `recent_sessions`
- `pricing`

## macOS-first Scope

v0.1 is implemented for macOS path layouts first. Linux path hooks are intentionally left easy to extend, but Linux and Windows are not yet guaranteed support targets in this release.
