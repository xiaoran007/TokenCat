# TokenCat Agent Notes
## Privacy / Pricing Behavior

- TokenCat is read-only with respect to provider data.
- It must not proxy requests, rewrite endpoints, or read/report raw prompt-response bodies.
- It must not read OAuth/session credentials for reporting.

## Release / Versioning Workflow

- Keep user-facing docs in `README.md`.
- README must always be written for end users: explain what TokenCat does, installation, usage, supported features, and troubleshooting. Do not put implementation progress, migration plans, decision records, build/test reports, or internal API details in README. Keep necessary design and maintenance documentation under `docs/`.
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

- CLI releases build, test, and publish through the manually dispatched `CLI release` GitHub Actions workflow. Do not publish CLI packages from the local machine or add automatic workflow triggers.
- For local development, the user prefers to run `build` and `make` commands manually to avoid local path, network, or permission issues.
- Use the repository virtualenv for Python commands in this repo:
  - prefer `.venv/bin/python`
  - prefer `.venv/bin/pytest`
  - avoid falling back to system `python`, `python3`, or global `pytest` unless the user explicitly asks
- Run and check Unit Tests when any change made. Make sure test cases are passed. 
