"""
tests/test_data_service.py — KISDataService TTL 캐시 테스트 (11 cases)
"""

import threading
import time
from unittest.mock import MagicMock, call

import pytest

from core.providers.data_service import KISDataService


# ── Fixtures ────────────────────────────────────────────────────────────────

def make_manager():
    """KISManager 목(Mock) 생성."""
    m = MagicMock()
    m.get_daily_ohlc.return_value = {"ohlc": "data"}
    m.get_investor_trend.return_value = {"trend": "data"}
    m.get_current_price.return_value = {"price": 50000}
    m.get_top_volume_stocks.return_value = [{"code": "005930"}]
    m.get_balance.return_value = {"deposit": 1_000_000, "holdings": []}
    m.place_order.return_value = "ORDER_001"
    m.cancel_order.return_value = "CANCEL_001"
    m.get_order_status.return_value = [{"odno": "ORDER_001"}]
    return m


# ── 1. 캐시 히트: 동일 종목 2회 호출 시 API 1회만 실행 ──────────────────────

def test_cache_hit_returns_same_data():
    manager = make_manager()
    svc = KISDataService(manager)

    result1 = svc.get_daily_ohlc("005930")
    result2 = svc.get_daily_ohlc("005930")

    assert result1 == result2
    manager.get_daily_ohlc.assert_called_once_with("005930")


# ── 2. TTL 만료 후 API 재호출 ────────────────────────────────────────────────

def test_cache_miss_after_ttl_expires():
    manager = make_manager()
    # current_price TTL을 0.05초로 단축
    svc = KISDataService(manager, ttl_config={"current_price": 0.05})

    svc.get_current_price("005930")
    time.sleep(0.1)  # TTL 초과
    svc.get_current_price("005930")

    assert manager.get_current_price.call_count == 2


# ── 3. place_order 후 balance 캐시 무효화 ───────────────────────────────────

def test_place_order_invalidates_balance():
    manager = make_manager()
    svc = KISDataService(manager)

    svc.get_balance()                        # 캐시 적재
    assert manager.get_balance.call_count == 1

    svc.place_order("005930", 1, 50000, "BUY")  # 주문 → balance 무효화
    svc.get_balance()                        # 재조회 → API 재호출

    assert manager.get_balance.call_count == 2


# ── 4. cancel_order 후 balance 캐시 무효화 ──────────────────────────────────

def test_cancel_order_invalidates_balance():
    manager = make_manager()
    svc = KISDataService(manager)

    svc.get_balance()
    assert manager.get_balance.call_count == 1

    svc.cancel_order("ORDER_001", "005930", 1)
    svc.get_balance()

    assert manager.get_balance.call_count == 2


# ── 5. get_order_status는 매번 API 직접 호출 ────────────────────────────────

def test_get_order_status_never_cached():
    manager = make_manager()
    svc = KISDataService(manager)

    svc.get_order_status()
    svc.get_order_status()
    svc.get_order_status()

    assert manager.get_order_status.call_count == 3


# ── 6. invalidate(prefix) — 특정 prefix만 제거 ──────────────────────────────

def test_invalidate_prefix():
    manager = make_manager()
    svc = KISDataService(manager)

    # ohlc 2종목 + price 1종목 캐시
    svc.get_daily_ohlc("005930")
    svc.get_daily_ohlc("000660")
    svc.get_current_price("005930")
    assert manager.get_daily_ohlc.call_count == 2
    assert manager.get_current_price.call_count == 1

    svc.invalidate("ohlc:")  # ohlc 캐시만 삭제

    svc.get_daily_ohlc("005930")   # 재조회
    svc.get_daily_ohlc("000660")   # 재조회
    svc.get_current_price("005930")  # 캐시 히트 — 재조회 없음

    assert manager.get_daily_ohlc.call_count == 4
    assert manager.get_current_price.call_count == 1  # 그대로


# ── 7. invalidate() 전체 캐시 제거 ──────────────────────────────────────────

def test_invalidate_all():
    manager = make_manager()
    svc = KISDataService(manager)

    svc.get_daily_ohlc("005930")
    svc.get_current_price("005930")
    svc.get_balance()
    assert manager.get_daily_ohlc.call_count == 1
    assert manager.get_current_price.call_count == 1
    assert manager.get_balance.call_count == 1

    svc.invalidate()  # 전체 캐시 제거

    svc.get_daily_ohlc("005930")
    svc.get_current_price("005930")
    svc.get_balance()

    assert manager.get_daily_ohlc.call_count == 2
    assert manager.get_current_price.call_count == 2
    assert manager.get_balance.call_count == 2


# ── 8. API 오류(None 반환) 시 캐시하지 않음 ──────────────────────────────────

def test_api_error_not_cached():
    manager = make_manager()
    manager.get_daily_ohlc.return_value = None  # API 실패 시뮬레이션
    svc = KISDataService(manager)

    result1 = svc.get_daily_ohlc("005930")
    result2 = svc.get_daily_ohlc("005930")

    assert result1 is None
    assert result2 is None
    assert manager.get_daily_ohlc.call_count == 2  # 매번 API 호출


# ── 9. 멀티스레드 동시 접근 안전성 ──────────────────────────────────────────

def test_thread_safety():
    manager = make_manager()
    svc = KISDataService(manager)

    results = []
    errors = []

    def worker():
        try:
            for _ in range(5):
                r = svc.get_daily_ohlc("005930")
                results.append(r)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"스레드 오류 발생: {errors}"
    assert len(results) == 50
    # 모든 결과가 동일한 데이터
    assert all(r == {"ohlc": "data"} for r in results)
    # API는 최대 수 회만 호출 (레이스컨디션 허용 범위 내)
    assert manager.get_daily_ohlc.call_count <= 10


# ── 10. TTL 커스텀 설정 반영 ────────────────────────────────────────────────

def test_custom_ttl_config():
    manager = make_manager()
    # balance TTL을 0.05초로 단축
    svc = KISDataService(manager, ttl_config={"balance": 0.05})

    svc.get_balance()
    time.sleep(0.1)
    svc.get_balance()

    assert manager.get_balance.call_count == 2


# ── 11. 패스스루 메서드 존재 확인 ────────────────────────────────────────────

def test_passthrough_methods_exist():
    manager = make_manager()
    svc = KISDataService(manager)

    # place_order 패스스루
    result = svc.place_order("005930", 1, 50000, "BUY")
    assert result == "ORDER_001"
    manager.place_order.assert_called_once_with("005930", 1, 50000, "BUY")

    # cancel_order 패스스루
    result = svc.cancel_order("ORDER_001", "005930", 1)
    assert result == "CANCEL_001"
    manager.cancel_order.assert_called_once_with("ORDER_001", "005930", 1)

    # get_order_status 패스스루
    result = svc.get_order_status()
    assert result == [{"odno": "ORDER_001"}]
    manager.get_order_status.assert_called_once_with()
