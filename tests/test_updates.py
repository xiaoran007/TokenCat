from tokencat.core.models import DashboardThemeMode
from tokencat.core.render import resolve_dashboard_theme
from tokencat.core.updates import UpdateNotice, check_latest_version


def test_resolve_dashboard_theme_uses_colorfgbg_background() -> None:
    assert resolve_dashboard_theme(DashboardThemeMode.AUTO, {"COLORFGBG": "15;0"}) is DashboardThemeMode.DARK
    assert resolve_dashboard_theme(DashboardThemeMode.AUTO, {"COLORFGBG": "0;15"}) is DashboardThemeMode.LIGHT
    assert resolve_dashboard_theme(DashboardThemeMode.AUTO, {}) is DashboardThemeMode.DARK


def test_resolve_dashboard_theme_respects_explicit_theme() -> None:
    assert resolve_dashboard_theme(DashboardThemeMode.DARK, {"COLORFGBG": "0;15"}) is DashboardThemeMode.DARK
    assert resolve_dashboard_theme(DashboardThemeMode.LIGHT, {"COLORFGBG": "15;0"}) is DashboardThemeMode.LIGHT


class _FakePyPIResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakePyPIResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_check_latest_version_returns_notice_for_newer_release(monkeypatch) -> None:
    monkeypatch.setattr(
        "tokencat.core.updates.urlopen",
        lambda url, timeout=0: _FakePyPIResponse(b'{"info":{"version":"0.5.0"}}'),
    )

    notice = check_latest_version("0.4.0")

    assert notice == UpdateNotice(current_version="0.4.0", latest_version="0.5.0")


def test_check_latest_version_returns_none_for_same_or_older_release(monkeypatch) -> None:
    monkeypatch.setattr(
        "tokencat.core.updates.urlopen",
        lambda url, timeout=0: _FakePyPIResponse(b'{"info":{"version":"0.4.0"}}'),
    )
    assert check_latest_version("0.4.0") is None

    monkeypatch.setattr(
        "tokencat.core.updates.urlopen",
        lambda url, timeout=0: _FakePyPIResponse(b'{"info":{"version":"0.3.9"}}'),
    )
    assert check_latest_version("0.4.0") is None


def test_check_latest_version_returns_none_for_invalid_or_failed_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "tokencat.core.updates.urlopen",
        lambda url, timeout=0: _FakePyPIResponse(b'{"info":{"version":"0.5.0rc1"}}'),
    )
    assert check_latest_version("0.4.0") is None

    def fail_urlopen(url, timeout=0):
        raise OSError("network down")

    monkeypatch.setattr("tokencat.core.updates.urlopen", fail_urlopen)
    assert check_latest_version("0.4.0") is None
