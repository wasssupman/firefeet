"""
StockScreener 통합 테스트.

테스트 항목:
  1. Pre-filter 로직
  2. 개별 스코어링 함수 (mock data)
  3. 전체 파이프라인 (실제 API, 선택적)
"""
import sys
import os

from core.encoding_setup import setup_utf8_stdout
setup_utf8_stdout()

# ────────────────────── Mock Classes ──────────────────────

class MockStrategy:
    k = 0.5
    
    def get_target_price(self, code, df):
        if df is None or len(df) < 2:
            return None
            
        today = df.iloc[0]
        yesterday = df.iloc[1]
        range = yesterday['high'] - yesterday['low']
        target = today['open'] + range * self.k
        return {
            'target_price': target,
            'current_open': today['open'],
            'yesterday_range': range
        }


class MockManager:
    class auth:
        url_base = "https://mock"


# ────────────────────── Tests ──────────────────────

def test_pre_filter():
    """Pre-filter: Scanner 데이터만으로 부적격 제거"""
    from core.analysis.scoring_engine import StockScreener
    import pandas as pd

    screener = StockScreener(MockStrategy())

    stocks = [
        {"code": "A", "name": "정상", "price": 10000, "volume": 1000000, "change_rate": 3.0},
        {"code": "B", "name": "거래량부족", "price": 10000, "volume": 100000, "change_rate": 3.0},
        {"code": "C", "name": "고가", "price": 600000, "volume": 1000000, "change_rate": 3.0},
        {"code": "D", "name": "급락", "price": 10000, "volume": 1000000, "change_rate": -5.0},
        {"code": "E", "name": "과열", "price": 10000, "volume": 1000000, "change_rate": 16.0},
        {"code": "F", "name": "정상2", "price": 50000, "volume": 800000, "change_rate": 1.5},
    ]

    screener.settings["output"]["min_score"] = 0
    screener.settings["output"]["min_breakout_proximity"] = 0
    
    def mock_data_provider(code):
        ohlc = pd.DataFrame({"close": [10000, 10000], "volume": [10000, 10000], "high": [10000, 10000], "low": [10000, 10000], "open": [10000, 10000]})
        supply = {"sentiment": "NEUTRAL", "foreign_3d": 0, "institution_3d": 0}
        current_data = {"price": 10000, "high": 10000}
        return ohlc, supply, current_data

    result = screener.screen(stocks, mock_data_provider)
    codes = [s["code"] for s in result]

    assert "A" in codes, "정상 종목 A 통과해야 함"
    assert "F" in codes, "정상 종목 F 통과해야 함"
    assert "B" not in codes, "거래량 부족 B 제외해야 함"
    assert "C" not in codes, "고가 C 제외해야 함"
    assert "D" not in codes, "급락 D 제외해야 함"
    assert "E" not in codes, "과열 E 제외해야 함"
    assert len(result) == 2, f"Expected 2, got {len(result)}"

    print("✅ test_pre_filter PASSED")


def test_price_momentum():
    """가격 모멘텀 스코어링"""
    from core.analysis.scoring_engine import StockScreener

    screener = StockScreener(MockStrategy())

    cases = [
        (-1.0, 0),    # 하락 → 0
        (0.0, 0),     # 보합 → 0
        (1.5, None),  # 상승 중 → >0
        (3.0, 100),   # 피크 → 100
        (7.0, None),  # 감소 중 → >0
        (13.0, 0),    # 과열 → 0
        (15.0, 0),    # 초과열 → 0
    ]

    for cr, expected in cases:
        stock = {"change_rate": cr}
        score = screener._score_price_momentum(stock)
        if expected is not None:
            assert score == expected, f"change_rate={cr}: expected {expected}, got {score}"
        else:
            assert score > 0, f"change_rate={cr}: expected >0, got {score}"

    # 피크 확인: 3%에서 최대
    s3 = screener._score_price_momentum({"change_rate": 3.0})
    s1 = screener._score_price_momentum({"change_rate": 1.0})
    s7 = screener._score_price_momentum({"change_rate": 7.0})
    assert s3 > s1, f"3% ({s3}) should be > 1% ({s1})"
    assert s3 > s7, f"3% ({s3}) should be > 7% ({s7})"

    print("✅ test_price_momentum PASSED")


def test_volume_surge():
    """거래량 급증 스코어링"""
    import pandas as pd
    from core.analysis.scoring_engine import StockScreener

    screener = StockScreener(MockStrategy())

    # 5일 평균 거래량 100,000
    ohlc = pd.DataFrame({
        "close": [10000] * 6,
        "volume": [0, 100000, 100000, 100000, 100000, 100000],
        "open": [10000] * 6,
        "high": [10500] * 6,
        "low": [9500] * 6,
    })

    cases = [
        (500000, 100),  # 5x → 100
        (300000, 80),   # 3x → 80
        (200000, 60),   # 2x → 60
        (150000, 40),   # 1.5x → 40
        (100000, 20),   # 1x → 20
        (50000, 0),     # 0.5x → 0
    ]

    for vol, expected in cases:
        stock = {"volume": vol}
        score = screener._score_volume_surge(stock, ohlc)
        assert score == expected, f"volume={vol}: expected {expected}, got {score}"

    print("✅ test_volume_surge PASSED")


def test_ma_alignment():
    """이동평균 정배열 스코어링"""
    import pandas as pd
    from core.analysis.scoring_engine import StockScreener

    screener = StockScreener(MockStrategy())

    # 정배열: MA5 > MA20 (최근 5일 close > 전체 20일 close)
    closes_aligned = [110] * 5 + [100] * 15  # MA5=110, MA20=102.5
    ohlc_aligned = pd.DataFrame({"close": closes_aligned})
    stock_aligned = {"price": 115}
    score = screener._score_ma_alignment(stock_aligned, ohlc_aligned)
    assert score >= 60, f"정배열: expected >=60, got {score}"

    # 부분 정배열: P > MA5, but MA5 < MA20
    closes_partial = [105] * 5 + [110] * 15  # MA5=105, MA20=108.75
    ohlc_partial = pd.DataFrame({"close": closes_partial})
    stock_partial = {"price": 108}
    score = screener._score_ma_alignment(stock_partial, ohlc_partial)
    assert score == 30, f"부분 정배열: expected 30, got {score}"

    # 역배열: P < MA5
    stock_reverse = {"price": 95}
    score = screener._score_ma_alignment(stock_reverse, ohlc_aligned)
    assert score == 0, f"역배열: expected 0, got {score}"

    print("✅ test_ma_alignment PASSED")


def test_supply_demand():
    """수급 스코어링"""
    from core.analysis.scoring_engine import StockScreener

    screener = StockScreener(MockStrategy())

    # 쌍끌이 매수 (대규모)
    supply_bull = {"sentiment": "BULLISH (Double Buy)", "foreign_3d": 200000, "institution_3d": 100000}
    assert screener._score_supply_demand(supply_bull) == 100

    # 쌍끌이 매수 (소규모)
    supply_bull_small = {"sentiment": "BULLISH (Double Buy)", "foreign_3d": 10000, "institution_3d": 5000}
    assert screener._score_supply_demand(supply_bull_small) == 80

    # 외국인만 순매수
    supply_foreign = {"sentiment": "NEUTRAL", "foreign_3d": 50000, "institution_3d": -10000}
    assert screener._score_supply_demand(supply_foreign) == 55

    # 기관만 순매수
    supply_inst = {"sentiment": "NEUTRAL", "foreign_3d": -10000, "institution_3d": 50000}
    assert screener._score_supply_demand(supply_inst) == 50

    # 쌍끌이 매도
    supply_bear = {"sentiment": "BEARISH (Double Sell)", "foreign_3d": -50000, "institution_3d": -30000}
    assert screener._score_supply_demand(supply_bear) == 0

    # NEUTRAL (양쪽 다 0 이하이지만 Double Sell은 아닌 경우)
    supply_neutral = {"sentiment": "NEUTRAL", "foreign_3d": -100, "institution_3d": -50}
    assert screener._score_supply_demand(supply_neutral) == 25

    # No Data
    assert screener._score_supply_demand("No Data") == 0
    assert screener._score_supply_demand(None) == 0

    print("✅ test_supply_demand PASSED")


def test_breakout_proximity():
    """돌파 근접도 스코어링"""
    import pandas as pd
    from core.analysis.scoring_engine import StockScreener

    screener = StockScreener(MockStrategy())

    # target = open + (high - low) * k = 10000 + (10500 - 9500) * 0.5 = 10500
    ohlc = pd.DataFrame({
        "open": [10000, 10000],
        "high": [10500, 10500],
        "low": [9500, 9500],
        "close": [10200, 10200],
        "volume": [100000, 100000],
    })

    # 이미 돌파 (방금)
    stock = {"code": "TEST", "price": 10600}
    score = screener._score_breakout_proximity(stock, ohlc)
    assert score == 100, f"방금 돌파: expected 100, got {score}"

    # 이미 돌파 (크게)
    stock = {"code": "TEST", "price": 11500}
    score = screener._score_breakout_proximity(stock, ohlc)
    assert score == 85, f"크게 돌파: expected 85, got {score}"

    # 목표가 근접 (0.5% 이내)
    stock = {"code": "TEST", "price": 10480}  # diff = 0.19%
    score = screener._score_breakout_proximity(stock, ohlc)
    assert score == 75, f"0.5% 이내: expected 75, got {score}"

    # 5% 이상 먼 경우
    stock = {"code": "TEST", "price": 9000}
    score = screener._score_breakout_proximity(stock, ohlc)
    assert score == 0, f"5% 이상: expected 0, got {score}"

    print("✅ test_breakout_proximity PASSED")


def test_weighted_total():
    """가중 합산 검증"""
    from core.analysis.scoring_engine import StockScreener

    screener = StockScreener(MockStrategy())
    weights = screener.settings["weights"]

    # 모든 항목 100점이면 총점 100점
    total = sum(100 * (w / 100) for w in weights.values())
    assert total == 100.0, f"Max score should be 100, got {total}"

    # 모든 항목 0점이면 총점 0점
    total = sum(0 * (w / 100) for w in weights.values())
    assert total == 0.0, f"Min score should be 0, got {total}"

    print("✅ test_weighted_total PASSED")


def test_settings_load():
    """설정 파일 로드"""
    from core.analysis.scoring_engine import StockScreener

    screener = StockScreener(MockStrategy())

    assert screener.settings["weights"]["volume_surge"] == 20
    assert screener.settings["pre_filter"]["min_volume"] == 500000
    assert screener.settings["output"]["min_score"] == 30
    assert screener.settings["cache"]["ttl"] == 300

    print("✅ test_settings_load PASSED")


def test_live_pipeline():
    """실제 API를 사용한 전체 파이프라인 테스트 (선택적)"""
    from core.config_loader import ConfigLoader
    from core.kis_auth import KISAuth
    from core.providers.kis_api import KISManager
    from core.analysis.technical import VolatilityBreakoutStrategy
    from core.scanner import StockScanner

    print("\n--- Live Pipeline Test ---")
    loader = ConfigLoader()
    config = loader.get_kis_config(mode="REAL")
    account_info = loader.get_account_info()

    auth = KISAuth(config)
    manager = KISManager(auth, account_info, mode="REAL")
    strategy = VolatilityBreakoutStrategy(k=0.5)
    scanner = StockScanner(auth)
    screener = StockScreener(strategy)

    raw = scanner.get_top_volume_stocks(limit=20)
    if not raw:
        print("⚠️  No stocks from scanner (market may be closed). Skipping live test.")
        return

    results = screener.screen(raw)
    output = screener.get_screened_stocks(raw)

    assert isinstance(output, list)
    for item in output:
        assert "code" in item
        assert "name" in item

    print(f"✅ test_live_pipeline PASSED ({len(output)} stocks screened)")


# ────────────────────── Runner ──────────────────────

if __name__ == "__main__":
    print("=== StockScreener Integration Tests ===\n")

    # Unit tests (no API calls)
    test_settings_load()
    test_pre_filter()
    test_price_momentum()
    test_volume_surge()
    test_ma_alignment()
    test_supply_demand()
    test_breakout_proximity()
    test_weighted_total()

    print(f"\n{'='*40}")
    print("All unit tests passed!")
    print(f"{'='*40}")

    # Live test (optional, requires API credentials)
    if "--live" in sys.argv:
        from core.analysis.scoring_engine import StockScreener
        test_live_pipeline()
    else:
        print("\nSkipping live test. Run with --live to include API tests.")
