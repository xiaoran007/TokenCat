# TokenCat

<img src="macos/Branding/TokenCatAppIcon.png" width="96" height="96" alt="TokenCat cat icon">

[![PyPI](https://img.shields.io/pypi/v/tokencat?style=flat-square)](https://pypi.org/project/tokencat/)
[![License](https://img.shields.io/badge/license-GPLv3-blue?style=flat-square)](LICENSE)

TokenCat shows how many tokens your AI coding tools use and estimates their API-equivalent cost from locally recorded usage. Use the macOS menu bar app for background monitoring or the terminal CLI for local dashboards and JSON exports.

- See usage by coding tool, model, project, and task.
- Inspect recent activity, cached tokens, and linked subagent usage.
- Keep usage collection local, with anonymous session IDs and hidden project paths by default.

## Choose an interface

Both interfaces support **Codex, Claude Code, OpenCode, and Antigravity**. The app requires macOS 14 or newer. The CLI supports macOS and Linux with Python 3.9 or newer; Windows is not supported.

CLI instructions below apply to 0.9.0 and newer. These versions provide local dashboards and JSON export. Remote aggregation, the older report/server commands, Gemini CLI, and GitHub Copilot are unavailable. If you still need those older CLI features, install `tokencat==0.8.0` in a separate environment.

## macOS app
![macOS app](https://img.xiaoran007.cc/9257c6e9-1241-4482-8ff9-f6eb16641f87.png)

### Install from source

You need Rust and Xcode's Swift toolchain with the macOS 26 SDK or newer. The app runs independently of Python and pipx.

From a checkout of this repository:

```bash
bash macos/scripts/build-app.sh
open build/TokenCat.app
```

The app is created at `build/TokenCat.app`. Move it to `/Applications` before enabling **Launch at Login** in Settings. To update, rebuild, quit the running copy, and open the new app.

### Use the app

Click the cat in the menu bar to see today's estimated cost and open the usage panel. Choose **Today**, **7 days**, or **30 days**, then open the dashboard for more detail.

In the dashboard you can:

- Search models, projects, and tasks; sort by cost, tokens, or recent activity.
- Switch the activity chart between recorded tokens and known API cost.
- Open a task to inspect its own usage and related subagents.

Open Settings with the settings button or **Command–comma**. Choose language, appearance, time zone, refresh interval, and source folders. English and Simplified Chinese are included. Usage refreshes every two seconds by default and resumes when the Mac wakes.

Standard source locations are detected automatically:

| Tool | Default locations |
| --- | --- |
| Codex | `~/.codex/sessions` and `~/.codex/archived_sessions` |
| Claude Code | `~/.claude/projects` and `~/.config/claude/projects` |
| OpenCode | `~/.local/share/opencode/opencode.db`, honoring `XDG_DATA_HOME` |
| Antigravity | `conversations` under `~/.gemini/antigravity` and `~/.gemini/antigravity-cli` |

If your tools store data elsewhere, set their roots in Settings. Project paths stay hidden unless you enable them.

## Terminal CLI

### Install or upgrade

```bash
pipx install tokencat
# Update an existing installation:
pipx upgrade tokencat
```

Compatible wheels include everything needed to run the CLI. Installing from a source archive or repository checkout also requires Rust and a C compiler:

```bash
pipx install .
```

If you previously installed the candidate alongside TokenCat, remove that extra with `pipx uninject tokencat tokencat-native`. Use `tokencat` for the current CLI. Its first run copies saved candidate usage into the CLI data directory and keeps the original candidate ledger. An existing CLI ledger takes precedence.

### Use the dashboard

```bash
tokencat                                      # Last seven days
tokencat dashboard                            # Also show recent sessions
tokencat --since 30d --weekly
tokencat --provider claude
tokencat --since 2026-10-01 --until 2026-10-03
tokencat --since 7d --json
TZ=America/New_York tokencat --since 7d
```

Use `--daily`, `--weekly`, or `--monthly` for calendar grouping, and `--theme auto|light|dark` for terminal colors. Repeat `--provider` to select several tools. Time windows use the system time zone; set `TZ` to choose another. `--until` includes the specified end time or the whole day for date-only values.

Standard source locations are detected automatically. Claude honors comma-separated roots in `CLAUDE_CONFIG_DIR` and `XDG_CONFIG_HOME`; OpenCode honors `XDG_DATA_HOME`. Run `tokencat --help` or `tokencat dashboard --help` for all options.

The CLI includes offline prices without automatic catalog downloads. Missing prices appear as unknown, and uncertain estimates appear as a range. Use `--no-price` to show usage without cost estimation. JSON exports anonymize session IDs and hide project paths; diagnostic warnings may include source file paths.

![TokenCat terminal dashboard](https://files.catbox.moe/wo8lwy.png)

## Prices and privacy

Costs are **API-equivalent estimates, not your bill or subscription balance**. Unknown model prices remain unpriced. Ambiguous recorded usage favors the higher defensible estimate; requests missing from local logs cannot be counted. Usage without a confirmed date may contribute to a window's totals while remaining outside the calendar timeline; warnings explain this difference. Estimates do not include every billing tier, tool fee, or regional adjustment.

Both interfaces include offline prices and show pricing coverage and sources. The app checks for price updates every 24 hours by default; Settings offers manual refresh, other intervals, an off switch, and a custom catalog. Different catalogs, source roots, and independently saved history can produce different totals between interfaces.

Usage collection reads local records. TokenCat does not proxy requests, change provider endpoints, or read OAuth/session credentials for reporting. Reports exclude prompt and response bodies. App price updates and CLI version checks access the network.

## Troubleshooting

**A tool is missing or shows no usage.** Make sure it has recorded local activity under the same user account. Check source roots in app Settings and warnings in the CLI output. For nonstandard CLI locations, `CLAUDE_CONFIG_DIR` accepts comma-separated Claude roots and `XDG_DATA_HOME` sets the OpenCode data location.

**Costs look different from an invoice.** TokenCat estimates standard API usage, including when a tool is used through a subscription. Check pricing coverage and unknown models before comparing totals. Updating the catalog can change estimates for earlier dates.

**A native extension cannot be loaded.** Reinstall TokenCat using a wheel matching your operating system and architecture. For a source installation, make sure Rust and a C compiler are available, then reinstall. TokenCat requires its native extension to collect usage.

**Where is TokenCat's data stored?** The app keeps usage and downloaded prices in `~/Library/Application Support/TokenCat/`. The CLI keeps usage in `~/.tokencat/usage.sqlite3`. Candidate history remains in `~/.tokencat-candidate/` after migration. Removing source logs does not erase already saved usage.

## Contributing

See [development and testing](docs/development.md) and [architecture and decisions](docs/architecture.md).
