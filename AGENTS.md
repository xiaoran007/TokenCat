# TokenCat Agent Notes
## Privacy / Pricing Behavior

- TokenCat is read-only with respect to provider data.
- It must not proxy requests, rewrite endpoints, or read/report raw prompt-response bodies.
- It must not read OAuth/session credentials for reporting.

## Release / Versioning Workflow

- Keep user-facing docs in `README.md`.
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
- Run and check Unit Tests when any change made. Make sure test cases are passed. 
