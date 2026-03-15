# TokenCat

TokenCat is a local-first, read-only CLI for inspecting AI coding agent usage on your own machine.

v0.1 focuses on:

- Codex local telemetry and archived session logs
- Gemini CLI local session files
- GitHub Copilot CLI detection and explicit unsupported diagnostics when no safe CLI telemetry source is available

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
tokencat doctor
tokencat summary --since 7d
tokencat sessions --provider codex --limit 20
tokencat sessions --provider codex --show-title --show-path
tokencat models --provider gemini --json
```

All read commands support:

- `--provider codex|gemini|copilot`
- `--since` and `--until` using `7d`, `24h`, or ISO date/datetime
- `--json`

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

## Privacy Defaults

- Default output is redacted: no session title, no cwd, no source file path.
- Raw prompt/response bodies are never emitted.
- OAuth/session tokens and auth files are never read for reporting.
- Stable anonymous session IDs are derived from provider + raw session ID using `sha256`.

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

## macOS-first Scope

v0.1 is implemented for macOS path layouts first. Linux path hooks are intentionally left easy to extend, but Linux and Windows are not yet guaranteed support targets in this release.
