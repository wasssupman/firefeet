import math
from core.technical.base import TAIndicator


class BollingerIndicator(TAIndicator):
    """볼린저 밴드 - 과매수/과매도 판단"""

    def __init__(self, period=20, num_std=2.0, cache_ttl=5.0):
        super().__init__(cache_ttl)
        self.period = period
        self.num_std = num_std

    def _compute(self, code, candle_history) -> dict:
        closes = candle_history.get_closes(code, self.period)

        if len(closes) < self.period:
            return {
                "upper": 0.0,
                "middle": 0.0,
                "lower": 0.0,
                "position": 0.5,
                "bandwidth": 0.0,
            }

        recent = closes[-self.period:]

        # SMA (middle band)
        middle = sum(recent) / len(recent)

        # Standard deviation
        variance = sum((p - middle) ** 2 for p in recent) / len(recent)
        std = math.sqrt(variance)

        # Bands
        upper = middle + self.num_std * std
        lower = middle - self.num_std * std

        # Position: 현재가가 밴드 내 어디에 위치하는지 (0=하단, 1=상단)
        current_price = closes[-1]
        band_width = upper - lower
        if band_width > 0:
            position = (current_price - lower) / band_width
            position = max(0.0, min(1.0, position))
        else:
            position = 0.5

        # Bandwidth: 밴드 폭 / 중간선 (변동성 지표)
        bandwidth = band_width / middle if middle > 0 else 0.0

        return {
            "upper": round(upper, 2),
            "middle": round(middle, 2),
            "lower": round(lower, 2),
            "position": round(position, 4),
            "bandwidth": round(bandwidth, 6),
        }
