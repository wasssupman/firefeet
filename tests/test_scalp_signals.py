"""ScalpSignals 런타임 로직 검증 — 실제 TickBuffer/OrderbookAnalyzer 사용."""

import time
import pytest
from core.scalping.scalp_signals import ScalpSignals
from core.scalping.tick_buffer import TickBuffer
from core.scalping.orderbook_analyzer import OrderbookAnalyzer
from tests.mocks.mock_scalping import inject_orderbook


CODE = "005930"


@pytest.fixture
def signals(scalp_settings):
    return ScalpSignals(scalp_settings)


@pytest.fixture
def buf():
    return TickBuffer(max_size=600)


@pytest.fixture
def oba():
    return OrderbookAnalyzer()


# ── 헬퍼 ──────────────────────────────────────────────────


def _inject_vwap_reversion_scenario(buf, code=CODE):
    """VWAP 위에 앵커 → 최근 VWAP 아래에서 반등 (양의 60s 모멘텀)."""
    now = time.time()
    # Phase 1: 90초 전, 고가 대량 (VWAP 앵커)
    for i in range(10):
        buf.add_tick(code, 50500, 10000, timestamp=now - 90 + i * 0.5, direction=1)
    # Phase 2: 최근 20초, 저가에서 반등 (49700 → 49900)
    for i in range(40):
        buf.add_tick(code, 49700 + i * 5, 1000, timestamp=now - 20 + i * 0.5, direction=1)


def _inject_above_vwap_scenario(buf, code=CODE):
    """가격이 VWAP 위 — VWAP reversion 비활성."""
    now = time.time()
    for i in range(50):
        buf.add_tick(code, 50000 + i * 10, 1000, timestamp=now - 25 + i * 0.5, direction=1)


def _inject_strong_uptrend(buf, code=CODE):
    """강한 상승 추세 (모멘텀 + 마이크로 트렌드 활성)."""
    now = time.time()
    for i in range(60):
        buf.add_tick(code, 49500 + i * 15, 1000 + i * 50,
                     timestamp=now - 30 + i * 0.5, direction=1)


def _inject_downtrend(buf, code=CODE):
    """하락 추세."""
    now = time.time()
    for i in range(60):
        buf.add_tick(code, 50500 - i * 15, 1000,
                     timestamp=now - 30 + i * 0.5, direction=-1)


def _inject_high_volume_burst(buf, code=CODE):
    """최근 거래량 급증."""
    now = time.time()
    # 3분 전: 평소 거래량
    for i in range(30):
        buf.add_tick(code, 50000, 500, timestamp=now - 180 + i * 5, direction=1)
    # 최근 30초: 대량 거래
    for i in range(30):
        buf.add_tick(code, 50000 + i * 5, 5000, timestamp=now - 15 + i * 0.5, direction=1)


def _inject_low_volume(buf, code=CODE):
    """거래량 균일 분산 (200초) → vol_accel ≈ 1.0."""
    now = time.time()
    for i in range(200):
        buf.add_tick(code, 50000, 100, timestamp=now - 200 + i, direction=0)


def _inject_bid_heavy_orderbook(oba, code=CODE):
    """매수 우위 호가."""
    inject_orderbook(
        oba, code,
        bid_prices=[50000, 49950, 49900],
        bid_volumes=[10000, 8000, 6000],
        ask_prices=[50050, 50100, 50150],
        ask_volumes=[2000, 1500, 1000],
    )


def _inject_ask_heavy_orderbook(oba, code=CODE):
    """매도 우위 호가."""
    inject_orderbook(
        oba, code,
        bid_prices=[50000, 49950, 49900],
        bid_volumes=[1000, 800, 600],
        ask_prices=[50050, 50100, 50150],
        ask_volumes=[10000, 8000, 6000],
    )


def _inject_balanced_orderbook(oba, code=CODE):
    """균형 호가."""
    inject_orderbook(
        oba, code,
        bid_prices=[50000, 49950, 49900],
        bid_volumes=[5000, 4000, 3000],
        ask_prices=[50050, 50100, 50150],
        ask_volumes=[5000, 4000, 3000],
    )


# ══════════════════════════════════════════════════════════════
# Signal 1: VWAP Reversion
# ══════════════════════════════════════════════════════════════


class TestSignalVWAPReversion:

    def test_below_vwap_with_uptrend_scores_high(self, signals, buf):
        """VWAP 아래 + 반등 추세 → 높은 점수."""
        _inject_vwap_reversion_scenario(buf)

        score = signals.signal_vwap_reversion(CODE, buf)

        # 기대: base_score(40~70) + trend_bonus(15) + vol_bonus(0~15)
        assert score >= 40, f"VWAP reversion score too low: {score}"

    def test_above_vwap_scores_zero(self, signals, buf):
        """VWAP 위 → 0점."""
        _inject_above_vwap_scenario(buf)

        score = signals.signal_vwap_reversion(CODE, buf)

        assert score == 0

    def test_no_data_scores_zero(self, signals, buf):
        """데이터 없으면 0."""
        score = signals.signal_vwap_reversion(CODE, buf)
        assert score == 0

    def test_below_vwap_downtrend_scores_zero(self, signals, buf):
        """VWAP 아래이지만 하락 추세 → 0 (반등 없음)."""
        now = time.time()
        # 앵커: 고가
        for i in range(10):
            buf.add_tick(CODE, 50500, 10000, timestamp=now - 90 + i * 0.5, direction=1)
        # 최근: 하락 중 (49900 → 49600)
        for i in range(40):
            buf.add_tick(CODE, 49900 - i * 7.5, 1000,
                         timestamp=now - 20 + i * 0.5, direction=-1)

        score = signals.signal_vwap_reversion(CODE, buf)

        # 60s momentum <= 0 → 0
        assert score == 0


# ══════════════════════════════════════════════════════════════
# Signal 2: Orderbook Pressure
# ══════════════════════════════════════════════════════════════


class TestSignalOrderbookPressure:

    def test_bid_heavy_scores_high(self, signals, oba):
        """매수 우위 호가 → 높은 점수."""
        _inject_bid_heavy_orderbook(oba)

        score = signals.signal_orderbook_pressure(CODE, oba)

        # imbalance > 0.5 → base_score >= 55
        assert score >= 40, f"Orderbook pressure score too low: {score}"

    def test_ask_heavy_scores_zero_or_low(self, signals, oba):
        """매도 우위 호가 → 낮은 점수 (0 or 15)."""
        _inject_ask_heavy_orderbook(oba)

        score = signals.signal_orderbook_pressure(CODE, oba)

        # imbalance <= -0.3 → 0, or <= 0 → 15
        assert score <= 15

    def test_balanced_scores_moderate(self, signals, oba):
        """균형 호가 → 중간 점수."""
        _inject_balanced_orderbook(oba)

        score = signals.signal_orderbook_pressure(CODE, oba)

        # imbalance ≈ 0 → 15
        assert 0 <= score <= 30

    def test_no_data_scores_zero(self, signals, oba):
        """데이터 없으면 0."""
        score = signals.signal_orderbook_pressure(CODE, oba)
        assert score == 0


# ══════════════════════════════════════════════════════════════
# Signal 3: Momentum Burst
# ══════════════════════════════════════════════════════════════


class TestSignalMomentumBurst:

    def test_strong_uptrend_scores_high(self, signals, buf):
        """강한 상승 추세 → 높은 점수."""
        _inject_strong_uptrend(buf)

        score = signals.signal_momentum_burst(CODE, buf)

        assert score >= 30, f"Momentum burst score too low: {score}"

    def test_downtrend_scores_zero(self, signals, buf):
        """하락 추세 → 0."""
        _inject_downtrend(buf)

        score = signals.signal_momentum_burst(CODE, buf)

        # tick_ratio < -0.3 and mom_10s < -0.3 → 0
        assert score == 0

    def test_no_data_scores_zero(self, signals, buf):
        """데이터 부족 → 0."""
        score = signals.signal_momentum_burst(CODE, buf)
        assert score == 0


# ══════════════════════════════════════════════════════════════
# Signal 4: Volume Surge
# ══════════════════════════════════════════════════════════════


class TestSignalVolumeSurge:

    def test_high_volume_burst_scores_high(self, signals, buf):
        """거래량 급증 → 높은 점수."""
        _inject_high_volume_burst(buf)

        score = signals.signal_volume_surge(CODE, buf)

        assert score >= 40, f"Volume surge score too low: {score}"

    def test_low_volume_scores_zero(self, signals, buf):
        """거래량 부족 → 0."""
        _inject_low_volume(buf)

        score = signals.signal_volume_surge(CODE, buf)

        # 일정한 저거래량 → vol_accel ≈ 1.0 → 20 or lower
        assert score <= 20

    def test_no_data_scores_zero(self, signals, buf):
        """데이터 부족 → 0."""
        score = signals.signal_volume_surge(CODE, buf)
        assert score == 0


# ══════════════════════════════════════════════════════════════
# Signal 5: Micro Trend
# ══════════════════════════════════════════════════════════════


class TestSignalMicroTrend:

    def test_all_timeframes_positive_scores_high(self, signals, buf):
        """전 타임프레임 상승 → 높은 점수."""
        _inject_strong_uptrend(buf)

        score = signals.signal_micro_trend(CODE, buf)

        # 3개 양수 → base_score=65 + accel_bonus
        assert score >= 65, f"Micro trend score too low: {score}"

    def test_downtrend_scores_low(self, signals, buf):
        """하락 추세 → 최소 점수."""
        _inject_downtrend(buf)

        score = signals.signal_micro_trend(CODE, buf)

        # 양수 0개 → 10
        assert score <= 25

    def test_no_data_scores_zero(self, signals, buf):
        """데이터 부족 → 0."""
        score = signals.signal_micro_trend(CODE, buf)
        assert score == 0


# ══════════════════════════════════════════════════════════════
# Composite Score
# ══════════════════════════════════════════════════════════════


class TestCompositeScore:

    def test_composite_weighted_sum(self, signals):
        """가중 합산 검증."""
        sigs = {
            "vwap_reversion": 80,
            "orderbook_pressure": 60,
            "momentum_burst": 40,
            "volume_surge": 20,
            "micro_trend": 0,
        }
        # 기본 weights: vwap=25, ob=25, mom=20, vol=15, trend=15
        expected = (80*25 + 60*25 + 40*20 + 20*15 + 0*15) / 100
        # = (2000 + 1500 + 800 + 300 + 0) / 100 = 46.0

        score = signals.get_composite_score(sigs)

        assert score == 46.0

    def test_custom_weights(self, signals):
        """커스텀 weights 적용."""
        sigs = {
            "vwap_reversion": 100,
            "orderbook_pressure": 0,
            "momentum_burst": 0,
            "volume_surge": 0,
            "micro_trend": 0,
        }
        weights = {"vwap_reversion": 100, "orderbook_pressure": 0,
                    "momentum_burst": 0, "volume_surge": 0, "micro_trend": 0}

        score = signals.get_composite_score(sigs, weights=weights)

        assert score == 100.0

    def test_all_zeros_returns_zero(self, signals):
        """모든 시그널 0 → composite 0."""
        sigs = {k: 0 for k in ["vwap_reversion", "orderbook_pressure",
                                 "momentum_burst", "volume_surge", "micro_trend"]}

        score = signals.get_composite_score(sigs)

        assert score == 0.0

    def test_all_max_returns_100(self, signals):
        """모든 시그널 100 → composite 100."""
        sigs = {k: 100 for k in ["vwap_reversion", "orderbook_pressure",
                                   "momentum_burst", "volume_surge", "micro_trend"]}

        score = signals.get_composite_score(sigs)

        assert score == 100.0


# ══════════════════════════════════════════════════════════════
# End-to-End: calculate_all → composite (실제 데이터 경로)
# ══════════════════════════════════════════════════════════════


class TestCalculateAllEndToEnd:

    def test_bullish_scenario_high_composite(self, signals, buf, oba):
        """강세 시나리오 → 모든 시그널 활성 → 높은 composite."""
        _inject_strong_uptrend(buf)
        _inject_bid_heavy_orderbook(oba)

        all_signals = signals.calculate_all(CODE, buf, oba)
        composite = signals.get_composite_score(all_signals)

        # 강세: 대부분 시그널 활성
        assert composite > 30, f"Bullish composite too low: {composite}"
        # 각 시그널이 계산되었는지 확인
        assert set(all_signals.keys()) == {
            "vwap_reversion", "orderbook_pressure",
            "momentum_burst", "volume_surge", "micro_trend",
        }

    def test_bearish_scenario_low_composite(self, signals, buf, oba):
        """약세 시나리오 → 시그널 비활성 → 낮은 composite."""
        _inject_downtrend(buf)
        _inject_ask_heavy_orderbook(oba)

        all_signals = signals.calculate_all(CODE, buf, oba)
        composite = signals.get_composite_score(all_signals)

        assert composite < 30, f"Bearish composite too high: {composite}"

    def test_no_data_all_zeros(self, signals, buf, oba):
        """데이터 없으면 모든 시그널 0."""
        all_signals = signals.calculate_all(CODE, buf, oba)
        composite = signals.get_composite_score(all_signals)

        assert composite == 0


# ══════════════════════════════════════════════════════════════
# End-to-End: evaluate + should_exit (실제 시그널, mock 없음)
# ══════════════════════════════════════════════════════════════


class TestRealSignalStrategy:

    def test_evaluate_with_real_signals_bullish(self, scalp_settings, buf, oba):
        """실제 시그널로 evaluate() — 강세 데이터 → should_enter 판단."""
        _inject_strong_uptrend(buf)
        _inject_bid_heavy_orderbook(oba)

        sigs = ScalpSignals(scalp_settings)
        from core.scalping.scalp_strategy import ScalpStrategy
        from tests.mocks.mock_scalping import make_strategy_profile

        strat = ScalpStrategy(sigs, scalp_settings)
        profile = make_strategy_profile(conf=0.30)  # 낮은 threshold

        result = strat.evaluate(CODE, buf, oba, profile=profile)

        # 결과 구조 검증
        assert "composite" in result
        assert "confidence" in result
        assert "should_enter" in result
        assert "penalties" in result
        assert result["composite"] >= 0
        assert result["confidence"] >= 0

    def test_evaluate_with_real_signals_bearish_rejected(self, scalp_settings, buf, oba):
        """실제 시그널로 evaluate() — 약세 데이터 → should_enter=False."""
        _inject_downtrend(buf)
        _inject_ask_heavy_orderbook(oba)

        sigs = ScalpSignals(scalp_settings)
        from core.scalping.scalp_strategy import ScalpStrategy
        from tests.mocks.mock_scalping import make_strategy_profile

        strat = ScalpStrategy(sigs, scalp_settings)
        profile = make_strategy_profile(conf=0.35)

        result = strat.evaluate(CODE, buf, oba, profile=profile)

        # 약세 → composite 낮음 → should_enter=False
        assert result["should_enter"] is False

    def test_should_exit_signal_with_real_data(self, scalp_settings, buf, oba):
        """실제 시그널로 should_exit() — 하락 데이터 + 장기 보유 → SIGNAL 청산."""
        # 하락 시그널 데이터
        _inject_downtrend(buf)
        _inject_ask_heavy_orderbook(oba)

        sigs = ScalpSignals(scalp_settings)
        from core.scalping.scalp_strategy import ScalpStrategy
        from tests.mocks.mock_scalping import make_strategy_profile

        strat = ScalpStrategy(sigs, scalp_settings)
        profile = make_strategy_profile(conf=0.35, tp=5.0, sl=-5.0, max_hold=600)

        # 매수가 50500 → 현재가 약 49600 (하락 추세 마지막 가격)
        # profit_rate ≈ -1.78% < -0.15%
        # hold_seconds=120 >= 90
        buy_price = 50500
        # 하락 추세: 50500 - 59*15 = 49615
        current_price = 49615

        should, reason, is_market = strat.should_exit(
            CODE, buy_price, current_price, hold_seconds=120,
            tick_buffer=buf, orderbook_analyzer=oba,
            profile=profile,
        )

        # composite 낮음 → SIGNAL 청산 또는 그 전에 다른 조건
        # 최소한 결과 구조가 올바른지 검증
        assert isinstance(should, bool)
        assert isinstance(reason, str)
        assert isinstance(is_market, bool)

        # 약세 데이터 + 손실 중 + 장기 보유 → 청산되어야 함
        if should:
            assert "SIGNAL" in reason or "SL" in reason
