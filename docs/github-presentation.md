# GitHub presentation

This document keeps repository metadata, share artwork, and profile copy together. User installation and usage remain in [README](../README.md); contributor setup is in [CONTRIBUTING](../CONTRIBUTING.md).

## Repository metadata

**Description**

```text
Local token and cost analytics for coding agents and subagents. macOS app + CLI; no provider credentials required.
```

**Topics**

```text
agents, ai-agents, claude-code, codex, opencode, antigravity, token-usage, cost-tracking, developer-tools, macos, python
```

Topics describe supported tools and usage analysis. The existing `agents`, `claude-code`, `codex`, and `python` topics are retained. Repository metadata can be changed through the About gear on the [repository homepage](https://github.com/xiaoran007/TokenCat) or the GitHub CLI.

## Upload the social preview

The ready-to-upload [PNG](assets/github-social-preview.png) is 1280 × 640 pixels and under 1 MB. Its task tree illustrates the concept; it is not an application screenshot or measured usage. The artwork uses the existing TokenCat vector mark.

1. Open [repository Settings](https://github.com/xiaoran007/TokenCat/settings).
2. Under **Social preview**, choose **Edit → Upload an image…**.
3. Select `docs/assets/github-social-preview.png` from this checkout.
4. Confirm the crop keeps the entire card visible, then save.

GitHub supports PNG, JPG, and GIF files under 1 MB and recommends 1280 × 640 for best display. See [social preview documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview).

The editable layout is [render-social-preview.swift](branding/render-social-preview.swift). Regenerate it on macOS:

```bash
swift -module-cache-path /tmp/tokencat-social-preview-swift-cache docs/branding/render-social-preview.swift
```

This only renders the card; it does not build or launch TokenCat.

## Put TokenCat first on the personal profile

TokenCat is already pinned on the maintainer's profile. Move its existing card to the first position rather than replacing the other pinned projects:

1. Open [the profile](https://github.com/xiaoran007).
2. In **Pinned**, use the card's drag handle to move **TokenCat** to the first position. If editing the selection, use **Customize your pins** and keep the existing projects selected.
3. Save the order if prompted.

See [GitHub's pinning instructions](https://docs.github.com/en/account-and-profile/how-tos/profile-customization/pinning-items-to-your-profile).

Under **Edit profile**, the following Bio preserves the existing university affiliation:

```text
Brown University · Building TokenCat, a local-first AI coding usage analyzer.
```

Use this for the profile's website URL:

```text
https://github.com/xiaoran007/TokenCat
```

## Add a project section to the profile README

Open [the profile README editor](https://github.com/xiaoran007/xiaoran007/edit/main/README.md). Insert this section after **About Me** and before **My Skills**, preserving the rest of the profile:

```markdown
### Featured project: TokenCat

[TokenCat](https://github.com/xiaoran007/TokenCat) helps you see where your AI coding tokens go, with local usage analysis and API-equivalent cost estimates for Codex, Claude Code, OpenCode, and Antigravity.

- Follow recorded usage in the native macOS app and explore tasks with their subagents.
- Review periods in the terminal CLI and export JSON for your own analysis.
- Keep provider records read-only, with no provider credentials needed for reporting.

[Screenshots and installation](https://github.com/xiaoran007/TokenCat#choose-an-interface) · [Share feedback](https://github.com/xiaoran007/TokenCat/issues/new/choose)
```

Commit the profile change through the web editor. This is a separate repository from TokenCat.

## Check the result

After merging the presentation PR, verify the README's screenshot and source/release installation choices, the [issue chooser](https://github.com/xiaoran007/TokenCat/issues/new/choose), and the contributor guide. The repository provides bug, feature, and usage-feedback templates; opening the chooser does not require submitting an issue.

Check **Insights → Traffic** before sharing the repository and record traffic weekly. GitHub exposes visitors from the last 14 days, referring sites, and full clones; these are discovery signals, not active-user counts. See [traffic documentation](https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/viewing-traffic-to-a-repository).
