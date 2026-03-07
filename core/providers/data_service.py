"""
KISDataService — KISManager 캐시 프록시.

읽기 전용 API에 TTL 캐시를 적용하여 중복 API 호출과 time.sleep() 병목을 제거한다.
쓰기/상태확인 API(place_order, cancel_order, get_order_status)는 절대 캐시하지 않는다.
"""

import time
import threading


class KISDataService:
    """KISManager 캐시 프록시. 읽기 전용 API에 TTL 캐시 적용."""

    def __init__(self, manager, ttl_config=None):
        self.manager = manager
        self._cache = {}  # {cache_key: (data, expire_time)}
        self._lock = threading.Lock()
        self._ttl = {
            "daily_ohlc": 300,      # 하루 1회 변경 — 5분 캐시
            "investor_trend": 300,  # 하루 1회 변경 — 5분 캐시
            "current_price": 5,     # 실시간성 필요 — 5초 캐시
            "top_volume": 60,       # 60초 캐시
            "balance": 30,          # 30초 캐시, 주문 후 invalidate
            **(ttl_config or {}),
        }

    def _get_cached(self, key, ttl_name, fetch_fn):
        """캐시 히트 시 반환, 미스 시 fetch_fn 호출 후 캐시."""
        with self._lock:
            if key in self._cache:
                data, expire = self._cache[key]
                if time.time() < expire:
                    return data

        # 캐시 미스 — 실제 API 호출 (lock 밖에서 실행해 블로킹 최소화)
        data = fetch_fn()

        # API 오류(None 또는 Exception)는 캐시하지 않음
        if data is not None:
            with self._lock:
                self._cache[key] = (data, time.time() + self._ttl[ttl_name])

        return data

    def invalidate(self, prefix=None):
        """캐시 무효화. prefix 없으면 전체, 있으면 해당 prefix로 시작하는 키만."""
        with self._lock:
            if prefix:
                self._cache = {
                    k: v for k, v in self._cache.items()
                    if not k.startswith(prefix)
                }
            else:
                self._cache.clear()

    # ── 캐시 적용 읽기 전용 메서드 ──────────────────────────────────────────

    def get_daily_ohlc(self, code):
        return self._get_cached(
            f"ohlc:{code}",
            "daily_ohlc",
            lambda: self.manager.get_daily_ohlc(code),
        )

    def get_investor_trend(self, code):
        return self._get_cached(
            f"trend:{code}",
            "investor_trend",
            lambda: self.manager.get_investor_trend(code),
        )

    def get_current_price(self, code):
        return self._get_cached(
            f"price:{code}",
            "current_price",
            lambda: self.manager.get_current_price(code),
        )

    def get_top_volume_stocks(self, count=30, **kwargs):
        # limit 키워드도 수용 (KISManager는 limit= 파라미터 사용)
        limit = kwargs.get("limit", count)
        return self._get_cached(
            f"top_vol:{limit}",
            "top_volume",
            lambda: self.manager.get_top_volume_stocks(limit),
        )

    def get_balance(self):
        return self._get_cached(
            "balance",
            "balance",
            lambda: self.manager.get_balance(),
        )

    # ── 패스스루 (캐시 금지) + balance invalidation ──────────────────────────

    def place_order(self, *args, **kwargs):
        result = self.manager.place_order(*args, **kwargs)
        self.invalidate("balance")  # 주문 후 잔고 캐시 무효화
        return result

    def cancel_order(self, *args, **kwargs):
        result = self.manager.cancel_order(*args, **kwargs)
        self.invalidate("balance")  # 취소 후 잔고 캐시 무효화
        return result

    def get_order_status(self, *args, **kwargs):
        # 체결 확인용 — 절대 캐시하면 안 됨
        return self.manager.get_order_status(*args, **kwargs)

    # ── KISManager 위임 속성 (기존 코드 호환) ────────────────────────────────

    def __getattr__(self, name):
        """캐시 메서드에 없는 속성/메서드는 manager에서 위임."""
        return getattr(self.manager, name)
