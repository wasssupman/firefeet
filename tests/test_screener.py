"""Tests for StockScreener (core/analysis/scoring_engine.py)."""

import pytest
import pandas as pd
from tests.mocks.mock_kis import make_ohlc_dataframe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_stock(code="005930", name="삼성전자", price=51000,
               volume=5000000, change_rate=2.0):
    return {"code": code, "name": name, "price": price,
            "volume": volume, "change_rate": change_rate}


def make_supply(sentiment="BULLISH (Double Buy)", foreign_3d=100000, institution_3d=50000):
    return {"sentiment": sentiment, "foreign_3d": foreign_3d, "institution_3d": institution_3d}


def make_screener(strategy, settings_path=None):
    from core.analysis.scoring_engine import StockScreener
    return StockScreener(strategy=strategy, discord=None, settings_path=settings_path)


# ---------------------------------------------------------------------------
# _score_volume_surge
# ---------------------------------------------------------------------------

def test_score_volume_surge_5x_returns_100(strategy):
    screener = make_screener(strategy)
    # ohlc index 0 = today (ignored for avg), indices 1-5 = past 5 days avg
    # avg_5d volume = 1_000_000 (base make_ohlc_dataframe default at i=1..5)
    ohlc = make_ohlc_dataframe(days=30)
    avg_5d = ohlc.iloc[1:6]["volume"].mean()
    stock = make_stock(volume=int(avg_5d * 5.5))
    assert screener._score_volume_surge(stock, ohlc) == 100


def test_score_volume_surge_2x_returns_60(strategy):
    screener = make_screener(strategy)
    ohlc = make_ohlc_dataframe(days=30)
    avg_5d = ohlc.iloc[1:6]["volume"].mean()
    stock = make_stock(volume=int(avg_5d * 2.1))
    assert screener._score_volume_surge(stock, ohlc) == 60


def test_score_volume_surge_below_1x_returns_0(strategy):
    screener = make_screener(strategy)
    ohlc = make_ohlc_dataframe(days=30)
    avg_5d = ohlc.iloc[1:6]["volume"].mean()
    stock = make_stock(volume=int(avg_5d * 0.5))
    assert screener._score_volume_surge(stock, ohlc) == 0


def test_score_volume_surge_none_ohlc_returns_0(strategy):
    screener = make_screener(strategy)
    stock = make_stock(volume=10000000)
    assert screener._score_volume_surge(stock, None) == 0


# ---------------------------------------------------------------------------
# _score_price_momentum
# ---------------------------------------------------------------------------

def test_score_price_momentum_3pct_returns_100(strategy):
    screener = make_screener(strategy)
    stock = make_stock(change_rate=3.0)
    assert screener._score_price_momentum(stock) == pytest.approx(100.0)


def test_score_price_momentum_0pct_returns_0(strategy):
    screener = make_screener(strategy)
    stock = make_stock(change_rate=0.0)
    assert screener._score_price_momentum(stock) == 0


def test_score_price_momentum_13pct_returns_0(strategy):
    screener = make_screener(strategy)
    stock = make_stock(change_rate=13.0)
    assert screener._score_price_momentum(stock) == 0


def test_score_price_momentum_above_13pct_returns_0(strategy):
    screener = make_screener(strategy)
    stock = make_stock(change_rate=15.0)
    assert screener._score_price_momentum(stock) == 0


# ---------------------------------------------------------------------------
# _score_ma_alignment
# ---------------------------------------------------------------------------

def test_score_ma_alignment_full_alignment_at_least_60(strategy):
    screener = make_screener(strategy)
    # Build OHLC where price > ma5 > ma20
    rows = []
    for i in range(30):
        rows.append({
            "date": f"2026{i:04d}",
            "open": 50000 - i * 100,
            "high": 52000 - i * 100,
            "low": 48000 - i * 100,
            "close": 51000 - i * 100,   # older rows have lower close → ma20 < ma5
            "volume": 1000000,
        })
    ohlc = pd.DataFrame(rows)
    # price is above ma5 and ma5 is above ma20 because recent rows have higher close
    price = 52000
    stock = make_stock(price=price)
    score = screener._score_ma_alignment(stock, ohlc)
    assert score >= 60


def test_score_ma_alignment_price_below_ma5_returns_0(strategy):
    screener = make_screener(strategy)
    rows = []
    for i in range(30):
        rows.append({
            "date": f"2026{i:04d}",
            "open": 60000,
            "high": 62000,
            "low": 58000,
            "close": 60000,
            "volume": 1000000,
        })
    ohlc = pd.DataFrame(rows)
    stock = make_stock(price=50000)  # price below ma5 (60000)
    score = screener._score_ma_alignment(stock, ohlc)
    assert score == 0


# ---------------------------------------------------------------------------
# _score_supply_demand
# ---------------------------------------------------------------------------

def test_score_supply_demand_bullish_double_buy_at_least_80(strategy):
    screener = make_screener(strategy)
    supply = make_supply("BULLISH (Double Buy)", 100000, 50000)
    score = screener._score_supply_demand(supply)
    assert score >= 80


def test_score_supply_demand_bearish_returns_0(strategy):
    screener = make_screener(strategy)
    supply = make_supply("BEARISH (Double Sell)", -100000, -50000)
    score = screener._score_supply_demand(supply)
    assert score == 0


def test_score_supply_demand_neutral_returns_25(strategy):
    screener = make_screener(strategy)
    supply = {"sentiment": "NEUTRAL", "foreign_3d": 0, "institution_3d": 0}
    score = screener._score_supply_demand(supply)
    assert score == 25


def test_score_supply_demand_none_returns_0(strategy):
    screener = make_screener(strategy)
    assert screener._score_supply_demand(None) == 0


# ---------------------------------------------------------------------------
# _score_breakout_proximity
# ---------------------------------------------------------------------------

def test_score_breakout_proximity_at_target_at_least_85(strategy):
    screener = make_screener(strategy)
    # yesterday high=52000, low=48000 → range=4000, k=0.5 → volatility=2000
    # today open=50000 → target=52000
    rows = [
        {"date": "20260226", "open": 50000, "high": 52100, "low": 49500, "close": 52000, "volume": 2000000},
        {"date": "20260225", "open": 49000, "high": 52000, "low": 48000, "close": 50500, "volume": 1500000},
    ]
    for i in range(2, 30):
        rows.append({"date": f"2026{i:04d}", "open": 48000, "high": 50000,
                     "low": 47000, "close": 49000, "volume": 1000000})
    ohlc = pd.DataFrame(rows)
    # target = 50000 + (52000-48000)*0.5 = 52000
    stock = make_stock(price=52000)
    score = screener._score_breakout_proximity(stock, ohlc)
    assert score >= 85


def test_score_breakout_proximity_large_gap_returns_0(strategy):
    screener = make_screener(strategy)
    rows = [
        {"date": "20260226", "open": 50000, "high": 52000, "low": 49000, "close": 51000, "volume": 2000000},
        {"date": "20260225", "open": 49000, "high": 51000, "low": 48000, "close": 50000, "volume": 1500000},
    ]
    for i in range(2, 30):
        rows.append({"date": f"2026{i:04d}", "open": 48000, "high": 50000,
                     "low": 47000, "close": 49000, "volume": 1000000})
    ohlc = pd.DataFrame(rows)
    # target = 50000 + (51000-48000)*0.5 = 51500; price=44000, gap > 5%
    stock = make_stock(price=44000)
    score = screener._score_breakout_proximity(stock, ohlc)
    assert score == 0


# ---------------------------------------------------------------------------
# _score_intraday_strength
# ---------------------------------------------------------------------------

def test_score_intraday_strength_near_high_returns_100(strategy):
    screener = make_screener(strategy)
    stock = make_stock(price=51800)
    current_data = {"high": 52000}
    score = screener._score_intraday_strength(stock, current_data)
    assert score == 100


def test_score_intraday_strength_3pct_drop_returns_0(strategy):
    screener = make_screener(strategy)
    stock = make_stock(price=50000)
    current_data = {"high": 52000}  # drop ≈ 3.85% > 3%
    score = screener._score_intraday_strength(stock, current_data)
    assert score == 0


# ---------------------------------------------------------------------------
# score_stock
# ---------------------------------------------------------------------------

def test_score_stock_none_ohlc_returns_0(strategy):
    screener = make_screener(strategy)
    stock = make_stock()
    result = screener.score_stock(stock, None, make_supply(), {"high": 52000})
    assert result is None


def test_score_stock_weighted_sum(strategy):
    screener = make_screener(strategy)
    ohlc = make_ohlc_dataframe(days=30)
    stock = make_stock(price=51000, volume=5000000, change_rate=3.0)
    supply = make_supply("BULLISH (Double Buy)", 100000, 50000)
    current_data = {"high": 52000}
    result = screener.score_stock(stock, ohlc, supply, current_data)
    assert isinstance(result, dict)
    assert "total_score" in result
    assert "detail" in result
    assert 0 <= result["total_score"] <= 100


# ---------------------------------------------------------------------------
# Pre-filter: low volume stock removed
# ---------------------------------------------------------------------------

def test_screen_prefilter_low_volume_removed(strategy):
    screener = make_screener(strategy)
    ohlc = make_ohlc_dataframe(days=30)
    supply = make_supply()
    current_data = {"high": 52000}

    low_vol_stock = make_stock(code="111111", volume=100)   # below min_volume=500000
    good_stock = make_stock(code="005930", volume=1000000, change_rate=3.0)

    def data_provider(code):
        return ohlc, supply, current_data

    results = screener.screen([low_vol_stock, good_stock], data_provider)
    result_codes = [r["code"] for r in results]
    assert "111111" not in result_codes


# ---------------------------------------------------------------------------
# screen: threshold filtering
# ---------------------------------------------------------------------------

def test_screen_filters_below_threshold(strategy, tmp_path):
    """Stocks below min_score threshold are excluded from results."""
    # Create settings with a very high min_score so no stock passes
    settings = {
        "weights": {"volume_surge": 20, "price_momentum": 15, "ma_alignment": 20,
                    "supply_demand": 20, "breakout_proximity": 15, "intraday_strength": 10},
        "pre_filter": {"min_volume": 1, "max_price": 1000000,
                       "min_change_rate": -100.0, "max_change_rate": 100.0},
        "output": {"min_score": 99, "max_stocks": 10},
        "cache": {"ttl": 300},
    }
    import yaml
    settings_file = tmp_path / "screener_settings.yaml"
    with open(settings_file, "w") as f:
        yaml.dump(settings, f)

    from core.analysis.scoring_engine import StockScreener
    screener = StockScreener(strategy=strategy, discord=None, settings_path=str(settings_file))

    ohlc = make_ohlc_dataframe(days=30)
    supply = {"sentiment": "NEUTRAL", "foreign_3d": 0, "institution_3d": 0}
    current_data = {"high": 52000}

    stock = make_stock(volume=600000, change_rate=1.0, price=51000)

    def data_provider(code):
        return ohlc, supply, current_data

    results = screener.screen([stock], data_provider)
    assert results == []
