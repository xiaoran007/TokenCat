from __future__ import annotations

import shutil
from pathlib import Path

from tokencat.core.models import ProviderName, ProviderStatus, ProviderSupportLevel, ScanFilters, SessionRecord
from tokencat.providers.base import ProviderAdapter


class CopilotAdapter(ProviderAdapter):
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or Path.home()
        self.config_dir = self.home / ".config"
        self.library_dir = self.home / "Library" / "Application Support"

    def detect(self) -> ProviderStatus:
        found_paths: list[Path] = []
        ignored_paths: list[Path] = []
        reasons: list[str] = []

        binary = shutil.which("github-copilot") or shutil.which("copilot")
        if binary:
            found_paths.append(Path(binary))

        for path in self._candidate_cli_paths():
            if path.exists():
                found_paths.append(path)

        for path in self._plugin_paths():
            if path.exists():
                ignored_paths.append(path)

        if found_paths:
            reasons.append("Potential Copilot CLI artifacts were detected, but v0.1 does not parse them yet.")
            return ProviderStatus(
                provider=ProviderName.COPILOT,
                status=ProviderSupportLevel.PARTIAL,
                found_paths=found_paths,
                ignored_paths=ignored_paths,
                reasons=reasons,
                warnings=["Copilot CLI usage stats are not surfaced in v0.1."],
            )

        if ignored_paths:
            return ProviderStatus(
                provider=ProviderName.COPILOT,
                status=ProviderSupportLevel.UNSUPPORTED,
                ignored_paths=ignored_paths,
                reasons=["Only IDE/plugin state was found. No safe Copilot CLI telemetry source was identified."],
            )

        return ProviderStatus(
            provider=ProviderName.COPILOT,
            status=ProviderSupportLevel.NOT_FOUND,
            reasons=["No Copilot CLI local data source was found."],
        )

    def scan(self, filters: ScanFilters) -> list[SessionRecord]:
        return []

    def _candidate_cli_paths(self) -> list[Path]:
        return [
            self.config_dir / "github-copilot-cli",
            self.config_dir / "copilot-cli",
            self.home / ".local" / "share" / "github-copilot-cli",
            self.library_dir / "GitHub Copilot CLI",
        ]

    def _plugin_paths(self) -> list[Path]:
        return [
            self.config_dir / "github-copilot",
            self.library_dir / "GitHub Copilot",
        ]
