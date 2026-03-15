# TokenCat

TokenCat is a local-first, read-only CLI for understanding how AI coding agents are being used on your machine.

It scans local Codex and Gemini CLI logs, summarizes tokens, sessions, and models in one place, and can optionally estimate API-equivalent cost without touching your prompts, responses, auth credentials, or network endpoints.

![TokenCat dashboard demo](https://files.catbox.moe/2uelh2.png)

## Why TokenCat

- One dashboard for Codex, Gemini CLI, and Copilot CLI detection
- Read-only by design: no proxying, no request interception, no endpoint rewrites
- Local-first privacy defaults: no raw prompt/response output, no OAuth/session token access
- Useful in both human and script workflows: terminal dashboard by default, JSON when needed

## Features

- Default 0-argument dashboard: `tokencat`
- Session-level and model-level usage views
- Daily usage breakdown with concrete model rows
- Local pricing catalog with optional refresh for cost estimation
- Stable anonymous session IDs by default
- Explicit diagnostics for unsupported or missing providers

## Install

Python 3.11+ is required.

Install with `pipx`:

```bash
pipx install tokencat
```

Upgrade later with:

```bash
pipx upgrade tokencat
```

If you want to run from a local checkout instead:

```bash
pipx install .
```

For maintainers preparing a release from a local checkout:

```bash
make install-release
make release-check
```

## Quick Start

Open the default dashboard:

```bash
tokencat
```

Inspect a longer time window:

```bash
tokencat --since 30d
```

Focus on one provider:

```bash
tokencat dashboard --provider codex
```

List recent sessions:

```bash
tokencat sessions --provider codex --limit 20
```

See model totals:

```bash
tokencat models --provider gemini
```

Check local provider detection:

```bash
tokencat doctor
```

Inspect pricing coverage:

```bash
tokencat pricing show
```

Refresh the local pricing cache:

```bash
tokencat pricing refresh
```

## Commands

```bash
tokencat
tokencat dashboard --provider codex
tokencat summary --json
tokencat sessions --provider gemini --limit 20
tokencat models --since 30d
tokencat doctor
tokencat pricing show
tokencat pricing refresh
```

Common flags:

- `--provider codex|gemini|copilot`
- `--since` / `--until` with values like `7d`, `24h`, or ISO dates
- `--json`
- `--no-price`

Extra session flags:

- `--limit`
- `--model`
- `--show-title`
- `--show-path`

## Supported Providers

| Provider | Status | Notes |
| --- | --- | --- |
| Codex | Supported | Reads `~/.codex/sessions/**/*.jsonl` and `~/.codex/archived_sessions/*.jsonl`, then falls back to `~/.codex/state_*.sqlite` when needed. |
| Gemini CLI | Supported | Reads `~/.gemini/tmp/**/chats/session-*.json` and non-sensitive settings metadata. |
| GitHub Copilot CLI | Detection only | Reports `partial`, `unsupported`, or `not_found`; does not treat editor plugin state as CLI usage telemetry. |

## Privacy

TokenCat is intentionally conservative.

- It only reads local files that already exist on your machine.
- It does not proxy traffic or intercept requests.
- It does not modify provider endpoints or sessions.
- It does not read OAuth credentials for reporting.
- It never outputs raw prompt or response bodies.
- It redacts sensitive local metadata by default.

By default, output does not include session titles, cwd paths, or raw session IDs. If you want more local detail in session listings:

```bash
tokencat sessions --show-title --show-path
```

## Pricing

TokenCat can estimate API-equivalent cost for models with a known pricing entry.

- Pricing works offline by default using a bundled catalog.
- `tokencat pricing refresh` updates TokenCat's own local cache at `~/.tokencat/pricing/catalog.json`.
- Unknown or old model names are shown as `unknown` instead of being guessed.
- Coverage is always shown so you can see how much usage was actually priceable.

Current pricing references:

- [OpenAI API pricing](https://openai.com/api/pricing/)
- [OpenAI Codex pricing](https://developers.openai.com/codex/pricing/)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [GitHub Copilot plans](https://docs.github.com/en/copilot/about-github-copilot/subscription-plans-for-github-copilot)

## JSON Output

All JSON commands keep a stable top-level shape:

- `generated_at`
- `filters`
- `providers`
- `summary` or `items`
- `warnings`

This makes TokenCat easy to use in scripts and local automation.

## Scope and Limitations

- v0.1 is macOS-first.
- Linux path hooks are intentionally easy to extend, but Linux is not yet a polished support target.
- Windows is not yet supported.
- Copilot support is currently detection-only, not full usage accounting.
- Cost is an estimate, not your actual bill.

## License

TokenCat is licensed under GNU GPLv3. See [LICENSE](LICENSE).
