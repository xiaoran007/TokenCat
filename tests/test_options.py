from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import tokencat.cli as shared_cli
from tokencat.core.models import DashboardUsageGranularity, ProviderName, ScanFilters
from tokencat import dashboard


def test_cli_uses_shared_date_parsing_and_inclusive_end(source_home, monkeypatch):
    filters = shared_cli.build_filters([ProviderName.CLAUDE], "2026-10-02", "2026-10-02", None, None, False, False)
    queries = []
    original = dashboard.Engine.query
    def query(engine, value):
        queries.append(dict(value))
        return original(engine, value)
    monkeypatch.setattr(dashboard.Engine, "query", query)
    data = dashboard.load_dashboard(filters, DashboardUsageGranularity.WEEKLY, pricing_enabled=True)
    assert [value["granularity"] for value in queries] == ["day", "week"]
    assert queries[0]["providers"] == ["claude"]
    assert queries[0]["until_ms"] - queries[0]["since_ms"] == 86_400_000
    assert data.overview["token_totals"]["total"] == 1050


@pytest.mark.parametrize("days,granularity", [(7, "daily"), (30, "weekly"), (90, "monthly")])
def test_granularity_uses_existing_cli_logic(monkeypatch, days, granularity):
    monkeypatch.setattr(shared_cli, "local_now", lambda: datetime(2026, 10, 3, tzinfo=ZoneInfo("UTC")))
    from datetime import timedelta
    filters = ScanFilters(since=shared_cli.local_now() - timedelta(days=days))
    selected = shared_cli._resolve_dashboard_usage_granularity(filters, daily_view=False, weekly_view=False, monthly_view=False)
    assert selected.value == granularity


def test_source_configuration_uses_existing_comma_separated_claude_roots(source_home, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", f"{source_home / 'one'}, {source_home / 'two'}")
    config = dashboard.configuration()
    assert config["claude_roots"] == [str(source_home / "one"), str(source_home / "two")]
    assert config["database_path"] == str(source_home / ".tokencat/usage.sqlite3")


def test_native_price_ranges_and_unknowns_are_preserved_in_shared_cost_type():
    cost = {"input_usd": 0.1, "cache_read_usd": 0.05, "output_usd": 0.2,
            "cache_write_min_usd": 0.0,
            "min_usd": 0.35, "max_usd": 0.45, "unpriced_events": 0, "priced_tokens": 100}
    estimate = dashboard._cost(cost, True)
    assert estimate.to_dict()["max_cost"] == 0.45
    assert estimate.display_cost == "$0.35–$0.45"
    assert dashboard._cost({**cost, "unpriced_events": 1}, True).display_cost == "Known $0.35–$0.45"
    assert dashboard._cost({**cost, "unpriced_events": 1, "priced_tokens": 0}, True).display_cost == "No price record"
    assert dashboard._cost(cost, False).to_dict()["total_cost"] == 0
