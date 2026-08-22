from __future__ import annotations

from datetime import datetime, timezone

from tokencat.core.filters import apply_filters
from tokencat.core.models import ProviderName, ScanFilters, SessionRecord, TokenTotals


def _session(session_id: str, timestamp: datetime | None) -> SessionRecord:
    return SessionRecord(
        provider=ProviderName.ANTIGRAVITY,
        provider_session_id=session_id,
        anon_session_id=session_id,
        started_at=timestamp,
        updated_at=timestamp,
        token_totals=TokenTotals.zero(),
    )


def test_apply_filters_sorts_records_with_missing_timestamps_last() -> None:
    dated = _session("dated", datetime(2026, 8, 22, tzinfo=timezone.utc))
    undated = _session("undated", None)

    records = apply_filters([undated, dated], ScanFilters())

    assert [record.provider_session_id for record in records] == ["dated", "undated"]
