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

The root package is `tokencat` 0.9.0 and uses maturin. Its Python frontend and adapter are in `src/tokencat`; the PyO3 extension is in `bindings/python`, with a separate Cargo workspace. Rust and a C compiler are needed for local source installation. Development tooling is an optional extra:

```bash
make install-dev
.venv/bin/tokencat --help
.venv/bin/pytest -q tests
PYO3_PYTHON="$PWD/.venv/bin/python" cargo test --locked --manifest-path bindings/python/Cargo.toml
```

`make install-dev` compiles and installs the editable native extension. Tests use the real extension against synthetic temporary sources, cover all four harnesses, ledger reopen/append, candidate-ledger migration with WAL, JSON privacy, calendar grouping, and the original layout at three terminal widths and both themes. Removed Python collectors and remote modules must not be importable. A local extension from an earlier checkout can exercise the frontend, but it does not validate later Rust analyzer changes; rebuild it before checking current end-to-end accounting.

Local development artifacts can be built manually with `make build`; wheels and the source distribution go to `dist/`. The package includes its Python frontend, native extension, and Rust price resources. Wheels use the CPython 3.9 stable ABI with platform and architecture tags; free-threaded Python is outside the wheel matrix. Cleanup preserves `build/TokenCat.app` and native compiler caches. CLI publishing runs exclusively through Actions, with no local publish targets.

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

## CLI releases through GitHub Actions

The **CLI release** workflow (`.github/workflows/cli-wheels.yml`) has only a `workflow_dispatch` trigger. Pushing commits, tags, or creating a GitHub Release does not start it. One manual run builds the selected commit, tests its artifacts, and optionally publishes them. Version changes remain explicit repository changes; Actions validates them and does not bump versions. A successful production PyPI publish also creates a GitHub Release and its `vX.Y.Z` tag at the tested commit.

1. Set the same `X.Y.Z` version in `pyproject.toml`, `src/tokencat/__init__.py`, and `bindings/python/Cargo.toml`. Refresh the matching Cargo.lock with `cargo metadata --manifest-path bindings/python/Cargo.toml --format-version 1`, then commit and push the release code. Keep commits small; do not amend or revert unrelated work. Published 0.8.0 packages and old tags are preserved.
2. In GitHub **Actions → CLI release → Run workflow**, choose the release branch and `publish_to`:

   | Value | Result after all checks pass |
   | --- | --- |
   | `none` (default) | Save tested artifacts without publishing |
   | `testpypi` | Publish those tested artifacts to TestPyPI |
   | `pypi` | Publish those tested artifacts to PyPI, then create a GitHub Release |

3. The run validates all four version declarations. For `pypi`, it also checks that any existing `vX.Y.Z` tag points to the selected commit; a mismatch stops the run before publishing. It builds macOS and manylinux2014 wheels for ARM64 and x86_64, and tests installed wheels on Python 3.14 across all four platforms and Python 3.9 on x86_64. It also tests source-archive installation and the Rust core. Package tests import the installed distribution rather than the source-tree frontend.
4. After tests succeed, the workflow checks that the artifact set contains exactly four CPython 3.9 ABI3 platform wheels and one source archive, all named and versioned as `tokencat`, then runs strict Twine metadata checks. The `release-distributions` artifact is the exact set handed to the publish job. Publishing downloads it from the same run and never rebuilds. A failed check prevents publication.
5. Only after the `pypi` publish job succeeds, the GitHub Release job downloads the same `release-distributions` artifact and checks the tag again. It creates `TokenCat CLI vX.Y.Z` with automatically generated release notes and attaches the four wheels and source archive. A missing tag is created at the tested commit; an existing matching tag is reused. `none`, `testpypi`, and failed publishes do not create a Release.

If GitHub Release creation fails after PyPI succeeds, the package is already published. Use **Re-run failed jobs** on that run to retry the Release job without repeating the successful PyPI upload. Existing tags and Releases are not overwritten; resolve a conflict before retrying.

`ci/release.py` validates source versions and distribution contents, with unit tests in `tests/test_release.py`. Release jobs use Python 3.14; artifact-content tests also run on Python 3.9. `actionlint` checks workflow syntax and expressions (`.venv/bin/actionlint .github/workflows/cli-wheels.yml` when installed). Cross-platform builds and actual upload remain unverified until their Actions jobs succeed.

### One-time Trusted Publishing setup

The publish job uses the pinned PyPA publishing action with OIDC. It requires no stored PyPI API token. Create the GitHub repository environments `pypi` and `testpypi`. On the corresponding package index, add a GitHub Trusted Publisher for `tokencat` with:

| Field | Value |
| --- | --- |
| Owner | `xiaoran007` |
| Repository | `TokenCat` |
| Workflow filename | `cli-wheels.yml` |
| Environment | `pypi` for PyPI; `testpypi` for TestPyPI |

See [PyPI's publisher setup](https://docs.pypi.org/trusted-publishers/adding-a-publisher/) and [token-free publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/). PyPI and TestPyPI publisher registrations are separate. A project not yet created on TestPyPI can use a [pending publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/). The workflow must exist on the repository's default branch for the manual Run workflow interface to be available, then a run can select another release branch.

Only the publish job receives `id-token: write`; only the GitHub Release job receives `contents: write`, using the built-in `GITHUB_TOKEN` without a personal access token. Build and test jobs have read-only repository access. The workflow does not configure external publisher settings itself. Register them before choosing a publishing destination. Run `none` to validate artifacts without publisher configuration. There are no local upload commands or separate `tokencat-native` release.

Production releases create tags of the form `vX.Y.Z` automatically, pointing to the exact tested commit. Tags do not trigger another run. Users update with `pipx upgrade tokencat` after the PyPI publish job succeeds.
