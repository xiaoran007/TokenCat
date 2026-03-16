# TokenCat

TokenCat is a local-first, read-only CLI for understanding how AI coding agents are being used on your machine.

If you jump between Codex, Gemini CLI, and Copilot CLI, TokenCat gives you one terminal-native view for sessions, models, tokens, and API-equivalent cost estimates without proxying traffic, rewriting endpoints, or touching your prompts and responses.

![TokenCat dashboard demo](https://files.catbox.moe/tf9mur.png)

## Why TokenCat

- One place to inspect Codex and Gemini CLI usage, plus Copilot CLI detection
- A default 0-argument dashboard: just run `tokencat`
- Read-only by design: no proxying, no interception, no auth-token handling
- Local pricing estimates with clear coverage for unknown or unattributed usage
- JSON output for scripts and terminal output for humans

## Install

Python 3.11+ is required.

```bash
pipx install tokencat
```

Upgrade later with:

```bash
pipx upgrade tokencat
```

If you want to try the repo directly:

```bash
pipx install .
```

## Quick Start

Open the dashboard:

```bash
tokencat
```

Look at a longer window:

```bash
tokencat --since 30d
```

Focus on one tool:

```bash
tokencat dashboard --provider codex
```

List recent sessions:

```bash
tokencat sessions --provider codex --limit 20
```

Inspect model totals:

```bash
tokencat models --provider gemini
```

Check local detection and health:

```bash
tokencat doctor
```

Inspect or refresh pricing data:

```bash
tokencat pricing show
tokencat pricing refresh
```

## What You Get

- A dense terminal dashboard with provider health, token totals, pricing coverage, daily usage, and recent sessions
- Session-level views with anonymous IDs by default
- Model-level aggregation across supported tools
- A bundled pricing catalog, plus a local cache that can refresh itself on first use
- Stable JSON envelopes for scripting and automation

## Supported Tools

| Tool | Status | Notes |
| --- | --- | --- |
| Codex | Supported | Reads `~/.codex/sessions/**/*.jsonl` and `~/.codex/archived_sessions/*.jsonl`, then falls back to `~/.codex/state_*.sqlite` when needed. |
| Gemini CLI | Supported | Reads `~/.gemini/tmp/**/chats/session-*.json` and non-sensitive settings metadata. |
| GitHub Copilot CLI | Detection only | Reports `partial`, `unsupported`, or `not_found`; does not treat editor plugin state as CLI usage telemetry. |

## Pricing

TokenCat can estimate API-equivalent cost for models with known pricing data.

- Pricing works offline by default using the bundled catalog shipped with the package.
- On first pricing use, TokenCat silently tries to refresh its own cache under `~/.tokencat/pricing/`.
- If that refresh fails, it quietly falls back to the bundled catalog.
- `tokencat pricing refresh` manually refreshes the local cache.
- Unknown or historically renamed models are shown clearly instead of being guessed.

Current pricing references:

- [OpenAI API pricing](https://openai.com/api/pricing/)
- [OpenAI Codex pricing](https://developers.openai.com/codex/pricing/)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [GitHub Copilot plans](https://docs.github.com/en/copilot/about-github-copilot/subscription-plans-for-github-copilot)

## Privacy

TokenCat is intentionally conservative.

- It only reads local files that already exist on your machine.
- It does not proxy traffic or intercept requests.
- It does not rewrite provider endpoints or mutate provider sessions.
- It does not read OAuth credentials for reporting.
- It never prints raw prompt or response bodies.
- It redacts sensitive local metadata by default.

To reveal more local metadata in session listings:

```bash
tokencat sessions --show-title --show-path
```

## JSON Output

All JSON commands keep a stable top-level shape:

- `generated_at`
- `filters`
- `providers`
- `summary` or `items`
- `warnings`

That makes TokenCat easy to pipe into scripts, local dashboards, or personal automation.

## Common Flags

- `--provider codex|gemini|copilot`
- `--since` / `--until` with values like `7d`, `24h`, or ISO dates
- `--json`
- `--no-price`

Session listings also support:

- `--limit`
- `--model`
- `--show-title`
- `--show-path`

## Limits

- TokenCat is macOS-first today.
- Linux path hooks are present, but Linux is not yet a polished target.
- Windows is not yet supported.
- Copilot support is currently detection-only, not full usage accounting.
- Cost is an estimate, not your actual bill.

## License

TokenCat is licensed under GNU GPLv3. See [LICENSE](LICENSE).
