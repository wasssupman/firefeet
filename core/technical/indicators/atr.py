from core.technical.base import TAIndicator


class ATRIndicator(TAIndicator):
    """Average True Range - 변동성 측정"""

    def __init__(self, period=14, tp_multiplier=1.5, sl_multiplier=1.0,
                 min_tp=0.3, max_tp=1.5, min_sl=-0.8, max_sl=-0.2,
                 cache_ttl=5.0):
        super().__init__(cache_ttl)
        self.period = period
        self.tp_multiplier = tp_multiplier
        self.sl_multiplier = sl_multiplier
        self.min_tp = min_tp
        self.max_tp = max_tp
        self.min_sl = min_sl  # 가장 넓은 SL (e.g. -0.8%)
        self.max_sl = max_sl  # 가장 좁은 SL (e.g. -0.2%)

    def _compute(self, code, candle_history) -> dict:
        closes = candle_history.get_closes(code, self.period + 1)
        highs = candle_history.get_highs(code, self.period + 1)
        lows = candle_history.get_lows(code, self.period + 1)

        if len(closes) < self.period + 1:
            return {
                "atr": 0.0,
                "atr_pct": 0.0,
                "suggested_tp": 0.0,
                "suggested_sl": 0.0,
            }

        # True Range 계산
        true_ranges = []
        for i in range(1, len(closes)):
            h = highs[i]
            l = lows[i]
            c_prev = closes[i - 1]
            tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
            true_ranges.append(tr)

        # SMA of True Range
        recent_tr = true_ranges[-self.period:]
        atr = sum(recent_tr) / len(recent_tr)

        # ATR as percentage of current price
        current_price = closes[-1]
        if current_price <= 0:
            return {
                "atr": atr,
                "atr_pct": 0.0,
                "suggested_tp": 0.0,
                "suggested_sl": 0.0,
            }

        atr_pct = atr / current_price * 100

        # TP/SL 제안 (ATR 기반 + 클램핑)
        suggested_tp = max(self.min_tp, min(self.max_tp, atr_pct * self.tp_multiplier))
        suggested_sl = min(self.max_sl, max(self.min_sl, -(atr_pct * self.sl_multiplier)))

        return {
            "atr": round(atr, 2),
            "atr_pct": round(atr_pct, 4),
            "suggested_tp": round(suggested_tp, 4),
            "suggested_sl": round(suggested_sl, 4),
        }
