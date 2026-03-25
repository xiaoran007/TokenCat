# TokenCat

[![PyPI Version](https://img.shields.io/pypi/v/tokencat?style=for-the-badge&logo=pypi&logoColor=white&label=PyPI&color=1f6feb)](https://pypi.org/project/tokencat/)
[![Python Versions](https://img.shields.io/pypi/pyversions/tokencat?style=for-the-badge&logo=python&logoColor=white&label=Python&color=3776ab)](https://pypi.org/project/tokencat/)
[![License](https://img.shields.io/pypi/l/tokencat?style=for-the-badge&label=License&color=3fb950)](LICENSE)

[![Supported](https://img.shields.io/badge/Supported-Codex%20%7C%20Claude%20%7C%20Gemini%20%7C%20Copilot-6e7781?style=for-the-badge&labelColor=3a3a3a)](#supported-tools)
[![Platform](https://img.shields.io/badge/Platform-macOS--first-f78166?style=for-the-badge&labelColor=3a3a3a)](#limits)

TokenCat is a local-first, read-only CLI for understanding how AI coding agents are being used on your machine.

If you jump between Codex, Claude Code, Gemini CLI, and Copilot CLI, TokenCat gives you one terminal-native view for sessions, models, tokens, and API-equivalent cost estimates without proxying traffic, rewriting endpoints, or touching your prompts and responses.

![TokenCat dashboard demo](https://files.catbox.moe/rsuhuk.png)

## Why TokenCat

- One place to inspect Codex, Claude Code, Gemini CLI, VS Code Copilot Chat/Agent usage, and Copilot CLI session-state totals
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

Inspect daily totals:

```bash
tokencat daily --provider claude
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
- Daily time-series aggregation across supported tools
- A bundled pricing catalog, plus a local cache that can refresh itself on first use
- Stable JSON envelopes for scripting and automation

## Supported Tools

| Tool | Status | Notes |
| --- | --- | --- |
| Codex | Supported | Reads `~/.codex/sessions/**/*.jsonl` and `~/.codex/archived_sessions/*.jsonl`, then falls back to `~/.codex/state_*.sqlite` when needed. |
| Claude Code | Supported | Reads `projects/**/*.jsonl` under `CLAUDE_CONFIG_DIR` when set, otherwise scans both `~/.config/claude` and legacy `~/.claude`. Preserves exact observed model names, including redirected non-Anthropic models and subagent sessions. |
| Gemini CLI | Supported | Reads `~/.gemini/tmp/**/chats/session-*.json` and non-sensitive settings metadata. |
| GitHub Copilot | Supported | Reads VS Code `workspaceStorage/*/chatSessions/*.json|*.jsonl` for Copilot Chat/Agent sessions and `~/.copilot/session-state/*/events.jsonl` for standalone Copilot CLI shutdown summaries. Active CLI sessions without shutdown summaries still show as partial in `doctor`. |

## Pricing

TokenCat can estimate API-equivalent cost for models with known pricing data.

- Pricing works offline by default using the bundled catalog shipped with the package.
- On first pricing use, TokenCat silently tries to refresh its own cache under `~/.tokencat/pricing/`.
- If that refresh fails, it quietly falls back to the bundled catalog.
- `tokencat pricing refresh` manually refreshes the local cache.
- Pricing resolution is source-aware: direct source price first, then official API price, then OpenRouter as the marketplace fallback.
- JSON output includes `pricing_source` so you can see whether a session or model was priced from the direct source, an official vendor catalog, or OpenRouter.
- Metadata-only rows in the upstream dataset are ignored; TokenCat only treats entries with explicit price fields as priced.
- Unknown or historically renamed models are shown clearly instead of being guessed.

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
- `--provider codex|claude|gemini|copilot`
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
- Copilot support covers VS Code Chat/Agent sessions plus standalone CLI shutdown summaries under `~/.copilot/session-state/`. Active CLI sessions without a shutdown summary are detected but not yet counted.
- Cost is an estimate, not your actual bill.

## License

TokenCat is licensed under GNU GPLv3. See [LICENSE](LICENSE).
