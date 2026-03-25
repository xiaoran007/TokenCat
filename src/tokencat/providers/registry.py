from __future__ import annotations

from tokencat.core.filters import apply_filters
from tokencat.core.models import ProviderName, ScanFilters, ScanResult
from tokencat.providers.base import ProviderAdapter
from tokencat.providers.claude import ClaudeAdapter
from tokencat.providers.codex import CodexAdapter
from tokencat.providers.copilot import CopilotAdapter
from tokencat.providers.gemini import GeminiAdapter


def build_providers() -> list[ProviderAdapter]:
    return [
        CodexAdapter(),
        ClaudeAdapter(),
        GeminiAdapter(),
        CopilotAdapter(),
    ]


def scan_providers(filters: ScanFilters) -> ScanResult:
    statuses = []
    sessions = []
    warnings = []
    selected = filters.providers or {ProviderName.CODEX, ProviderName.CLAUDE, ProviderName.GEMINI, ProviderName.COPILOT}

    for adapter in build_providers():
        status = adapter.detect()
        if status.provider not in selected:
            continue
        statuses.append(status)
        warnings.extend(status.warnings)
        sessions.extend(adapter.scan(filters))

    filtered_sessions = apply_filters(sessions, filters)
    return ScanResult(statuses=statuses, sessions=filtered_sessions, warnings=warnings)
