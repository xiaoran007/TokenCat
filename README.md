# TokenCat

<img src="macos/Branding/TokenCatAppIcon.png" width="96" height="96" alt="TokenCat cat icon">

[![PyPI](https://img.shields.io/pypi/v/tokencat?style=flat-square)](https://pypi.org/project/tokencat/)
[![License](https://img.shields.io/badge/license-GPLv3-blue?style=flat-square)](LICENSE)

**See token usage and estimated costs across your coding agents and subagents.** TokenCat reads local usage records from **Codex, Claude Code, OpenCode, and Antigravity**. Use the macOS app to follow usage as records arrive and explore task families, or the CLI to review a period and export JSON.

- **Follow a task and its subagents.** In the app, expand recorded parent-child relationships and distinguish a task's own estimated cost from the cost of its whole family.
- **Understand the numbers.** Explore usage by tool, model, project, and task; inspect cache usage, pricing coverage, unknown prices, and uncertain estimates.
- **Keep collection local and read-only.** No provider credentials are needed for reporting. Session IDs are anonymized and project paths stay hidden by default.

Costs are **API-equivalent estimates, not your bill or remaining subscription quota**. App updates follow locally recorded usage; data can appear only after your coding tool writes it.

[macOS app](#macos-app) · [Terminal CLI](#terminal-cli) · [Prices and privacy](#prices-and-privacy) · [Feedback and contributing](#feedback-and-contributing)

![TokenCat macOS dashboard](https://img.xiaoran007.cc/9257c6e9-1241-4482-8ff9-f6eb16641f87.png)

## Choose an interface

Both interfaces support **Codex, Claude Code, OpenCode, and Antigravity**. The app requires macOS 14 or newer. The CLI supports macOS and Linux with Python 3.9 or newer; Windows is not supported.

| Interface | Use it for | Availability |
| --- | --- | --- |
| macOS app | Background monitoring, task trees, and interactive breakdowns | Build from source |
| Terminal CLI | Period reviews, provider filters, calendar grouping, and JSON exports | PyPI release or source checkout; see the version note below |

**Version note:** this README describes the **0.9.0 source version**. As of October 4, 2026, the latest PyPI release is **0.8.0**; `pipx install tokencat` installs that release. Use [the 0.8.0 documentation on PyPI](https://pypi.org/project/tokencat/0.8.0/) for its commands, or install this checkout for the behavior below.

The 0.9.0 CLI provides local dashboards and JSON export. Remote aggregation, the older report/server commands, Gemini CLI, and GitHub Copilot are unavailable in this version.

The app and CLI keep separate settings and usage histories; they do not automatically synchronize. To compare results, use the same source roots, time window, time zone, and pricing catalog. Previously collected history can still differ.

## macOS app

### Install from source

You need Rust and Xcode's Swift toolchain with the macOS 26 SDK or newer. The app runs independently of Python and pipx.

Clone this repository, then build and launch:

```bash
git clone https://github.com/xiaoran007/TokenCat.git
cd TokenCat
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

For a task with recorded subagents, expand its row in **Tasks** and open the parent. **Direct task cost** shows that task's own usage; **Task and subagents** includes its descendants. Open a child to inspect its contribution. Relationships and usage depend on what the source records expose.

Open Settings with the settings button or **Command–comma**. Choose language, appearance, time zone, refresh interval, and source folders. English and Simplified Chinese are included. By default, the app waits two seconds after each refresh before scanning again and refreshes when the Mac wakes. This is near-real-time monitoring of local records, not token-by-token streaming from the provider.

Standard source locations are detected automatically:

| Tool | Default locations |
| --- | --- |
| Codex | `~/.codex/sessions` and `~/.codex/archived_sessions` |
| Claude Code | `~/.claude/projects` and `~/.config/claude/projects` |
| OpenCode | `~/.local/share/opencode/opencode.db`, honoring `XDG_DATA_HOME` |
| Antigravity | `conversations` under `~/.gemini/antigravity` and `~/.gemini/antigravity-cli` |

If your tools store data elsewhere, set their roots in Settings. Project paths stay hidden unless you enable them.

**First run:** use a supported coding tool under the same user account, then choose a TokenCat period containing that activity. You should see recorded tokens for that tool. Missing prices do not mean missing usage; check pricing coverage. If the panel is empty, check source roots in Settings and [troubleshooting](#troubleshooting).

## Terminal CLI

### Install or upgrade

For the published **0.8.0** release, follow [its documentation](https://pypi.org/project/tokencat/0.8.0/):

```bash
pipx install tokencat
# Update an existing installation:
pipx upgrade tokencat
```

For the **0.9.0 source version** described below, you need Python 3.9+, pipx, Rust, and a C compiler:

```bash
git clone https://github.com/xiaoran007/TokenCat.git
cd TokenCat
pipx install .
```

If TokenCat is already installed with pipx, use `pipx install --force .` from this checkout instead.

If you previously installed the candidate alongside TokenCat, remove that extra with `pipx uninject tokencat tokencat-native`. Use `tokencat` for the current CLI. Its first run copies saved candidate usage into the CLI data directory and keeps the original candidate ledger. An existing CLI ledger takes precedence.

### Use the dashboard

After installing the source version, run `tokencat --since 7d`. You should see recorded tokens, model totals, and pricing coverage for supported tools with local activity in that period. No provider login is needed for TokenCat. If the view is empty, check warnings, confirm you used a supported tool under this user account, and try `--since 30d`.

The CLI scans once per invocation. Use the app for automatic background refreshes.

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

## Feedback and contributing

- **Missing usage, unexpected totals, or installation trouble?** [Report a bug](https://github.com/xiaoran007/TokenCat/issues/new?template=bug_report.md) with your version, coding tool, time window, and time zone.
- **Did TokenCat help with a real task?** [Share your experience](https://github.com/xiaoran007/TokenCat/issues/new?template=usage_feedback.md), including what was useful and where you got stuck.
- **Have a workflow in mind?** [Suggest an improvement](https://github.com/xiaoran007/TokenCat/issues/new?template=feature_request.md) with a concrete example.
- **Want to contribute?** Start with [the contributor guide](CONTRIBUTING.md) for setup, code locations, and checks. Compatibility fixes, synthetic usage samples, interface improvements, and documentation are welcome.

English and Simplified Chinese are welcome. Review exports and screenshots for private file paths before sharing. Do not attach full logs, databases, credentials, or conversation bodies.

If TokenCat is useful to you, a GitHub star helps others discover it and lets you bookmark the project.
