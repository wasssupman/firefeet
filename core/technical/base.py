import time


class TAIndicator:
    """기술 지표 베이스 클래스 (캐싱 포함)"""

    def __init__(self, cache_ttl=5.0):
        self._cache = {}  # {code: (timestamp, result)}
        self._cache_ttl = cache_ttl

    def calculate(self, code, candle_history) -> dict:
        """캐시 확인 -> _compute() 호출"""
        now = time.time()
        cached = self._cache.get(code)
        if cached and (now - cached[0]) < self._cache_ttl:
            return cached[1]

        result = self._compute(code, candle_history)
        self._cache[code] = (now, result)
        return result

    def _compute(self, code, candle_history) -> dict:
        """서브클래스 구현"""
        raise NotImplementedError
