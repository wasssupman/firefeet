from dataclasses import dataclass
from collections import deque


@dataclass
class Candle:
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: float


class CandleHistory:
    """종목별 완성 캔들 링 버퍼"""

    def __init__(self, max_candles=60, interval=15):
        self.max_candles = max_candles  # 60개 = 15분 (15s 캔들 기준)
        self.interval = interval
        self._history = {}  # {code: deque(maxlen=max_candles)}

    def on_candle_complete(self, code, candle: Candle):
        """완성 캔들 수신 콜백"""
        if code not in self._history:
            self._history[code] = deque(maxlen=self.max_candles)
        self._history[code].append(candle)

    def count(self, code) -> int:
        """종목의 완성 캔들 수"""
        if code not in self._history:
            return 0
        return len(self._history[code])

    def get_candles(self, code, n=20) -> list:
        """최근 n개 완성 캔들 반환 (시간순)"""
        if code not in self._history:
            return []
        history = self._history[code]
        return list(history)[-n:]

    def get_closes(self, code, n=20) -> list:
        """최근 n개 종가"""
        return [c.close for c in self.get_candles(code, n)]

    def get_highs(self, code, n=20) -> list:
        """최근 n개 고가"""
        return [c.high for c in self.get_candles(code, n)]

    def get_lows(self, code, n=20) -> list:
        """최근 n개 저가"""
        return [c.low for c in self.get_candles(code, n)]

    def reset(self, code=None):
        """리셋"""
        if code:
            self._history.pop(code, None)
        else:
            self._history.clear()
