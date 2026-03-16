# TokenCat Agent Notes

## Product Status

- Current release line: `v0.1.1` is the latest tagged release.
- Next planned development line: `v0.2.0`.
- Project goal: a local-first, read-only CLI for aggregating AI coding agent usage on one machine.
- Supported in practice:
  - `Codex`: supported via local session JSONL and SQLite fallback.
  - `Gemini CLI`: supported via local chat/session files.
  - `GitHub Copilot CLI`: detection-only, not full usage accounting.

## Privacy / Pricing Behavior

- TokenCat is read-only with respect to provider data.
- It must not proxy requests, rewrite endpoints, or read/report raw prompt-response bodies.
- It must not read OAuth/session credentials for reporting.
- Pricing behavior in `v0.1.1`:
  - package builds refresh the bundled pricing catalog before packaging;
  - first pricing load attempts a silent bootstrap refresh into `~/.tokencat/pricing/`;
  - silent bootstrap failure falls back to the bundled catalog without surfacing an error.

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
- Generated files that may legitimately change during release work include the bundled pricing catalog at `src/tokencat/pricing/catalog.json`.
