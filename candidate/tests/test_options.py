from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tokencat_native.options import Harness, configuration, make_query, timezone_name
from tokencat_native.render import cost_text


def test_inclusive_date_end_keeps_entire_dst_day_and_datetime_end_is_exclusive():
    now = datetime(2026, 11, 3, tzinfo=ZoneInfo("America/New_York"))
    args = dict(since="2026-11-01", zone="America/New_York", providers=[Harness.CLAUDE],
                daily=True, weekly=False, monthly=False, now=now)
    query = make_query(until="2026-11-01", **args)
    assert query["until_ms"] - query["since_ms"] == 25 * 3_600_000
    assert query["providers"] == ["claude"]
    explicit = make_query(until="2026-11-02T05:00:00Z", **args)
    assert explicit["until_ms"] == query["until_ms"]


@pytest.mark.parametrize("since,granularity", [("7d", "day"), ("30d", "week"), ("90d", "month")])
def test_automatic_cli_granularity_uses_one_captured_window(since, granularity):
    query = make_query(since=since, until=None, zone="UTC", providers=[], daily=False, weekly=False,
                       monthly=False, now=datetime(2026, 10, 3, tzinfo=ZoneInfo("UTC")))
    assert query["granularity"] == granularity
    assert query["providers"] is None


def test_timezone_is_explicit_or_detected_from_configuration(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    assert timezone_name(None) == "America/New_York"
    assert timezone_name("UTC") == "UTC"
    monkeypatch.setenv("TZ", "invalid-zone")
    with pytest.raises(ValueError, match="Unknown time zone"):
        timezone_name(None)


def test_environment_roots_are_only_used_for_the_actual_user_home(tmp_path, monkeypatch):
    home = tmp_path / "user"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "custom-claude"))
    args = dict(data_dir=None, pricing_path=None, codex_root=None, claude_roots=[],
                opencode_root=None, antigravity_roots=[])
    actual = configuration(home=None, **args)
    assert actual["claude_roots"] == [str(tmp_path / "custom-claude")]
    assert actual["database_path"] == str(home / ".tokencat-candidate/usage.sqlite3")
    isolated = configuration(home=tmp_path / "fixture", **args)
    assert isolated["claude_roots"] == []


def test_price_ranges_unknowns_and_free_rates_stay_distinct():
    cost = {"min_usd": 0.35, "max_usd": 0.45, "unpriced_events": 0, "priced_tokens": 100}
    assert cost_text(cost) == "$0.35–$0.45"
    assert cost_text({**cost, "unpriced_events": 1}) == "Known $0.35–$0.45"
    assert cost_text({**cost, "unpriced_events": 1, "priced_tokens": 0}) == "No price record"
    assert cost_text({**cost, "min_usd": 0, "max_usd": 0}) == "$0.00"
