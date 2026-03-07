"""Tests for core.econ_calendar.EconCalendar."""

import os
import datetime
import pytest
import yaml
from unittest.mock import patch

from core.econ_calendar import EconCalendar


# ---------------------------------------------------------------------------
# Patch helper: replace datetime.date.today() inside core.econ_calendar
# ---------------------------------------------------------------------------

def _fixed_date_class(fixed_date: datetime.date):
    """Return a datetime.date subclass whose today() returns fixed_date."""
    class _FixedDate(datetime.date):
        @classmethod
        def today(cls):
            return fixed_date
    return _FixedDate


def _parse_with_year(cal, html, year):
    """Call _parse_marketwatch_html with datetime.date patched to a fixed year."""
    fixed = datetime.date(year, 1, 1)  # day/month don't matter; year is what's used
    fake_cls = _fixed_date_class(fixed)
    with patch("core.econ_calendar.datetime.date", fake_cls):
        return cal._parse_marketwatch_html(html)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_CONFIG = {
    "indicators": [
        {
            "name": "CPI",
            "keywords": ["CPI", "Consumer Price"],
            "importance": "high",
            "country": "US",
            "unit": "pct",
        },
        {
            "name": "Nonfarm Payrolls",
            "keywords": ["Nonfarm Payrolls", "NFP"],
            "importance": "high",
            "country": "US",
            "unit": "k",
        },
    ]
}


def _write_config(tmp_path, data=None):
    """Write econ_calendar.yaml to tmp_path and return its path string."""
    if data is None:
        data = _BASE_CONFIG
    path = tmp_path / "econ_calendar.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)
    return str(path)


def _build_html(date_header, rows):
    """
    Build minimal MarketWatch-like HTML.

    date_header: e.g. "MONDAY, FEB. 9"
    rows: list of (time, event, period, actual, forecast) tuples
    """
    row_html = ""
    for time_val, event, period, actual, forecast in rows:
        row_html += (
            f"<tr>"
            f"<td>{time_val}</td>"
            f"<td>{event}</td>"
            f"<td>{period}</td>"
            f"<td>{actual}</td>"
            f"<td>{forecast}</td>"
            f"</tr>\n"
        )
    return f"""
    <html><body>
    <table>
      <tr><th class="day">{date_header}</th></tr>
      {row_html}
    </table>
    </body></html>
    """


# ---------------------------------------------------------------------------
# 1. ET→KST DST 변換 (H7 회귀) — 동절기 (EST = UTC-5, +14h to KST)
# ---------------------------------------------------------------------------

def test_et_to_kst_winter_conversion(tmp_path):
    """Winter: 8:30 am ET (EST, UTC-5) should convert to 22:30 KST (+14h)."""
    config_path = _write_config(tmp_path)
    cal = EconCalendar(config_path=config_path)

    # Use a date firmly in winter: 2026-01-09 (January — no DST)
    html = _build_html(
        "FRIDAY, JAN. 9",
        [("8:30 am", "CPI Index", "Dec", "-", "0.3%")],
    )
    events = _parse_with_year(cal, html, 2026)

    assert len(events) == 1
    assert events[0]["kst_time"] == "22:30 (KST)"


def test_et_to_kst_summer_conversion(tmp_path):
    """Summer: 8:30 am ET (EDT, UTC-4) should convert to 21:30 KST (+13h)."""
    config_path = _write_config(tmp_path)
    cal = EconCalendar(config_path=config_path)

    # Use a date firmly in summer: 2026-06-05 (June — DST active)
    html = _build_html(
        "FRIDAY, JUN. 5",
        [("8:30 am", "CPI Index", "May", "-", "0.3%")],
    )
    events = _parse_with_year(cal, html, 2026)

    assert len(events) == 1
    assert events[0]["kst_time"] == "21:30 (KST)"


# ---------------------------------------------------------------------------
# 2. _parse_marketwatch_html(): 정상 HTML → events list
# ---------------------------------------------------------------------------

def test_parse_marketwatch_html_normal(tmp_path):
    """_parse_marketwatch_html returns correctly structured events for valid HTML."""
    config_path = _write_config(tmp_path)
    cal = EconCalendar(config_path=config_path)

    html = _build_html(
        "THURSDAY, FEB. 9",
        [
            ("8:30 am", "CPI Index", "Jan", "0.4%", "0.3%"),
            ("8:30 am", "Nonfarm Payrolls", "Jan", "275K", "200K"),
        ],
    )
    events = _parse_with_year(cal, html, 2026)

    assert len(events) == 2

    cpi = next(e for e in events if e["target_name"] == "CPI")
    assert cpi["date"] == "2026-02-09"
    assert cpi["actual"] == "0.4%"
    assert cpi["forecast"] == "0.3%"
    assert cpi["importance"] == "high"
    assert cpi["country"] == "US"

    nfp = next(e for e in events if e["target_name"] == "Nonfarm Payrolls")
    assert nfp["actual"] == "275K"


# ---------------------------------------------------------------------------
# 3. 파싱 실패 시 graceful skip (empty list)
# ---------------------------------------------------------------------------

def test_parse_malformed_html_returns_empty(tmp_path):
    """Completely malformed HTML returns an empty list without raising."""
    config_path = _write_config(tmp_path)
    cal = EconCalendar(config_path=config_path)

    result = cal._parse_marketwatch_html("<html><body>no table here</body></html>")
    assert result == []


def test_parse_empty_string_returns_empty(tmp_path):
    """Empty string input returns an empty list."""
    config_path = _write_config(tmp_path)
    cal = EconCalendar(config_path=config_path)

    result = cal._parse_marketwatch_html("")
    assert result == []


# ---------------------------------------------------------------------------
# 4. 타겟 필터링: config indicators의 keywords 매칭
# ---------------------------------------------------------------------------

def test_non_target_events_are_filtered_out(tmp_path):
    """Events whose name does not match any indicator keyword are excluded."""
    config_path = _write_config(tmp_path)
    cal = EconCalendar(config_path=config_path)

    html = _build_html(
        "MONDAY, MAR. 2",
        [
            ("10:00 am", "CPI Index", "Feb", "0.2%", "0.2%"),
            ("10:30 am", "Mortgage Applications", "Feb", "1.5%", "-"),  # not in config
        ],
    )
    events = _parse_with_year(cal, html, 2026)

    names = [e["target_name"] for e in events]
    assert "CPI" in names
    assert all("Mortgage" not in e["name"] for e in events)


def test_keyword_matching_is_case_insensitive_substring(tmp_path):
    """Keyword matching in event names is case-insensitive and substring-based."""
    config_path = _write_config(tmp_path)
    cal = EconCalendar(config_path=config_path)

    # "consumer price index" should match keyword "Consumer Price"
    html = _build_html(
        "TUESDAY, APR. 7",
        [("8:30 am", "consumer price index", "Mar", "0.1%", "0.2%")],
    )
    events = _parse_with_year(cal, html, 2026)

    assert len(events) == 1
    assert events[0]["target_name"] == "CPI"


# ---------------------------------------------------------------------------
# 5. 빈 테이블 → empty list
# ---------------------------------------------------------------------------

def test_empty_table_returns_empty_list(tmp_path):
    """A table with no data rows returns an empty list."""
    config_path = _write_config(tmp_path)
    cal = EconCalendar(config_path=config_path)

    html = "<html><body><table></table></body></html>"
    result = cal._parse_marketwatch_html(html)
    assert result == []

