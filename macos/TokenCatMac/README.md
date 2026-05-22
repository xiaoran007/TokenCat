# TokenCat macOS Development Extension

This directory contains the development-only macOS companion targets for
TokenCat:

- `TokenCatMac`: SwiftUI menu bar app.
- `TokenCatWidgetExtension`: WidgetKit desktop widget.
- `TokenCatMacTests`: Swift unit tests for snapshot decoding, storage, bridge,
  and menu bar state.

TokenCat's Python CLI remains the source of truth. During development, the app
calls:

```sh
.venv/bin/python -m tokencat snapshot --since 7d
```

The menu bar app writes the resulting `snapshot.json` to the configured App
Group container. The widget only reads that cached snapshot.

## Local Build

Install full Xcode and select it:

```sh
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
```

If command-line signing needs an explicit team, provide your Personal Team ID:

```sh
TOKENCAT_DEVELOPMENT_TEAM=YOURTEAMID make macos-build
```

Convenience commands:

```sh
make macos-build
make macos-test
make macos-run
```

`make macos-run` uses `script/build_and_run.sh`, which sets `TOKENCAT_ROOT` and
`TOKENCAT_PYTHON` for the launched app via `launchctl setenv`.
