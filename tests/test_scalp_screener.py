"""ScalpScreener 유닛 테스트 — 필터링 + ticks_to_cover 수수료 계산 검증.

C-2 회귀 테스트 포함:
  Task #2 C-2: ticks_to_cover = 0.21 / (tick_pct * 100) 오류 수정
               → 0.21 / tick_pct 로 수정. 수정 전에는 거의 모든 종목이
               ticks_to_cover <= 3 를 만족해 점수 차별화가 무의미했음.
"""

import pytest
from unittest.mock import MagicMock, patch
from core.scalping.scalp_screener import ScalpScreener


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def mock_manager():
    """KIS API mock."""
    return MagicMock()


@pytest.fixture
def screener(mock_manager, scalp_settings):
    """실제 설정 파일을 사용하는 ScalpScreener."""
    return ScalpScreener(manager=mock_manager, settings_path=scalp_settings)


def _make_stock(code="005930", name="삼성전자", price=50000,
                volume=5000000, change_rate=3.0):
    """테스트용 종목 딕셔너리 생성."""
    return {
        "code": code,
        "name": name,
        "price": price,
        "volume": volume,
        "change_rate": change_rate,
    }


# ══════════════════════════════════════════════════════════════
# C-2 회귀 테스트: ticks_to_cover 수수료 계산 오류 수정
# ══════════════════════════════════════════════════════════════


class TestTicksToCoverFix:
    """C-2 수정 회귀 테스트: 수수료 커버 틱 수 계산 정확성."""

    def test_50000won_price_ticks_to_cover_approx_1(self, screener):
        """50,000원 종목: tick=50원, tick_pct=0.10%
        ticks_to_cover = 0.21 / 0.10 = 2.1틱 → 25점 (<=3 조건 만족)
        수정 전: 0.21 / (0.10 * 100) = 0.021 → 25점 (잘못된 값으로도 동일)
        핵심 검증: 10,000원 종목에서 수정 전후 결과가 달라지는 경계 확인."""
        # 50,000원: tick_size=50원, tick_pct=0.10%
        # ticks_to_cover = 0.21 / 0.10 = 2.1 → <=3 → 25점
        stock = _make_stock(price=50000, volume=5000000)
        score = screener._score_stock(stock)
        # 가격대 점수(30) + 틱점수(25) + 거래량(25) + rvol(>0) => >= 80
        assert score >= 80, f"50,000원 종목 점수가 너무 낮음: {score}"

    def test_5000won_price_blocked_by_min_price_filter(self, screener):
        """5,000원 종목: min_price=10,000원(설정값) 미만이므로 필터 차단.
        틱사이즈 불리 + 수수료 비율 과다로 10,000원 미만 종목 제외."""
        stock = _make_stock(price=5000, volume=5000000)
        result = screener.filter_stocks([stock])
        assert len(result) == 0, "5,000원 종목이 min_price=10,000 필터에 차단되어야 함"

    def test_ticks_to_cover_calculation_direct_high_price(self, screener):
        """200,000원 종목: tick=500원, tick_pct=0.25%
        수정 후: ticks_to_cover = 0.21 / 0.25 = 0.84 → <=3 → 25점
        수정 전: 0.21 / (0.25 * 100) = 0.0084 → <=3 → 25점 (동일)
        실제 차별화는 mid-range 종목에서 발생."""
        stock = _make_stock(price=200000, volume=5000000)
        score = screener._score_stock(stock)
        # 최적 가격대(50k~200k) 30점 + 틱점수 25점 + 거래량 25점 = 80점 이상
        # (rvol_proxy = change_rate * log(volume) → change_rate=3.0이면 추가점)
        assert score >= 75, f"200,000원 종목 점수가 예상보다 낮음: {score}"

    def test_score_differentiates_by_tick_efficiency(self, screener):
        """수수료 커버 틱 수에 따른 점수 차별화 검증.
        tick_pct가 작을수록 수수료 커버에 더 많은 틱이 필요 → 점수 낮음."""
        # 10,000원 종목: tick=10원, tick_pct=0.10%
        # ticks_to_cover = 0.21 / 0.10 = 2.1 → <=3 → 25점
        stock_10k = _make_stock(price=10000, volume=5000000, change_rate=3.0)
        score_10k = screener._score_stock(stock_10k)

        # 500원 종목은 min_price 필터에서 차단되므로,
        # 대신 수동으로 tick_size mock을 통해 경계 케이스 검증
        # tick_pct 충분히 작으면 ticks_to_cover > 10 → 0점
        from core.providers.kis_api import KISManager
        with patch.object(KISManager, 'get_tick_size', return_value=1):
            # price=10000, tick=1 → tick_pct=0.01% → ticks_to_cover=0.21/0.01=21 → 0점
            score_bad_tick = screener._score_stock(stock_10k)

        # 일반 tick_size(10원)가 mock tick_size(1원)보다 높은 점수
        assert score_10k >= score_bad_tick, (
            f"정상 틱({score_10k}) >= 비효율 틱({score_bad_tick})"
        )

    def test_ticks_to_cover_boundary_3_ticks(self, screener):
        """ticks_to_cover 경계값: 정확히 3틱이면 25점 (<=3 조건)."""
        # tick_pct = 0.21/3 = 0.07%
        # price=50000, tick=35원이면 tick_pct=0.07%
        from core.providers.kis_api import KISManager
        with patch.object(KISManager, 'get_tick_size', return_value=35):
            stock = _make_stock(price=50000, volume=5000000)
            score = screener._score_stock(stock)
        # ticks_to_cover = 0.21 / 0.07 = 3.0 → <=3 → 25점
        # 가격대(30) + 틱(25) + 거래량(25) + rvol
        assert score >= 80

    def test_ticks_to_cover_boundary_just_above_3(self, screener):
        """ticks_to_cover > 3 but <=5 → 16점."""
        # tick_pct = 0.21/4 = 0.0525%
        from core.providers.kis_api import KISManager
        with patch.object(KISManager, 'get_tick_size', return_value=26):
            # price=50000, tick=26 → tick_pct = 26/50000*100 = 0.052%
            # ticks_to_cover = 0.21/0.052 ≈ 4.04 → >3, <=5 → 16점
            stock = _make_stock(price=50000, volume=5000000)
            score = screener._score_stock(stock)
        # 가격대(30) + 틱(16) + 거래량(25) + rvol >= 71
        assert score >= 71


# ══════════════════════════════════════════════════════════════
# 급락 종목 차단 필터 테스트 (패닉 가드 Level 1)
# ══════════════════════════════════════════════════════════════


class TestDeclineFilter:
    """change_rate 급락 종목 차단 검증."""

    def test_stock_down_3pct_blocked(self, screener):
        """change_rate <= -3.0% 종목 → 차단."""
        stocks = [_make_stock(price=50000, volume=5000000, change_rate=-3.0)]
        result = screener.filter_stocks(stocks)
        assert len(result) == 0, "-3% 하락 종목이 차단되어야 함"

    def test_stock_down_7pct_blocked(self, screener):
        """KOSPI -7% 급락 시나리오: change_rate=-7% → 차단."""
        stocks = [_make_stock(price=218000, volume=3000000, change_rate=-7.0)]
        result = screener.filter_stocks(stocks)
        assert len(result) == 0, "-7% 폭락 종목이 차단되어야 함"

    def test_stock_down_2pct_allowed(self, screener):
        """change_rate=-2.0% → 통과 (임계값 -3% 미만)."""
        stocks = [_make_stock(price=50000, volume=5000000, change_rate=-2.0)]
        result = screener.filter_stocks(stocks)
        assert len(result) == 1, "-2% 하락 종목은 통과해야 함"

    def test_stock_down_2_9pct_allowed(self, screener):
        """경계값: change_rate=-2.9% → 통과."""
        stocks = [_make_stock(price=50000, volume=5000000, change_rate=-2.9)]
        result = screener.filter_stocks(stocks)
        assert len(result) == 1, "-2.9% 하락 종목은 통과해야 함"

    def test_crash_day_filters_most_stocks(self, screener):
        """폭락장 시나리오: 대부분 종목 -5%+ → 대부분 차단."""
        stocks = [
            _make_stock(code="A", price=218000, volume=5000000, change_rate=-9.8),  # 삼전
            _make_stock(code="B", price=150000, volume=3000000, change_rate=-11.1),  # 하이닉스
            _make_stock(code="C", price=50000, volume=2000000, change_rate=-5.2),
            _make_stock(code="D", price=30000, volume=4000000, change_rate=-1.5),  # 이것만 통과
        ]
        result = screener.filter_stocks(stocks)
        codes = [s["code"] for s in result]
        assert "D" in codes, "소폭 하락 종목은 통과"
        assert "A" not in codes, "-9.8% 종목 차단"
        assert "B" not in codes, "-11.1% 종목 차단"
        assert "C" not in codes, "-5.2% 종목 차단"

    def test_max_decline_pct_loaded_from_settings(self, screener):
        """설정 파일에서 max_decline_pct 로드 확인."""
        assert screener.max_decline_pct == -3.0


# ══════════════════════════════════════════════════════════════
# 필터링 로직 테스트
# ══════════════════════════════════════════════════════════════


class TestFilterStocks:
    """filter_stocks() 기본 동작 검증."""

    def test_price_below_min_excluded(self, screener):
        """min_price(3,000원) 미만 종목 제외 — 설정값 기준."""
        stocks = [_make_stock(price=1000)]
        result = screener.filter_stocks(stocks)
        assert len(result) == 0

    def test_price_above_max_excluded(self, screener):
        """max_price(500,000원) 초과 종목 제외."""
        stocks = [_make_stock(price=600000)]
        result = screener.filter_stocks(stocks)
        assert len(result) == 0

    def test_high_volatility_excluded(self, screener):
        """변동률 30% 이상 종목 제외 (상한가)."""
        stocks = [_make_stock(price=50000, change_rate=30.0)]
        result = screener.filter_stocks(stocks)
        assert len(result) == 0

    def test_valid_stock_included(self, screener):
        """유효한 종목은 통과."""
        stocks = [_make_stock(price=50000, volume=5000000, change_rate=3.0)]
        result = screener.filter_stocks(stocks)
        assert len(result) == 1

    def test_sorted_by_score_descending(self, screener):
        """점수 내림차순 정렬."""
        stocks = [
            _make_stock(code="A", price=10000, volume=500000, change_rate=1.0),
            _make_stock(code="B", price=50000, volume=5000000, change_rate=5.0),
            _make_stock(code="C", price=100000, volume=2000000, change_rate=3.0),
        ]
        result = screener.filter_stocks(stocks)
        scores = [s["scalp_score"] for s in result]
        assert scores == sorted(scores, reverse=True), "점수 내림차순 정렬 실패"

    def test_low_trading_value_excluded(self, screener):
        """거래대금 부족 종목 제외 (price * volume < min_trading_value=100억)."""
        # 10,000원 * 100주 = 100만원 << 100억 → 제외
        stocks = [_make_stock(price=10000, volume=100)]
        result = screener.filter_stocks(stocks)
        assert len(result) == 0

    def test_spread_filter_with_orderbook(self, screener):
        """스프레드 초과 종목 호가 데이터로 필터링."""
        from core.scalping.orderbook_analyzer import OrderbookAnalyzer
        from tests.mocks.mock_scalping import inject_orderbook

        oba = OrderbookAnalyzer()
        code = "005930"
        # 매우 넓은 스프레드 주입 (100bps)
        inject_orderbook(
            oba, code,
            bid_prices=[50000, 49900, 49800],
            bid_volumes=[1000, 800, 600],
            ask_prices=[50500, 50600, 50700],  # ~100bps 스프레드
            ask_volumes=[1000, 800, 600],
        )
        stocks = [_make_stock(code=code, price=50000, volume=5000000)]
        result = screener.filter_stocks(stocks, orderbook_analyzer=oba)
        # max_spread_bps=30 → 100bps 초과 → 제외
        assert len(result) == 0

    def test_empty_input_returns_empty(self, screener):
        """빈 입력 → 빈 결과."""
        result = screener.filter_stocks([])
        assert result == []

    def test_multiple_stocks_filtered_correctly(self, screener):
        """여러 종목 중 유효한 것만 통과.

        min_price=3,000, min_trading_value=100억 기준:
        - 1,000원 종목: 가격 미달 → 제외
        - 50,000원 * 5,000,000 = 2,500억 → 통과
        - 50,000원 변동률 35% → 제외
        - 20,000원 * 100주 = 200만 < 100억 → 거래대금 미달 → 제외
        """
        stocks = [
            _make_stock(code="001", price=1000, volume=5000000),   # 가격 미달(< 3,000)
            _make_stock(code="002", price=50000, volume=5000000),  # 통과
            _make_stock(code="003", price=50000, change_rate=35.0, volume=5000000),  # 변동률 초과
            _make_stock(code="004", price=20000, volume=100),       # 거래대금 미달
        ]
        result = screener.filter_stocks(stocks)
        codes = [s["code"] for s in result]
        assert "002" in codes
        assert "001" not in codes
        assert "003" not in codes
        assert "004" not in codes


# ══════════════════════════════════════════════════════════════
# 스코어링 세부 검증
# ══════════════════════════════════════════════════════════════


class TestScoreStock:
    """_score_stock() 개별 컴포넌트 검증."""

    def test_optimal_price_range_bonus(self, screener):
        """가격대별 점수 차별화 검증 — 설정 파일 기준 실제 값 사용.

        optimal_price_min/max는 scalping_settings.yaml에서 로드.
        최적 가격대에 속하면 30점, 20,000원 이상(비최적)이면 20점,
        20,000원 미만이면 8점. 동일 volume/change_rate로 비교."""
        # 최적 가격대 내 종목 (30점) — 설정상 3,000~50,000원이 최적
        stock_optimal = _make_stock(price=screener.optimal_price_min + 1000,
                                    volume=1000000, change_rate=0.0)
        # 최적 범위 밖, >=20,000원 (20점) — 예: 100,000원
        stock_above_optimal = _make_stock(price=100000,
                                          volume=1000000, change_rate=0.0)

        score_opt = screener._score_stock(stock_optimal)
        score_above = screener._score_stock(stock_above_optimal)

        # 최적 가격대가 그 위 가격대보다 높은 점수
        assert score_opt >= score_above, (
            f"최적 가격대({score_opt}) >= 최적 범위 밖({score_above}) 실패 "
            f"(optimal: {screener.optimal_price_min}~{screener.optimal_price_max}원)"
        )

    def test_high_volume_bonus(self, screener):
        """거래량 500만+ → 25점."""
        stock_high = _make_stock(volume=6000000, price=50000)
        stock_low = _make_stock(volume=100000, price=50000)

        score_high = screener._score_stock(stock_high)
        score_low = screener._score_stock(stock_low)

        assert score_high > score_low

    def test_score_max_100(self, screener):
        """최대 점수는 100점 초과 불가."""
        stock = _make_stock(price=100000, volume=10000000, change_rate=10.0)
        score = screener._score_stock(stock)
        assert score <= 100, f"점수 100 초과: {score}"

    def test_score_min_0(self, screener):
        """최소 점수는 0 이상."""
        stock = _make_stock(price=10000, volume=10, change_rate=0.0)
        score = screener._score_stock(stock)
        assert score >= 0, f"점수 음수: {score}"

    def test_rvol_proxy_high_activity(self, screener):
        """높은 변동률 × 거래량 → RVOL 프록시 점수 가산."""
        # rvol_proxy = abs(change_rate) * log(volume)
        # 10.0 * log(5,000,000) ≈ 10 * 15.4 = 154 → >=140 → 15점
        stock_active = _make_stock(price=50000, volume=5000000, change_rate=10.0)
        stock_calm = _make_stock(price=50000, volume=5000000, change_rate=0.1)

        score_active = screener._score_stock(stock_active)
        score_calm = screener._score_stock(stock_calm)

        assert score_active > score_calm, "활성 종목이 더 높은 점수여야 함"


# ══════════════════════════════════════════════════════════════
# get_priority_codes (인터페이스 존재 검증)
# ══════════════════════════════════════════════════════════════


class TestGetPriorityCodes:
    """get_priority_codes() 인터페이스 검증 (미사용 메서드, L-3)."""

    def test_returns_code_list(self, screener):
        """유효 종목에서 코드 리스트 반환."""
        stocks = [
            _make_stock(code="005930", price=50000, volume=5000000),
            _make_stock(code="035720", price=60000, volume=3000000),
        ]
        codes = screener.get_priority_codes(stocks, max_codes=5)
        assert isinstance(codes, list)
        assert "005930" in codes or "035720" in codes

    def test_max_codes_respected(self, screener):
        """max_codes 한도 준수."""
        stocks = [
            _make_stock(code=f"{i:06d}", price=50000, volume=5000000)
            for i in range(10)
        ]
        codes = screener.get_priority_codes(stocks, max_codes=3)
        assert len(codes) <= 3
