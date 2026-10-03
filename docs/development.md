# Development

User installation and usage belong in [README](../README.md). Collection boundaries and design decisions belong in [architecture](architecture.md).

## Local setup and checks

Use Python 3.9+ for the CLI. Create the repository virtualenv and install development dependencies with `make venv`; subsequent Python commands use `.venv/bin/python` or `.venv/bin/pytest`.

```bash
.venv/bin/pytest -q
bash macos/scripts/test.sh
```

The native test script runs release-mode Rust tests, links Swift to the exact tested Rust archive, and runs the Swift tests. Core-only checks on macOS or Linux:

```bash
cargo test --locked --manifest-path native/Cargo.toml
```

The macOS app requires macOS 14+, Rust, and Xcode's Swift toolchain with the macOS 26 SDK or newer. Build and launch manually:

```bash
bash macos/scripts/build-app.sh
open build/TokenCat.app
```

Quit a previously running app before launching a rebuilt copy. The build script uses release-mode Rust and Swift, bundles resources, and applies an ad-hoc signature. Publisher signing and notarization are separate distribution work.

Editable branding is in `macos/Branding`. Regenerate the SVG, PDF, PNG, and ICNS assets with `swift macos/scripts/generate-icons.swift` on macOS.

## Refresh benchmark

The [isolated runner](../experiments/antigravity-refresh/run.py) uses synthetic sources and temporary release workspaces. It does not overwrite the app, provider sources, or the app's ledger. macOS process resource measurement and a populated local Cargo dependency cache are required; builds run offline.

```bash
.venv/bin/python experiments/antigravity-refresh/run.py --output /tmp/tokencat-refresh-results
```

Original code and fixture helpers are pinned to `8f41381` (`--baseline-ref` overrides it); production uses the current checkout. The runner compares the original, BLOB-only, cached, bounded-cache, and production variants. All must produce identical event, session, and scan-report digests. The small profile contains 4 databases with 20 generations each and 4 KiB skipped fields; the large profile contains 8 databases with 80 generations each and 256 KiB skipped fields. “Cold” means the first collector scan, not an empty OS file cache.

Output includes `results.json`, generated source variants, test logs, process resource reports, and `workspace.txt`. `--workspace` reuses the recorded temporary compilation directory. With existing results, `--resume --variants production` measures production against the recorded baseline. Keep compilation separate from the final performance measurement. [Recorded production results](../experiments/antigravity-refresh/production-results.json) and their interpretation are in [architecture](architecture.md#refresh-cache-decision).

## Releases

Use tags of the form `vX.Y.Z`. Keep commits small and split implementation, tests, docs, and packaging where practical. Do not amend commits or revert unrelated changes without instruction. Run checks before release; packaging, build, and publish commands are run manually. `make install-release` installs the optional Python release tooling in the project virtualenv.
