from __future__ import annotations

from tokencat.core.filters import apply_filters
from tokencat.core.models import ProviderName, ScanFilters, ScanResult
from tokencat.providers.antigravity import AntigravityAdapter
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
        AntigravityAdapter(),
        CopilotAdapter(),
    ]


def build_provider_map() -> dict[ProviderName, ProviderAdapter]:
    return {
        ProviderName.CODEX: CodexAdapter(),
        ProviderName.CLAUDE: ClaudeAdapter(),
        ProviderName.GEMINI: GeminiAdapter(),
        ProviderName.ANTIGRAVITY: AntigravityAdapter(),
        ProviderName.COPILOT: CopilotAdapter(),
    }


def scan_providers(filters: ScanFilters) -> ScanResult:
    statuses = []
    sessions = []
    warnings = []
    selected = filters.providers or {ProviderName.CODEX, ProviderName.CLAUDE, ProviderName.GEMINI, ProviderName.ANTIGRAVITY, ProviderName.COPILOT}

    providers = build_provider_map()
    for provider in (ProviderName.CODEX, ProviderName.CLAUDE, ProviderName.GEMINI, ProviderName.ANTIGRAVITY, ProviderName.COPILOT):
        if provider not in selected:
            continue
        adapter = providers[provider]
        status = adapter.detect()
        statuses.append(status)
        warnings.extend(status.warnings)
        sessions.extend(adapter.scan(filters))

    filtered_sessions = apply_filters(sessions, filters)
    return ScanResult(statuses=statuses, sessions=filtered_sessions, warnings=warnings)
