# TokenCat Agent Notes

## Product Status

- Current tagged release: `v0.4.0`.
- Current working branch is typically `main` unless the user explicitly asks for a feature branch.
- Project goal: a local-first, read-only CLI for aggregating AI coding agent usage on one machine.
- Supported in practice:
  - `Codex`: supported via local session JSONL and SQLite fallback.
  - `Claude Code`: supported via `CLAUDE_CONFIG_DIR` roots or local Claude project JSONL under `$XDG_CONFIG_HOME/claude` / `~/.config/claude` and legacy `~/.claude`.
  - `Gemini CLI`: supported via local chat/session files.
  - `GitHub Copilot`: supported via VS Code `workspaceStorage/*/chatSessions/*.json|*.jsonl`.
  - `GitHub Copilot CLI`: supported via `~/.copilot/session-state/*/events.jsonl` shutdown summaries.
  - Active Copilot CLI sessions without a `session.shutdown` summary still show as `partial` in `doctor`.
  - Claude Code support is read-only and based on local session telemetry only; it keeps exact observed model names so redirected/custom backends are shown conservatively instead of guessed.

## Privacy / Pricing Behavior

- TokenCat is read-only with respect to provider data.
- It must not proxy requests, rewrite endpoints, or read/report raw prompt-response bodies.
- It must not read OAuth/session credentials for reporting.
- Pricing behavior in `v0.4.0`:
  - package builds refresh the bundled pricing catalog before packaging;
  - first pricing load attempts a silent bootstrap refresh into `~/.tokencat/pricing/`;
  - silent bootstrap failure falls back to the bundled catalog without surfacing an error.
  - pricing resolution order is:
    1. direct source price when that source has explicit pricing;
    2. official API pricing for the model family;
    3. OpenRouter pricing as the marketplace fallback;
    4. otherwise `unknown_model`.
  - pricing catalog entries are keyed by pricing source, not scan provider;
  - session/model JSON can include `pricing_source` in addition to `pricing_model`.
  - Claude Code pricing keeps the observed model string, but pricing normalization can still resolve namespaced forms such as `anthropic/claude-*` and redirected families such as `openai/gpt-*` or `google/gemini-*` when they map cleanly to existing catalog families.
  - time-windowed `sessions`, `summary`, `models`, and `daily` views now use event/message/request timestamps when local telemetry supports it, instead of assigning whole sessions to `updated_at`.
  - terminal dashboard usage buckets can adapt between daily, weekly, and monthly views based on the selected time window, with explicit `--daily`, `--weekly`, and `--monthly` overrides.
  - terminal dashboard hides zero-token model rows so metadata-only Copilot VS Code sessions do not show misleading `0` token lines by default.
  - Claude Code session parsing is conservative: only assistant messages with usage are billable, streaming snapshots are deduplicated by message id, and prompt/response bodies remain out of TokenCat output.

## Release / Versioning Workflow

- Keep user-facing docs in `README.md`.
- Keep agent/process/project memory in this `AGENTS.md`.
- Version bumps happen in both:
  - `pyproject.toml`
  - `src/tokencat/__init__.py`
- Tag after the explicit version bump commit.
- Current tag convention: `vX.Y.Z`.

## Git Hygiene

- Split commits by concern whenever practical:
  - `feat`
  - `test`
  - `docs`
  - `build`
  - `chore`
- Do not amend commits unless the user explicitly asks.
- Do not revert unrelated user changes.
- Keep release-related commits small and easy to audit.

## Local Workflow Preferences

- The user prefers to run `build`, `make`, and publish commands manually to avoid local path, network, or permission issues.
- Use the repository virtualenv for Python commands in this repo:
  - prefer `.venv/bin/python`
  - prefer `.venv/bin/pytest`
  - avoid falling back to system `python`, `python3`, or global `pytest` unless the user explicitly asks
- If a future thread needs to inspect pricing/test behavior, assume the local `.venv` is the correct interpreter first.
- Generated files that may legitimately change during release work include the bundled pricing catalog at `src/tokencat/pricing/catalog.json`.
