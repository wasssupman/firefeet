"""ScalpStrategy 유닛 테스트 — evaluate() + should_exit() + apply_temperature()."""

import pytest
from unittest.mock import MagicMock, patch
from core.scalping.scalp_strategy import ScalpStrategy
from core.scalping.scalp_signals import ScalpSignals
from core.scalping.tick_buffer import TickBuffer
from core.scalping.orderbook_analyzer import OrderbookAnalyzer
from tests.mocks.mock_scalping import (
    make_strategy_profile, make_ta_overlay,
    inject_ticks, inject_orderbook,
    make_tick_buffer_with_data, make_orderbook_with_data,
)


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def strategy(scalp_settings):
    signals = ScalpSignals(scalp_settings)
    return ScalpStrategy(signals, scalp_settings)


@pytest.fixture
def mock_signals():
    """제어 가능한 ScalpSignals mock."""
    sig = MagicMock(spec=ScalpSignals)
    sig.calculate_all.return_value = {
        "vwap_reversion": 50,
        "orderbook_pressure": 50,
        "momentum_burst": 50,
        "volume_surge": 50,
        "micro_trend": 50,
    }
    sig.get_composite_score.return_value = 50.0
    return sig


@pytest.fixture
def mock_strategy(scalp_settings, mock_signals):
    """mock signals를 쓰는 ScalpStrategy."""
    strat = ScalpStrategy(mock_signals, scalp_settings)
    return strat


@pytest.fixture
def tb():
    """데이터가 채워진 TickBuffer (vol_accel 통과)."""
    return make_tick_buffer_with_data("005930", n=50, base_price=50000)


@pytest.fixture
def oba():
    """spread 10bps, 매수 우위 OrderbookAnalyzer."""
    return make_orderbook_with_data("005930", spread_bps=10, imbalance=0.3)


# ══════════════════════════════════════════════════════════════
# evaluate() 테스트
# ══════════════════════════════════════════════════════════════


class TestEvaluateEntry:

    def test_enter_with_profile_threshold(self, mock_strategy, tb, oba):
        """profile.conf=0.35, global=0.40 -> max(0.35,0.40)=0.40 사용."""
        mock_strategy.signals.get_composite_score.return_value = 40.0
        profile = make_strategy_profile(conf=0.35)

        result = mock_strategy.evaluate("005930", tb, oba, profile=profile)

        assert result["should_enter"] is True
        assert result["threshold"] == 0.40  # max(profile=0.35, global=0.40)
        assert result["confidence"] == 0.40

    def test_enter_without_profile_uses_global(self, mock_strategy, tb, oba):
        """profile=None -> 글로벌 threshold(0.40) 사용."""
        mock_strategy.signals.get_composite_score.return_value = 45.0
        mock_strategy.confidence_threshold = 0.40

        result = mock_strategy.evaluate("005930", tb, oba, profile=None)

        assert result["should_enter"] is True
        assert result["threshold"] == 0.40

    def test_threshold_uses_max_of_profile_and_global(self, mock_strategy, tb, oba):
        """profile.conf=0.22, global=0.40 -> max(0.22,0.40)=0.40 사용."""
        mock_strategy.signals.get_composite_score.return_value = 30.0
        mock_strategy.confidence_threshold = 0.40
        profile = make_strategy_profile(conf=0.22)

        result = mock_strategy.evaluate("005930", tb, oba, profile=profile)

        assert result["threshold"] == 0.40  # max(profile=0.22, global=0.40)
        assert result["should_enter"] is False  # 0.30 < 0.40

    def test_penalty_veto_blocks_entry(self, mock_strategy, oba):
        """combined_penalty < 0.5 -> should_enter=False (극단 스프레드)."""
        mock_strategy.signals.get_composite_score.return_value = 80.0

        # 스프레드 100bps -> spread_penalty=0.60
        # vol_accel 0.3 -> volume_penalty=0.65
        # combined = min(0.60, 0.65) = 0.60 >= 0.5 -> NO veto
        # 스프레드 100bps + vol_accel < 0.4 -> 0.60 and 0.65 -> min=0.60 >= 0.5
        # We need combined < 0.5. Only way: both extreme (which gives 0.60 min).
        # Actually looking at the code: spread > 80 -> 0.60, vol < 0.4 -> 0.65
        # combined = min(0.60, 0.65) = 0.60 which is >= 0.5
        # Penalty veto only fires if combined < 0.5
        # With current penalty functions, min is 0.60 (spread) or 0.65 (vol)
        # So combined can only be as low as 0.60 with real data.
        # We need to directly set penalty behavior. Let me use a different approach.

        # Mock _spread_penalty and _volume_penalty to return extreme values
        mock_strategy._spread_penalty = MagicMock(return_value=0.40)
        mock_strategy._volume_penalty = MagicMock(return_value=0.30)
        profile = make_strategy_profile(conf=0.10)

        result = mock_strategy.evaluate("005930", make_tick_buffer_with_data(), oba, profile=profile)

        assert result["should_enter"] is False
        assert result["penalties"]["combined"] == 0.3

    def test_low_confidence_rejected(self, mock_strategy, tb, oba):
        """composite=20, threshold=0.35 -> confidence=0.20 < 0.35 -> rejected."""
        mock_strategy.signals.get_composite_score.return_value = 20.0
        profile = make_strategy_profile(conf=0.35)

        result = mock_strategy.evaluate("005930", tb, oba, profile=profile)

        assert result["should_enter"] is False
        assert result["confidence"] == 0.20

    def test_mode_from_profile(self, mock_strategy, tb, oba):
        """profile 있으면 mode = profile.name."""
        mock_strategy.signals.get_composite_score.return_value = 50.0
        profile = make_strategy_profile(name="orb", conf=0.30)

        result = mock_strategy.evaluate("005930", tb, oba, profile=profile)

        assert result["mode"] == "orb"

    def test_tp_sl_from_profile(self, mock_strategy, tb, oba):
        """profile의 TP/SL이 결과에 반영."""
        mock_strategy.signals.get_composite_score.return_value = 50.0
        profile = make_strategy_profile(tp=1.5, sl=-0.7, conf=0.30)

        result = mock_strategy.evaluate("005930", tb, oba, profile=profile)

        assert result["take_profit"] == 1.5
        assert result["stop_loss"] == -0.7

    def test_ta_overlay_adjusts_tp_sl(self, mock_strategy, tb, oba):
        """TAOverlay가 TP/SL 조절."""
        mock_strategy.signals.get_composite_score.return_value = 50.0
        profile = make_strategy_profile(tp=1.2, sl=-0.5, conf=0.30)
        # suggested_tp=0.8 < base_tp=1.2 -> tp=0.8
        # bb_position=0.5 < bb_exit_threshold=0.8 -> no BB multiplier
        overlay = make_ta_overlay(suggested_tp=0.8, bb_position=0.5)

        result = mock_strategy.evaluate("005930", tb, oba, profile=profile, ta_overlay=overlay)

        assert result["take_profit"] == 0.8


# ══════════════════════════════════════════════════════════════
# should_exit() 테스트
# ══════════════════════════════════════════════════════════════


class TestShouldExit:

    def test_sl_exit(self, mock_strategy, tb, oba):
        """profit=-0.6%, sl=-0.5% -> (True, 'SCALP_SELL_SL', market=True)."""
        buy_price = 50000
        current_price = 49700  # -0.6%

        should, reason, is_market = mock_strategy.should_exit(
            "005930", buy_price, current_price, hold_seconds=60,
            tick_buffer=tb, orderbook_analyzer=oba,
            profile=make_strategy_profile(sl=-0.5),
        )

        assert should is True
        assert "SCALP_SELL_SL" in reason
        assert is_market is True

    def test_tp_exit(self, mock_strategy, tb, oba):
        """profit=+1.3%, tp=1.2% -> (True, 'SCALP_SELL_TP', market=False)."""
        buy_price = 50000
        current_price = 50650  # +1.3%

        should, reason, is_market = mock_strategy.should_exit(
            "005930", buy_price, current_price, hold_seconds=60,
            tick_buffer=tb, orderbook_analyzer=oba,
            profile=make_strategy_profile(tp=1.2),
        )

        assert should is True
        assert "SCALP_SELL_TP" in reason
        assert is_market is False

    def test_timeout_exit(self, mock_strategy, tb, oba):
        """hold=200s, max=180 -> (True, 'SCALP_SELL_TIMEOUT')."""
        should, reason, is_market = mock_strategy.should_exit(
            "005930", 50000, 50000, hold_seconds=200,
            tick_buffer=tb, orderbook_analyzer=oba,
            profile=make_strategy_profile(max_hold=180),
        )

        assert should is True
        assert "SCALP_SELL_TIMEOUT" in reason

    def test_signal_exit_disabled(self, mock_strategy, tb, oba):
        """exit_threshold_ratio=0.0 -> SIGNAL 청산 비활성화 (구조결함 수정)."""
        # 기존에 SIGNAL 발동하던 조건: composite 5.0, hold=120s, loss=-0.2%
        mock_strategy.signals.get_composite_score.return_value = 5.0
        buy_price = 50000
        current_price = 49900  # -0.2%

        should, reason, _ = mock_strategy.should_exit(
            "005930", buy_price, current_price, hold_seconds=120,
            tick_buffer=tb, orderbook_analyzer=oba,
            profile=make_strategy_profile(conf=0.35, tp=5.0, sl=-5.0, max_hold=300),
        )

        # exit_threshold_ratio=0.0 -> exit_threshold=0 -> composite/100 < 0 불가 -> 비활성화
        assert should is False

    def test_signal_exit_requires_min_hold(self, mock_strategy, tb, oba):
        """hold=30s < min_hold=90s -> SIGNAL 청산 발동 안 됨 (비활성화 상태에서도 동일)."""
        mock_strategy.signals.get_composite_score.return_value = 5.0
        buy_price = 50000
        current_price = 49900  # -0.2%

        should, reason, _ = mock_strategy.should_exit(
            "005930", buy_price, current_price, hold_seconds=30,
            tick_buffer=tb, orderbook_analyzer=oba,
            profile=make_strategy_profile(conf=0.35, tp=5.0, sl=-5.0, max_hold=300),
        )

        # SL/TP/TIMEOUT 안 걸리고, SIGNAL도 비활성화
        assert should is False

    def test_bb_exit(self, mock_strategy, tb, oba):
        """profit>0.25%, bb>0.9 -> (True, 'SCALP_SELL_BB')."""
        buy_price = 50000
        current_price = 50200  # +0.4%
        overlay = make_ta_overlay(bb_position=0.95)

        should, reason, is_market = mock_strategy.should_exit(
            "005930", buy_price, current_price, hold_seconds=60,
            tick_buffer=tb, orderbook_analyzer=oba,
            profile=make_strategy_profile(tp=5.0, sl=-5.0, max_hold=300),
            ta_overlay=overlay,
        )

        assert should is True
        assert "SCALP_SELL_BB" in reason
        assert is_market is False

    def test_no_exit_buy_price_zero(self, mock_strategy, tb, oba):
        """buy_price=0 -> (False, '', False)."""
        should, reason, is_market = mock_strategy.should_exit(
            "005930", 0, 50000, hold_seconds=60,
            tick_buffer=tb, orderbook_analyzer=oba,
        )

        assert should is False
        assert reason == ""

    def test_resistance_exit(self, mock_strategy, tb, oba):
        """profit>0.25%, resistance 근접 -> SCALP_SELL_RESISTANCE."""
        buy_price = 50000
        current_price = 50200  # +0.4%
        overlay = make_ta_overlay(
            nearest_resistance=50250,
            resistance_distance_pct=0.03,  # < 0.05
            bb_position=0.5,  # BB exit 안 걸리게
        )

        should, reason, _ = mock_strategy.should_exit(
            "005930", buy_price, current_price, hold_seconds=60,
            tick_buffer=tb, orderbook_analyzer=oba,
            profile=make_strategy_profile(tp=5.0, sl=-5.0, max_hold=300),
            ta_overlay=overlay,
        )

        assert should is True
        assert "RESISTANCE" in reason


# ══════════════════════════════════════════════════════════════
# apply_temperature() 테스트
# ══════════════════════════════════════════════════════════════


class TestApplyTemperature:

    def test_temperature_updates_threshold(self, scalp_settings):
        """HOT -> threshold=0.35 (from scalping_rules.yaml)."""
        signals = ScalpSignals(scalp_settings)
        strat = ScalpStrategy(signals, scalp_settings)
        old_threshold = strat.confidence_threshold

        strat.apply_temperature({"temperature": 80, "level": "HOT"})

        assert strat.confidence_threshold == 0.35
        assert strat.temperature_level == "HOT"

    def test_cold_temperature_raises_threshold(self, scalp_settings):
        """COLD -> threshold=0.50."""
        signals = ScalpSignals(scalp_settings)
        strat = ScalpStrategy(signals, scalp_settings)

        strat.apply_temperature({"temperature": -70, "level": "COLD"})

        assert strat.confidence_threshold == 0.50
        assert strat.temperature_level == "COLD"

    def test_profile_overrides_temperature(self, scalp_settings):
        """temp=NEUTRAL(0.40) + profile.conf=0.35 -> evaluate시 0.35 사용."""
        mock_signals = MagicMock(spec=ScalpSignals)
        mock_signals.calculate_all.return_value = {
            "vwap_reversion": 50, "orderbook_pressure": 50,
            "momentum_burst": 50, "volume_surge": 50, "micro_trend": 50,
        }
        mock_signals.get_composite_score.return_value = 38.0

        strat = ScalpStrategy(mock_signals, scalp_settings)
        strat.apply_temperature({"temperature": 0, "level": "NEUTRAL"})

        # NEUTRAL -> confidence_threshold=0.40
        assert strat.confidence_threshold == 0.40

        # profile.conf=0.35 vs global=0.40 -> max=0.40
        profile = make_strategy_profile(conf=0.35)
        tb = make_tick_buffer_with_data()
        oba = make_orderbook_with_data()
        result = strat.evaluate("005930", tb, oba, profile=profile)

        # threshold=max(0.35, 0.40)=0.40, confidence=0.38 < 0.40 -> rejected
        assert result["threshold"] == 0.40
        assert result["should_enter"] is False

    def test_temperature_updates_mode(self, scalp_settings):
        """HOT -> mode=aggressive."""
        signals = ScalpSignals(scalp_settings)
        strat = ScalpStrategy(signals, scalp_settings)

        strat.apply_temperature({"temperature": 80, "level": "HOT"})

        assert strat.mode == "aggressive"

    def test_temperature_updates_tp_sl(self, scalp_settings):
        """HOT -> take_profit_pct=2.0, stop_loss_pct=-0.8."""
        signals = ScalpSignals(scalp_settings)
        strat = ScalpStrategy(signals, scalp_settings)

        strat.apply_temperature({"temperature": 80, "level": "HOT"})

        assert strat.aggressive_tp == 2.0
        assert strat.aggressive_sl == -0.8


# ══════════════════════════════════════════════════════════════
# SIGNAL 청산 비활성화 회귀 테스트 (exit_threshold_ratio=0.0)
# Task #2: config/scalping_settings.yaml exit_threshold_ratio=0.0
#          → composite/100 < 0 불가 → SIGNAL 청산 완전 비활성화
# ══════════════════════════════════════════════════════════════


class TestSignalExitDisabledRegression:
    """SIGNAL 청산 비활성화 회귀 테스트.

    exit_threshold_ratio=0.0 설정 시 어떤 composite 값에서도
    SIGNAL 청산이 발동하지 않아야 한다. 이 기능은 Task #1 분석에서
    SIGNAL 청산이 13건 전패(-92K)로 가장 나쁜 청산 방식이었기 때문에
    비활성화되었다.
    """

    def test_signal_exit_never_fires_with_ratio_zero(self, mock_strategy, tb, oba):
        """exit_threshold_ratio=0.0 → composite=0이어도 SIGNAL 청산 발동 안 됨."""
        # composite=0 → exit_threshold = entry_threshold * 0.0 = 0
        # composite/100 = 0.0 < 0 → False → SIGNAL 청산 없음
        mock_strategy.signals.get_composite_score.return_value = 0.0
        buy_price = 50000
        current_price = 49900  # -0.2% 손실

        should, reason, _ = mock_strategy.should_exit(
            "005930", buy_price, current_price, hold_seconds=120,
            tick_buffer=tb, orderbook_analyzer=oba,
            profile=make_strategy_profile(tp=5.0, sl=-5.0, max_hold=300),
        )

        assert should is False, "SIGNAL 청산이 비활성화됐는데 발동됨"
        assert "SIGNAL" not in reason

    def test_signal_exit_never_fires_regardless_of_composite(self, mock_strategy, tb, oba):
        """composite가 0~100 어떤 값이어도 SIGNAL 청산 없음."""
        buy_price = 50000
        current_price = 49900  # -0.2% 손실
        profile = make_strategy_profile(tp=5.0, sl=-5.0, max_hold=300)

        for composite_val in [0.0, 5.0, 10.0, 20.0, 30.0, 50.0]:
            mock_strategy.signals.get_composite_score.return_value = composite_val

            should, reason, _ = mock_strategy.should_exit(
                "005930", buy_price, current_price, hold_seconds=120,
                tick_buffer=tb, orderbook_analyzer=oba,
                profile=profile,
            )

            assert should is False, f"composite={composite_val}에서 SIGNAL 청산 발동"

    def test_signal_exit_condition_hold_seconds_not_met(self, mock_strategy, tb, oba):
        """hold_seconds < sig_min_hold(90) → SIGNAL 조건 자체 미충족."""
        mock_strategy.signals.get_composite_score.return_value = 0.0
        buy_price = 50000
        current_price = 49900

        should, reason, _ = mock_strategy.should_exit(
            "005930", buy_price, current_price, hold_seconds=89,
            tick_buffer=tb, orderbook_analyzer=oba,
            profile=make_strategy_profile(tp=5.0, sl=-5.0, max_hold=300),
        )

        assert should is False
        assert "SIGNAL" not in reason

    def test_signal_exit_profit_loss_condition_not_met(self, mock_strategy, tb, oba):
        """profit_rate > sig_min_loss(-0.15%) → SIGNAL 조건 미충족."""
        mock_strategy.signals.get_composite_score.return_value = 0.0
        buy_price = 50000
        current_price = 50100  # +0.2% 수익 중 → 손실 조건 미충족

        should, reason, _ = mock_strategy.should_exit(
            "005930", buy_price, current_price, hold_seconds=120,
            tick_buffer=tb, orderbook_analyzer=oba,
            profile=make_strategy_profile(tp=5.0, sl=-5.0, max_hold=300),
        )

        assert should is False

    def test_other_exits_still_work_when_signal_disabled(self, mock_strategy, tb, oba):
        """SIGNAL 청산이 비활성화돼도 SL/TP/TIMEOUT은 정상 작동."""
        # SL 테스트: -0.6% 손실 → SL(-0.5%) 발동
        mock_strategy.signals.get_composite_score.return_value = 0.0
        buy_price = 50000
        sl_price = 49700  # -0.6%

        should_sl, reason_sl, _ = mock_strategy.should_exit(
            "005930", buy_price, sl_price, hold_seconds=30,
            tick_buffer=tb, orderbook_analyzer=oba,
            profile=make_strategy_profile(tp=5.0, sl=-0.5, max_hold=300),
        )
        assert should_sl is True
        assert "SL" in reason_sl

        # TP 테스트: +1.3% 수익 → TP(1.2%) 발동
        tp_price = 50650  # +1.3%
        should_tp, reason_tp, _ = mock_strategy.should_exit(
            "005930", buy_price, tp_price, hold_seconds=30,
            tick_buffer=tb, orderbook_analyzer=oba,
            profile=make_strategy_profile(tp=1.2, sl=-5.0, max_hold=300),
        )
        assert should_tp is True
        assert "TP" in reason_tp


# ══════════════════════════════════════════════════════════════
# 온도 전환 경계 테스트
# Task #1 분석: HOT→COLD 전환 시 파라미터 일관성 검증
# ══════════════════════════════════════════════════════════════


class TestTemperatureTransitions:
    """온도 전환 시 threshold 파라미터 일관성 검증."""

    def test_hot_to_cold_transition_raises_threshold(self, scalp_settings):
        """HOT(threshold=0.35) → COLD(threshold=0.50) 전환 시
        threshold가 올바르게 상향 조정됨."""
        signals = ScalpSignals(scalp_settings)
        strat = ScalpStrategy(signals, scalp_settings)

        strat.apply_temperature({"temperature": 80, "level": "HOT"})
        assert strat.confidence_threshold == 0.35

        strat.apply_temperature({"temperature": -80, "level": "COLD"})
        assert strat.confidence_threshold == 0.50
        assert strat.confidence_threshold > 0.35, "COLD가 HOT보다 threshold 높아야 함"

    def test_cold_to_hot_transition_lowers_threshold(self, scalp_settings):
        """COLD(threshold=0.50) → HOT(threshold=0.35) 전환 시
        threshold가 낮아짐."""
        signals = ScalpSignals(scalp_settings)
        strat = ScalpStrategy(signals, scalp_settings)

        strat.apply_temperature({"temperature": -80, "level": "COLD"})
        assert strat.confidence_threshold == 0.50

        strat.apply_temperature({"temperature": 80, "level": "HOT"})
        assert strat.confidence_threshold == 0.35
        assert strat.confidence_threshold < 0.50

    def test_temperature_threshold_monotonic_hot_to_cold(self, scalp_settings):
        """온도 레벨 HOT→WARM→NEUTRAL→COOL→COLD 순으로
        threshold가 단조 증가(또는 유지)."""
        signals = ScalpSignals(scalp_settings)
        strat = ScalpStrategy(signals, scalp_settings)

        levels = [
            ("HOT", 80),
            ("WARM", 50),
            ("NEUTRAL", 0),
            ("COOL", -40),
            ("COLD", -80),
        ]
        thresholds = []
        for level, temp in levels:
            strat.apply_temperature({"temperature": temp, "level": level})
            thresholds.append(strat.confidence_threshold)

        for i in range(1, len(thresholds)):
            assert thresholds[i] >= thresholds[i - 1], (
                f"온도 {levels[i][0]}: threshold={thresholds[i]}가 "
                f"{levels[i-1][0]}: {thresholds[i-1]}보다 낮음 (단조증가 실패)"
            )

    def test_max_logic_cold_temperature_overrides_low_profile_threshold(
        self, scalp_settings
    ):
        """COLD 온도(0.50)에서 낮은 profile.conf(0.30) 설정 시
        max(0.30, 0.50) = 0.50이 실제 threshold로 사용됨.
        → composite=0.45 < 0.50 → should_enter=False."""
        mock_signals = MagicMock(spec=ScalpSignals)
        mock_signals.calculate_all.return_value = {
            "vwap_reversion": 45, "orderbook_pressure": 45,
            "momentum_burst": 45, "volume_surge": 45, "micro_trend": 45,
        }
        mock_signals.get_composite_score.return_value = 45.0

        strat = ScalpStrategy(mock_signals, scalp_settings)
        strat.apply_temperature({"temperature": -80, "level": "COLD"})
        assert strat.confidence_threshold == 0.50

        profile = make_strategy_profile(conf=0.30)  # 낮은 profile threshold
        tb = make_tick_buffer_with_data()
        oba = make_orderbook_with_data()
        result = strat.evaluate("005930", tb, oba, profile=profile)

        # max(0.30, 0.50) = 0.50, confidence=0.45 < 0.50 → 거부
        assert result["threshold"] == 0.50
        assert result["should_enter"] is False

    def test_warm_temperature_mode_is_aggressive(self, scalp_settings):
        """WARM → mode='aggressive' (scalping_rules.yaml 기반)."""
        signals = ScalpSignals(scalp_settings)
        strat = ScalpStrategy(signals, scalp_settings)

        strat.apply_temperature({"temperature": 50, "level": "WARM"})

        assert strat.mode == "aggressive"

    def test_cool_temperature_mode_is_micro_swing(self, scalp_settings):
        """COOL → mode='micro_swing' (scalping_rules.yaml 기반)."""
        signals = ScalpSignals(scalp_settings)
        strat = ScalpStrategy(signals, scalp_settings)

        strat.apply_temperature({"temperature": -40, "level": "COOL"})

        assert strat.mode == "micro_swing"
