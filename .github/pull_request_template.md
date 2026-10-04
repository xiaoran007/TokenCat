## Problem and result

Describe the concrete problem and what users will see after this change. Link a related issue if there is one.

## Verification

List the commands you ran and their results. Include the Python unit suite for every change, plus the relevant Rust/binding/macOS checks. Explain any checks you could not run.

## Checklist

- [ ] Changes and commits are focused; unrelated work is preserved.
- [ ] Parsing/accounting fixes have a minimal synthetic regression, where applicable.
- [ ] Fixtures, output examples, and screenshots contain no credentials or private conversation data.
- [ ] Provider sources remain read-only; reporting does not read OAuth/session credentials or expose conversation bodies.
- [ ] User-facing changes are explained in README where needed; design/maintenance notes stay in `docs/`.
