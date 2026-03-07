"""Tests for MarketTemperature (core/analysis/market_temperature.py)."""

import pytest
import yaml
from unittest.mock import patch, MagicMock
from core.analysis.market_temperature import MarketTemperature


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_module_mock(score, weight=40, error=None):
    """Return a mock TempModule."""
    m = MagicMock()
    m.weight = weight
    if error:
        m.calculate.return_value = {"score": 0, "details": {}, "error": error}
    else:
        m.calculate.return_value = {"score": score, "details": {}, "error": None}
    return m


def _make_mt(temperature_config):
    """Build a MarketTemperature from the temp config path (all modules disabled)."""
    return MarketTemperature(config_path=temperature_config)


# ---------------------------------------------------------------------------
# _to_level mapping
# ---------------------------------------------------------------------------

def test_to_level_70_is_hot(temperature_config):
    mt = _make_mt(temperature_config)
    assert mt._to_level(70) == "HOT"


def test_to_level_40_is_warm(temperature_config):
    mt = _make_mt(temperature_config)
    assert mt._to_level(40) == "WARM"


def test_to_level_negative_20_is_neutral(temperature_config):
    mt = _make_mt(temperature_config)
    assert mt._to_level(-20) == "NEUTRAL"


def test_to_level_negative_60_is_cool(temperature_config):
    mt = _make_mt(temperature_config)
    assert mt._to_level(-60) == "COOL"


def test_to_level_below_negative_60_is_cold(temperature_config):
    mt = _make_mt(temperature_config)
    assert mt._to_level(-61) == "COLD"


def test_to_level_boundary_69_is_warm(temperature_config):
    mt = _make_mt(temperature_config)
    assert mt._to_level(69) == "WARM"


def test_to_level_boundary_exactly_neutral(temperature_config):
    mt = _make_mt(temperature_config)
    assert mt._to_level(-20) == "NEUTRAL"


# ---------------------------------------------------------------------------
# calculate: all modules disabled → temperature=0, level=NEUTRAL
# ---------------------------------------------------------------------------

def test_calculate_all_disabled_returns_neutral(temperature_config):
    mt = _make_mt(temperature_config)
    result = mt.calculate()
    assert result["temperature"] == 0
    assert result["level"] == "NEUTRAL"
    assert result["components"] == {}


# ---------------------------------------------------------------------------
# calculate: single module failure still produces result from remaining
# ---------------------------------------------------------------------------

def test_calculate_one_module_fails_rest_continue(temperature_config):
    mt = _make_mt(temperature_config)
    # Inject two mock modules: one succeeds, one returns error
    good = _make_module_mock(score=60, weight=40)
    bad = _make_module_mock(score=0, weight=35, error="simulated failure")
    mt.modules = {"macro": good, "sentiment": bad}

    result = mt.calculate()

    assert "sentiment" in result["failed"]
    assert "macro" not in result["failed"]
    # Temperature should be non-zero (coming from macro only)
    assert result["temperature"] != 0
    assert "macro" in result["components"]
    assert "sentiment" not in result["components"]


# ---------------------------------------------------------------------------
# calculate: failed module excluded + weights renormalized
# ---------------------------------------------------------------------------

def test_calculate_weight_renormalization(temperature_config):
    mt = _make_mt(temperature_config)
    # macro weight=40 succeeds with score=50; econ weight=25 fails
    macro = _make_module_mock(score=50, weight=40)
    econ = _make_module_mock(score=0, weight=25, error="fetch error")
    mt.modules = {"macro": macro, "econ": econ}

    result = mt.calculate()

    # With only macro remaining (weight 40/40 = 1.0), temperature = 50
    assert result["temperature"] == pytest.approx(50.0, abs=0.1)


# ---------------------------------------------------------------------------
# calculate: majority failure triggers warning (DiscordClient mock)
# ---------------------------------------------------------------------------

def test_calculate_majority_failure_warns(temperature_config):
    mt = _make_mt(temperature_config)
    bad1 = _make_module_mock(score=0, weight=40, error="err1")
    bad2 = _make_module_mock(score=0, weight=35, error="err2")
    mt.modules = {"macro": bad1, "sentiment": bad2}

    mock_discord_instance = MagicMock()
    # DiscordClient is imported locally inside calculate() so patch at its
    # source module location.
    with patch("core.discord_client.DiscordClient", return_value=mock_discord_instance):
        result = mt.calculate()

    assert len(result["failed"]) == 2
    mock_discord_instance.send_message.assert_called_once()
    msg = mock_discord_instance.send_message.call_args[0][0]
    assert "실패" in msg or "failed" in msg.lower()


# ---------------------------------------------------------------------------
# generate_report: output contains temperature and level
# ---------------------------------------------------------------------------

def test_generate_report_contains_temperature_and_level(temperature_config):
    mt = _make_mt(temperature_config)
    result = {
        "temperature": 55.0,
        "level": "WARM",
        "components": {},
        "details": {},
        "failed": [],
    }
    report = mt.generate_report(result)
    assert "55" in report or "55.0" in report
    assert "WARM" in report


# ---------------------------------------------------------------------------
# regime vector tests
# ---------------------------------------------------------------------------

def test_regime_vector_present_in_result(temperature_config):
    mt = _make_mt(temperature_config)
    result = mt.calculate()
    assert "regime" in result


def test_regime_has_all_dimensions(temperature_config):
    mt = _make_mt(temperature_config)
    result = mt.calculate()
    regime = result["regime"]
    assert "trend" in regime
    assert "volatility" in regime
    assert "liquidity" in regime
    assert "event_risk" in regime


def test_regime_trend_uptrend(temperature_config):
    mt = _make_mt(temperature_config)
    details = {
        "macro": {
            "us_index": {
                "trend_info": {"avg_change": 1.0}
            }
        }
    }
    regime = mt._compute_regime({}, details)
    assert regime["trend"] == "UPTREND"


def test_regime_trend_downtrend(temperature_config):
    mt = _make_mt(temperature_config)
    details = {
        "macro": {
            "us_index": {
                "trend_info": {"avg_change": -0.8}
            }
        }
    }
    regime = mt._compute_regime({}, details)
    assert regime["trend"] == "DOWNTREND"


def test_regime_trend_sideways(temperature_config):
    mt = _make_mt(temperature_config)
    details = {
        "macro": {
            "us_index": {
                "trend_info": {"avg_change": 0.0}
            }
        }
    }
    regime = mt._compute_regime({}, details)
    assert regime["trend"] == "SIDEWAYS"


def test_regime_volatility_expanding(temperature_config):
    mt = _make_mt(temperature_config)
    details = {
        "macro": {
            "vix": {
                "individual": {"VIX": {"current_price": 28.0}}
            }
        }
    }
    regime = mt._compute_regime({}, details)
    assert regime["volatility"] == "EXPANDING"


def test_regime_volatility_stable(temperature_config):
    """VIX 데이터 없으면 STABLE 반환."""
    mt = _make_mt(temperature_config)
    regime = mt._compute_regime({}, {})
    assert regime["volatility"] == "STABLE"


def test_regime_event_risk_high(temperature_config):
    mt = _make_mt(temperature_config)
    details = {
        "econ": {
            "uncertainty": {"pending_events": 3}
        }
    }
    regime = mt._compute_regime({}, details)
    assert regime["event_risk"] == "HIGH"


def test_regime_default_on_error(temperature_config):
    """_compute_regime 내부 예외 시 기본 중립값 반환."""
    mt = _make_mt(temperature_config)
    # Pass a non-dict details to force an exception path
    regime = mt._compute_regime(None, None)
    assert regime["trend"] == "SIDEWAYS"
    assert regime["volatility"] == "STABLE"
    assert regime["liquidity"] == "NORMAL"
    assert regime["event_risk"] == "LOW"


# ---------------------------------------------------------------------------
# liquidity regime tests (Stage 7 completion)
# ---------------------------------------------------------------------------


def test_regime_liquidity_high_from_spread(temperature_config):
    mt = _make_mt(temperature_config)
    regime = mt._compute_regime({}, {}, liquidity_data={"spread_bps": 3.0})
    assert regime["liquidity"] == "HIGH"


def test_regime_liquidity_normal_from_spread(temperature_config):
    mt = _make_mt(temperature_config)
    regime = mt._compute_regime({}, {}, liquidity_data={"spread_bps": 10.0})
    assert regime["liquidity"] == "NORMAL"


def test_regime_liquidity_low_from_spread(temperature_config):
    mt = _make_mt(temperature_config)
    regime = mt._compute_regime({}, {}, liquidity_data={"spread_bps": 25.0})
    assert regime["liquidity"] == "LOW"


def test_regime_liquidity_dry_from_spread(temperature_config):
    mt = _make_mt(temperature_config)
    regime = mt._compute_regime({}, {}, liquidity_data={"spread_bps": 50.0})
    assert regime["liquidity"] == "DRY"


def test_regime_liquidity_high_from_volume(temperature_config):
    mt = _make_mt(temperature_config)
    regime = mt._compute_regime({}, {}, liquidity_data={"volume_ratio": 4.0})
    assert regime["liquidity"] == "HIGH"


def test_regime_liquidity_normal_from_volume(temperature_config):
    mt = _make_mt(temperature_config)
    regime = mt._compute_regime({}, {}, liquidity_data={"volume_ratio": 2.0})
    assert regime["liquidity"] == "NORMAL"


def test_regime_liquidity_low_from_volume(temperature_config):
    mt = _make_mt(temperature_config)
    regime = mt._compute_regime({}, {}, liquidity_data={"volume_ratio": 0.7})
    assert regime["liquidity"] == "LOW"


def test_regime_liquidity_dry_from_volume(temperature_config):
    mt = _make_mt(temperature_config)
    regime = mt._compute_regime({}, {}, liquidity_data={"volume_ratio": 0.3})
    assert regime["liquidity"] == "DRY"


def test_regime_liquidity_default_no_data(temperature_config):
    """No liquidity_data -> NORMAL (backward compat)."""
    mt = _make_mt(temperature_config)
    regime = mt._compute_regime({}, {})
    assert regime["liquidity"] == "NORMAL"


def test_regime_liquidity_boundary_spread_5(temperature_config):
    """spread_bps == 5 -> HIGH (<=5)."""
    mt = _make_mt(temperature_config)
    regime = mt._compute_regime({}, {}, liquidity_data={"spread_bps": 5.0})
    assert regime["liquidity"] == "HIGH"


def test_calculate_passes_liquidity_data(temperature_config):
    """calculate(liquidity_data=...) propagates to regime."""
    mt = _make_mt(temperature_config)
    good = _make_module_mock(score=50, weight=40)
    mt.modules = {"macro": good}
    result = mt.calculate(liquidity_data={"spread_bps": 50.0})
    assert result["regime"]["liquidity"] == "DRY"


def test_backward_compat_level_unchanged(temperature_config):
    """regime 추가 후에도 level, temperature, components 필드가 동일하게 존재."""
    mt = _make_mt(temperature_config)
    good = _make_module_mock(score=50, weight=40)
    mt.modules = {"macro": good}

    result = mt.calculate()
    assert "temperature" in result
    assert "level" in result
    assert "components" in result
    assert "details" in result
    assert "failed" in result
    assert "degraded" in result
    # regime present as well
    assert "regime" in result
