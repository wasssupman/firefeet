"""Tests for VolatilityBreakoutStrategy — P0 signal logic."""

import pytest
import pandas as pd

from core.analysis.technical import VolatilityBreakoutStrategy
from tests.mocks.mock_kis import make_ohlc_dataframe


# ── Helpers ─────────────────────────────────────────────────

def _two_row_df(today_open, yesterday_high, yesterday_low):
    """Minimal 2-row OHLC: index 0 = today, index 1 = yesterday."""
    return pd.DataFrame([
        {"date": "20260226", "open": today_open, "high": today_open + 500,
         "low": today_open - 500, "close": today_open + 200, "volume": 2000000},
        {"date": "20260225", "open": yesterday_low, "high": yesterday_high,
         "low": yesterday_low, "close": yesterday_high - 100, "volume": 1500000},
    ])


# ── check_buy_signal ─────────────────────────────────────────

class TestCheckBuySignal:

    def test_buy_signal_when_price_exceeds_target(self, strategy, breakout_ohlc):
        """돌파 조건 충족(current_price >= target) → signal='BUY'."""
        # breakout_ohlc: today open=50000, yesterday hi=51000 lo=48000
        # target = 50000 + (51000-48000)*0.5 = 51500
        result = strategy.check_buy_signal("005930", breakout_ohlc, current_price=52000)
        assert result is not None
        assert result["signal"] == "BUY"
        assert result["current_price"] == 52000

    def test_no_signal_when_price_below_target(self, strategy, breakout_ohlc):
        """목표가 미달(current_price < target) → signal=None."""
        # target = 51500 (same setup)
        result = strategy.check_buy_signal("005930", breakout_ohlc, current_price=51000)
        assert result is not None
        assert result["signal"] is None

    def test_no_signal_when_df_is_none(self, strategy):
        """OHLC None → None 반환."""
        result = strategy.check_buy_signal("005930", None, current_price=50000)
        assert result is None

    def test_no_signal_when_df_is_empty(self, strategy):
        """OHLC empty DataFrame → None 반환."""
        result = strategy.check_buy_signal("005930", pd.DataFrame(), current_price=50000)
        assert result is None

    def test_no_signal_when_df_has_one_row(self, strategy):
        """OHLC 1행 → None 반환 (어제 범위 계산 불가)."""
        single = make_ohlc_dataframe(days=1)
        result = strategy.check_buy_signal("005930", single, current_price=50000)
        assert result is None

    def test_signal_at_exact_target_price(self, strategy):
        """current_price == target_price (경계) → BUY."""
        df = _two_row_df(today_open=50000, yesterday_high=52000, yesterday_low=48000)
        # target = 50000 + (52000-48000)*0.5 = 52000
        result = strategy.check_buy_signal("005930", df, current_price=52000)
        assert result["signal"] == "BUY"

    def test_result_contains_expected_keys(self, strategy, sample_ohlc):
        """결과 dict에 필수 키가 포함되어야 한다."""
        result = strategy.check_buy_signal("005930", sample_ohlc, current_price=50000)
        assert result is not None
        for key in ("signal", "current_price", "target_price", "volatility_k", "profit_potential"):
            assert key in result


# ── get_target_price ─────────────────────────────────────────

class TestGetTargetPrice:

    def test_target_price_calculation(self, strategy):
        """target = open + (yesterday_high - yesterday_low) * k."""
        df = _two_row_df(today_open=50000, yesterday_high=52000, yesterday_low=48000)
        result = strategy.get_target_price("005930", df)
        # (52000-48000)*0.5 = 2000; target = 50000+2000 = 52000
        assert result is not None
        assert result["target_price"] == 52000
        assert result["today_open"] == 50000
        assert result["volatility_range"] == 2000

    def test_target_price_uses_k(self):
        """k=0.3 일 때 올바른 목표가 계산."""
        strat = VolatilityBreakoutStrategy(k=0.3)
        df = _two_row_df(today_open=50000, yesterday_high=52000, yesterday_low=48000)
        result = strat.get_target_price("005930", df)
        # (52000-48000)*0.3 = 1200; target = 51200
        assert result["target_price"] == pytest.approx(51200)

    def test_target_price_returns_none_for_insufficient_data(self, strategy):
        """1행 → None."""
        single = make_ohlc_dataframe(days=1)
        result = strategy.get_target_price("005930", single)
        assert result is None


# ── should_sell ──────────────────────────────────────────────

class TestShouldSell:

    def test_sell_take_profit(self, strategy):
        """profit_rate >= take_profit → SELL_TAKE_PROFIT."""
        # take_profit default = 4.0%
        result = strategy.should_sell(current_price=104500, buy_price=100000,
                                      current_time_str="1200")
        assert result == "SELL_TAKE_PROFIT"

    def test_sell_stop_loss(self, strategy):
        """profit_rate <= stop_loss → SELL_STOP_LOSS."""
        # stop_loss default = -2.0%
        result = strategy.should_sell(current_price=97500, buy_price=100000,
                                      current_time_str="1200")
        assert result == "SELL_STOP_LOSS"

    def test_sell_eod_at_1520(self, strategy):
        """time_str == '1520' → SELL_EOD."""
        result = strategy.should_sell(current_price=100500, buy_price=100000,
                                      current_time_str="1520")
        assert result == "SELL_EOD"

    def test_sell_eod_after_1520(self, strategy):
        """time_str > '1520' → SELL_EOD."""
        result = strategy.should_sell(current_price=100500, buy_price=100000,
                                      current_time_str="1530")
        assert result == "SELL_EOD"

    def test_no_sell_signal_when_conditions_not_met(self, strategy):
        """조건 미충족 → None."""
        result = strategy.should_sell(current_price=101000, buy_price=100000,
                                      current_time_str="1100")
        assert result is None

    def test_no_sell_when_buy_price_zero(self, strategy):
        """buy_price=0 → None (division guard)."""
        result = strategy.should_sell(current_price=100000, buy_price=0,
                                      current_time_str="1100")
        assert result is None

    def test_take_profit_priority_over_eod(self, strategy):
        """TP 조건이 EOD보다 먼저 평가된다."""
        result = strategy.should_sell(current_price=104000, buy_price=100000,
                                      current_time_str="1520")
        assert result == "SELL_TAKE_PROFIT"


# ── apply_temperature ────────────────────────────────────────

class TestApplyTemperature:

    HOT_PROFILES = {
        "HOT":     {"k": 0.3, "take_profit": 4.0, "stop_loss": -3.0, "max_position_pct": 0.35},
        "NEUTRAL": {"k": 0.5, "take_profit": 3.0, "stop_loss": -3.0, "max_position_pct": 0.25},
        "COLD":    {"k": 0.7, "take_profit": 2.0, "stop_loss": -2.0, "max_position_pct": 0.15},
    }

    def test_hot_profile_sets_correct_params(self, strategy):
        """HOT 프로필 적용 시 k=0.3, TP=4.0%, SL=-3.0%."""
        strategy.apply_temperature({"level": "HOT"}, self.HOT_PROFILES)
        assert strategy.k == pytest.approx(0.3)
        assert strategy.take_profit == pytest.approx(4.0)
        assert strategy.stop_loss == pytest.approx(-3.0)
        assert strategy.max_position_pct == pytest.approx(0.35)
        assert strategy.temperature_level == "HOT"

    def test_cold_profile_sets_correct_params(self, strategy):
        """COLD 프로필 적용 시 k=0.7, TP=2.0%."""
        strategy.apply_temperature({"level": "COLD"}, self.HOT_PROFILES)
        assert strategy.k == pytest.approx(0.7)
        assert strategy.take_profit == pytest.approx(2.0)
        assert strategy.stop_loss == pytest.approx(-2.0)

    def test_missing_level_falls_back_to_neutral(self, strategy):
        """없는 레벨은 NEUTRAL 프로필로 폴백."""
        strategy.apply_temperature({"level": "UNKNOWN"}, self.HOT_PROFILES)
        assert strategy.k == pytest.approx(0.5)


# ── calculate_atr ─────────────────────────────────────────

class TestCalculateATR:

    def test_atr_with_uniform_range(self, sample_ohlc):
        """균일한 range(4000)의 OHLC → ATR ≈ 4000."""
        atr = VolatilityBreakoutStrategy.calculate_atr(sample_ohlc, period=14)
        assert atr is not None
        assert atr == pytest.approx(4000, rel=0.01)

    def test_atr_returns_none_for_insufficient_data(self):
        """데이터 부족 (period+1 미만) → None."""
        df = make_ohlc_dataframe(days=5)
        atr = VolatilityBreakoutStrategy.calculate_atr(df, period=14)
        assert atr is None

    def test_atr_returns_none_for_none_df(self):
        """None DataFrame → None."""
        assert VolatilityBreakoutStrategy.calculate_atr(None, period=14) is None

    def test_atr_returns_none_for_empty_df(self):
        """Empty DataFrame → None."""
        assert VolatilityBreakoutStrategy.calculate_atr(pd.DataFrame(), period=14) is None

    def test_atr_period_5(self, sample_ohlc):
        """ATR(5) 계산."""
        atr = VolatilityBreakoutStrategy.calculate_atr(sample_ohlc, period=5)
        assert atr is not None
        assert atr == pytest.approx(4000, rel=0.01)

    def test_atr_with_gap(self):
        """갭 발생 시 True Range가 high-low보다 큼."""
        rows = [
            {"date": "20260227", "open": 55000, "high": 56000, "low": 54000, "close": 55500, "volume": 1000000},
            {"date": "20260226", "open": 50000, "high": 51000, "low": 49000, "close": 50000, "volume": 1000000},  # gap up
            {"date": "20260225", "open": 49500, "high": 50500, "low": 49000, "close": 50000, "volume": 1000000},
        ]
        df = pd.DataFrame(rows)
        atr = VolatilityBreakoutStrategy.calculate_atr(df, period=2)
        # Row 0: high-low=2000, |high-prev_close|=|56000-50000|=6000, |low-prev_close|=|54000-50000|=4000 → TR=6000
        # Row 1: high-low=2000, |high-prev_close|=|51000-50000|=1000, |low-prev_close|=|49000-50000|=1000 → TR=2000
        # ATR = (6000+2000)/2 = 4000
        assert atr == pytest.approx(4000)


# ── get_contraction_ratio ─────────────────────────────────

class TestContractionRatio:

    def test_uniform_range_ratio_is_one(self, strategy, sample_ohlc):
        """균일한 range → ATR5/ATR20 ≈ 1.0."""
        ratio = strategy.get_contraction_ratio(sample_ohlc)
        assert ratio is not None
        assert ratio == pytest.approx(1.0, rel=0.05)

    def test_contraction_detected(self, strategy):
        """최근 5일 range가 20일 평균보다 작으면 ratio < 1."""
        rows = []
        # Recent 6 days: narrow range (1000)
        for i in range(6):
            rows.append({"date": f"2026030{6-i}", "open": 50000, "high": 50500, "low": 49500, "close": 50200, "volume": 1000000})
        # Older 16 days: wide range (4000)
        for i in range(16):
            rows.append({"date": f"2026021{16-i:02d}", "open": 50000, "high": 52000, "low": 48000, "close": 51000, "volume": 1000000})
        df = pd.DataFrame(rows)
        ratio = strategy.get_contraction_ratio(df)
        assert ratio is not None
        assert ratio < 0.5  # narrow/wide ≈ 1000/4000 = 0.25

    def test_expansion_detected(self, strategy):
        """최근 5일 range가 20일 평균보다 크면 ratio > 1."""
        rows = []
        # Recent 6 days: wide range (6000)
        for i in range(6):
            rows.append({"date": f"2026030{6-i}", "open": 50000, "high": 53000, "low": 47000, "close": 50200, "volume": 1000000})
        # Older 16 days: narrow range (2000)
        for i in range(16):
            rows.append({"date": f"2026021{16-i:02d}", "open": 50000, "high": 51000, "low": 49000, "close": 50500, "volume": 1000000})
        df = pd.DataFrame(rows)
        ratio = strategy.get_contraction_ratio(df)
        assert ratio is not None
        assert ratio > 1.5  # wide/narrow; ATR(5) >> ATR(20) since recent rows dominate

    def test_returns_none_for_insufficient_data(self, strategy):
        """데이터 부족 → None."""
        df = make_ohlc_dataframe(days=10)  # ATR(20) needs 21 rows
        ratio = strategy.get_contraction_ratio(df)
        assert ratio is None


# ── should_sell with ATR ──────────────────────────────────

class TestShouldSellWithATR:

    def test_atr_widens_stop_loss(self, strategy):
        """ATR 기반 SL이 고정 SL(-2%)보다 넓으면 ATR 사용."""
        # buy=100000, atr=5000, multiplier=1.0 → ATR SL = -5%
        # Fixed SL = -2%. ATR이 더 넓으므로 -5% 적용
        # price=96000 → profit_rate=-4% → 고정SL(-2%)에선 trigger, ATR SL(-5%)에선 아님
        result = strategy.should_sell(current_price=96000, buy_price=100000,
                                      current_time_str="1200", atr=5000)
        assert result is None  # -4% > -5%, 아직 안 잘림

    def test_atr_sl_triggers_at_threshold(self, strategy):
        """ATR SL 임계치 도달 시 매도."""
        # buy=100000, atr=5000, multiplier=1.0 → ATR SL = -5%
        result = strategy.should_sell(current_price=94500, buy_price=100000,
                                      current_time_str="1200", atr=5000)
        assert result == "SELL_STOP_LOSS"  # -5.5% <= -5%

    def test_fixed_sl_used_as_floor(self, strategy):
        """ATR SL이 고정 SL보다 좁으면 고정 SL 사용 (floor)."""
        # buy=100000, atr=500, multiplier=1.0 → ATR SL = -0.5%
        # Fixed SL = -2%. 고정이 더 넓으므로 -2% 적용
        result = strategy.should_sell(current_price=99000, buy_price=100000,
                                      current_time_str="1200", atr=500)
        assert result is None  # -1% > -2%, 안 잘림

    def test_atr_widens_take_profit(self, strategy):
        """ATR 기반 TP가 고정 TP(4%)보다 넓으면 ATR 사용."""
        # buy=100000, atr=5000, multiplier=2.0 → ATR TP = 10%
        # Fixed TP = 4%. ATR이 더 넓으므로 10% 적용
        # price=108000 → profit_rate=8% → 고정TP(4%)에선 trigger, ATR TP(10%)에선 아님
        result = strategy.should_sell(current_price=108000, buy_price=100000,
                                      current_time_str="1200", atr=5000)
        assert result is None  # 8% < 10%, 아직 TP 안 됨

    def test_no_atr_uses_fixed(self, strategy):
        """atr=None → 기존 고정 % 사용 (호환성)."""
        result = strategy.should_sell(current_price=97500, buy_price=100000,
                                      current_time_str="1200", atr=None)
        assert result == "SELL_STOP_LOSS"  # -2.5% <= -2%

    def test_atr_zero_uses_fixed(self, strategy):
        """atr=0 → 기존 고정 % 사용."""
        result = strategy.should_sell(current_price=97500, buy_price=100000,
                                      current_time_str="1200", atr=0)
        assert result == "SELL_STOP_LOSS"


# ── check_buy_signal contraction context ─────────────────

class TestCheckBuySignalContraction:

    def test_result_contains_contraction_keys(self, strategy, sample_ohlc):
        """결과 dict에 contraction_ratio와 atr14 키 포함."""
        result = strategy.check_buy_signal("005930", sample_ohlc, current_price=50000)
        assert result is not None
        assert "contraction_ratio" in result
        assert "atr14" in result

    def test_contraction_ratio_with_sufficient_data(self, strategy, sample_ohlc):
        """30일 데이터 → contraction_ratio 계산됨."""
        result = strategy.check_buy_signal("005930", sample_ohlc, current_price=50000)
        assert result["contraction_ratio"] is not None

    def test_atr14_with_sufficient_data(self, strategy, sample_ohlc):
        """30일 데이터 → atr14 계산됨."""
        result = strategy.check_buy_signal("005930", sample_ohlc, current_price=50000)
        assert result["atr14"] is not None
        assert result["atr14"] > 0

    def test_contraction_none_with_insufficient_data(self, strategy):
        """2일 데이터 → contraction_ratio = None (ATR20 불가)."""
        df = _two_row_df(50000, 52000, 48000)
        result = strategy.check_buy_signal("005930", df, current_price=53000)
        assert result is not None
        assert result["contraction_ratio"] is None


# ── apply_temperature ATR multipliers ────────────────────

class TestApplyTemperatureATR:

    PROFILES_WITH_ATR = {
        "HOT": {"k": 0.3, "take_profit": 5.0, "stop_loss": -2.0,
                "atr_sl_multiplier": 1.0, "atr_tp_multiplier": 2.5},
        "NEUTRAL": {"k": 0.5, "take_profit": 4.0, "stop_loss": -2.0},
    }

    def test_atr_multipliers_loaded_from_profile(self, strategy):
        """HOT 프로필에서 ATR 멀티플라이어 로드."""
        strategy.apply_temperature({"level": "HOT"}, self.PROFILES_WITH_ATR)
        assert strategy.atr_sl_multiplier == pytest.approx(1.0)
        assert strategy.atr_tp_multiplier == pytest.approx(2.5)

    def test_atr_multipliers_keep_defaults_when_absent(self, strategy):
        """프로필에 ATR 멀티플라이어 없으면 기본값 유지."""
        strategy.apply_temperature({"level": "NEUTRAL"}, self.PROFILES_WITH_ATR)
        assert strategy.atr_sl_multiplier == pytest.approx(1.0)   # default
        assert strategy.atr_tp_multiplier == pytest.approx(2.0)   # default
