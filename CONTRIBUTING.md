# Contributing to TokenCat

Help is welcome with source compatibility, usage accounting, interface clarity, and documentation. You can contribute without sharing your conversations or knowing every part of the codebase.

## Start with a problem

- [Report a bug](https://github.com/xiaoran007/TokenCat/issues/new?template=bug_report.md): include the interface and version, coding-tool version, time window, time zone, and expected versus actual behavior.
- [Share a usage experience](https://github.com/xiaoran007/TokenCat/issues/new?template=usage_feedback.md): tell us what you wanted to learn, whether TokenCat helped, and where you got stuck.
- [Suggest an improvement](https://github.com/xiaoran007/TokenCat/issues/new?template=feature_request.md): describe the workflow and the result you need.

Search [existing issues](https://github.com/xiaoran007/TokenCat/issues) first. For a larger feature or a change to accounting behavior, open an issue to agree on scope before implementing it. For a small fix, a focused PR is enough. English and Simplified Chinese are welcome.

## Protect source data

Do not attach full provider logs, conversation databases, TokenCat ledgers, credentials, or prompt/response bodies. JSON exports hide session IDs and project paths by default, but diagnostic warnings can include file paths; review exports and screenshots before sharing.

For parser bugs, describe the relevant usage fields or create a minimal synthetic sample with invented identifiers, paths, timestamps, and counters. Keep credentials and conversation text out of fixtures. TokenCat must keep provider sources read-only and must not proxy requests, rewrite endpoints, or read OAuth/session credentials for reporting.

## Set up a checkout

For CLI development on macOS or Linux, install Python 3.9+, Rust, and a C compiler. Then run these commands yourself:

```bash
git clone https://github.com/xiaoran007/TokenCat.git
cd TokenCat
git switch -c dev/my-change
make venv
.venv/bin/tokencat --help
```

`make venv` creates `.venv` and installs the editable native extension and development dependencies. Use `.venv/bin/python` and `.venv/bin/pytest` for subsequent Python commands. After changing Rust code used by the CLI, run `make install-dev` to rebuild that extension before testing it.

The app runs on macOS 14+; building it requires Xcode's Swift toolchain with the macOS 26 SDK or newer. See [development](docs/development.md) for app builds, benchmarks, and release procedures.

## Find the relevant code and checks

| Change | Start here | Verification |
| --- | --- | --- |
| CLI arguments, rendering, or JSON | `src/tokencat/`, `tests/` | `.venv/bin/pytest -q` |
| Source parsing, accounting, or pricing | `native/tokencat-core/`, its `tests/` | Rust tests, rebuild the CLI extension, then Python tests |
| Python native adapter | `bindings/python/`, `tests/test_native.py` | Binding tests, rebuild the extension, then Python tests |
| macOS presentation or settings | `macos/Sources/`, `macos/Tests/` | macOS test script |
| Installation or explanations | `README.md`, `docs/` | Check the described behavior and links, then Python tests |

Run the Python unit suite for every change:

```bash
.venv/bin/pytest -q
```

For core changes on macOS or Linux:

```bash
cargo test --locked --manifest-path native/Cargo.toml
```

For binding changes:

```bash
PYO3_PYTHON="$PWD/.venv/bin/python" cargo test --locked --manifest-path bindings/python/Cargo.toml
```

For macOS changes:

```bash
bash macos/scripts/test.sh
```

The macOS script tests Rust, links Swift to the tested archive, and runs Swift tests. Python tests use synthetic temporary sources; personal usage logs are unnecessary. If you cannot run a relevant check on your platform, say so in the PR.

## Keep a PR reviewable

Explain the problem, resulting behavior, and checks you ran. Keep changes focused and commits small; separate code, tests, and documentation when useful. Do not amend commits or revert unrelated changes. Add a synthetic regression for parsing or accounting fixes; documentation-only changes do not need a new test.

User installation, usage, supported features, and troubleshooting belong in README. Design decisions and maintenance notes belong in `docs/`. Costs remain API-equivalent estimates: missing prices stay unknown, and incomplete local records must remain visible.

CLI releases use the manually dispatched **CLI release** GitHub Actions workflow. Do not publish packages locally or add automatic release triggers. See [release instructions](docs/development.md#cli-releases-through-github-actions).
