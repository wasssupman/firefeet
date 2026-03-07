"""Tests for StockScanner (core/execution/scanner.py)."""

import pytest
from unittest.mock import patch, MagicMock
from core.execution.scanner import StockScanner, ETF_PREFIXES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_stock_list(n=3):
    return [
        {"code": f"00593{i}", "name": f"종목{i}", "price": 50000 + i * 1000,
         "volume": 1000000 + i * 100000, "change_rate": 1.0 + i * 0.5}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# get_top_stocks: primary_fetcher used during market hours
# ---------------------------------------------------------------------------

def test_get_top_stocks_uses_primary_fetcher_during_market_hours():
    expected = make_stock_list(2)
    fetcher = MagicMock(return_value=expected)
    scanner = StockScanner(primary_fetcher=fetcher)

    with patch.object(StockScanner, "_is_market_hours", return_value=True):
        result = scanner.get_top_stocks(limit=2)

    fetcher.assert_called_once_with(limit=2, min_price=StockScanner.MIN_PRICE)
    assert result == expected


# ---------------------------------------------------------------------------
# get_top_stocks: Naver fallback when primary_fetcher is None (market hours)
# ---------------------------------------------------------------------------

def test_get_top_stocks_falls_back_to_naver_when_no_primary():
    naver_stocks = make_stock_list(3)
    scanner = StockScanner(primary_fetcher=None)

    with patch.object(StockScanner, "_is_market_hours", return_value=True), \
         patch.object(scanner, "_scrape_naver", return_value=naver_stocks) as mock_naver:
        result = scanner.get_top_stocks(limit=3)

    mock_naver.assert_called_once_with(3)
    assert result == naver_stocks


# ---------------------------------------------------------------------------
# Stock code is 6 digits
# ---------------------------------------------------------------------------

def test_stock_codes_are_6_digits():
    stocks = make_stock_list(5)
    for s in stocks:
        assert len(s["code"]) == 6, f"Code {s['code']} is not 6 digits"


# ---------------------------------------------------------------------------
# _parse_int utility
# ---------------------------------------------------------------------------

def test_parse_int_handles_comma_separated():
    assert StockScanner._parse_int("1,234,567") == 1234567


def test_parse_int_returns_0_on_invalid():
    assert StockScanner._parse_int("abc") == 0


def test_parse_int_handles_plain_number():
    assert StockScanner._parse_int("50000") == 50000


# ---------------------------------------------------------------------------
# _parse_float utility
# ---------------------------------------------------------------------------

def test_parse_float_handles_percent_sign():
    assert StockScanner._parse_float("+2.50%") == pytest.approx(2.50)


def test_parse_float_handles_negative():
    assert StockScanner._parse_float("-1.30") == pytest.approx(-1.30)


def test_parse_float_returns_0_on_invalid():
    assert StockScanner._parse_float("N/A") == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# ETF filtering: ETF_PREFIXES names must be excluded by _scrape_naver_market
# ---------------------------------------------------------------------------

def test_etf_prefixes_cover_major_brands():
    for prefix in ("KODEX", "TIGER", "KBSTAR", "KOSEF", "ARIRANG", "SOL"):
        assert prefix in ETF_PREFIXES


def test_scrape_naver_filters_etf_names():
    """_scrape_naver_market must skip rows whose name starts with an ETF prefix."""
    from bs4 import BeautifulSoup

    def _build_row(name, code, price="50,000", volume="1,000,000", change="+1.00"):
        return (
            f'<tr>'
            f'<td>1</td>'
            f'<td><a href="?code={code}">{name}</a></td>'
            f'<td>{price}</td>'
            f'<td>500</td>'
            f'<td>{change}</td>'
            f'<td>{volume}</td>'
            f'</tr>'
        )

    html = (
        '<table class="type_2"><tbody>'
        + _build_row("KODEX 200", "069500", "30,000", "2,000,000", "+0.50")
        + _build_row("삼성전자", "005930", "71,000", "3,000,000", "+1.20")
        + '</tbody></table>'
    )

    mock_response = MagicMock()
    mock_response.text = html
    mock_response.raise_for_status = MagicMock()

    scanner = StockScanner()
    with patch("requests.get", return_value=mock_response):
        result = scanner._scrape_naver_market(sosok=0)

    codes = [s["code"] for s in result]
    assert "069500" not in codes   # ETF filtered out
    assert "005930" in codes       # real stock kept
