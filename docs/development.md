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

## Native Python CLI

The root package is `tokencat` 0.9.0 and uses maturin. Its Python frontend and adapter are in `src/tokencat`; the PyO3 extension is in `bindings/python`, with a separate Cargo workspace. Rust and a C compiler are needed for local source installation. Development and release tooling are optional extras:

```bash
make install-dev
.venv/bin/tokencat --help
.venv/bin/pytest -q tests
PYO3_PYTHON="$PWD/.venv/bin/python" cargo test --locked --manifest-path bindings/python/Cargo.toml
```

`make install-dev` compiles and installs the editable native extension. Tests use the real extension against synthetic temporary sources, cover all four harnesses, ledger reopen/append, candidate-ledger migration with WAL, JSON privacy, calendar grouping, and the original layout at three terminal widths and both themes. Removed Python collectors and remote modules must not be importable. A local extension from an earlier checkout can exercise the frontend, but it does not validate later Rust analyzer changes; rebuild it before checking current end-to-end accounting.

Build manually with `make build`; wheels and the source distribution go to `dist/`. `make check-dist` builds and checks package metadata. The package includes its Python frontend, native extension, and Rust price resources without depending on the old package or candidate. Wheels use the CPython 3.9 stable ABI, with platform and architecture tags; free-threaded Python is outside the wheel matrix. Cleanup preserves `build/TokenCat.app` and native compiler caches.

The **CLI wheels** workflow (`.github/workflows/cli-wheels.yml`) is manually triggered. It builds macOS and manylinux2014 wheels for x86_64 and ARM64 and tests the installed distribution on Python 3.14 across all four platforms and Python 3.9 on the two x86_64 platforms. A source-distribution job installs the archived source into a separate virtualenv and runs the same suite, verifying that Rust dependencies and resources survive packaging. Tests must import the installed wheel/archive rather than a source-tree copy. Artifacts are retained for download; publishing remains manual. Cross-platform support is verified only after those workflow jobs succeed.

For 0.9.0, publish only the new `tokencat` artifacts; no separate `tokencat-native` release or coordinated frontend release is needed. Do not replace previously published 0.8.0 artifacts or retag old releases. The `publish` targets upload locally built artifacts for the current machine; to release all platforms, download the successful workflow's wheels plus its single source archive into a clean distribution directory, check those exact files with twine, then upload them manually.

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
