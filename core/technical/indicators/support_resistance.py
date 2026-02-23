from core.technical.base import TAIndicator


class SRIndicator(TAIndicator):
    """지지/저항선 - 최근 캔들의 피봇 포인트 기반"""

    def __init__(self, lookback=30, min_touches=2, cache_ttl=5.0):
        super().__init__(cache_ttl)
        self.lookback = lookback
        self.min_touches = min_touches

    def _compute(self, code, candle_history) -> dict:
        candles = candle_history.get_candles(code, self.lookback)

        if len(candles) < 5:
            return {
                "nearest_support": 0.0,
                "nearest_resistance": 0.0,
                "support_distance_pct": 0.0,
                "resistance_distance_pct": 0.0,
            }

        current_price = candles[-1].close
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]

        # 피봇 레벨 수집 (로컬 고/저점)
        levels = []
        for i in range(1, len(candles) - 1):
            # 로컬 고점 (양쪽보다 높은 high)
            if highs[i] >= highs[i - 1] and highs[i] >= highs[i + 1]:
                levels.append(highs[i])
            # 로컬 저점 (양쪽보다 낮은 low)
            if lows[i] <= lows[i - 1] and lows[i] <= lows[i + 1]:
                levels.append(lows[i])

        if not levels:
            # 피봇이 없으면 단순 최고/최저 사용
            levels = [max(highs), min(lows)]

        # 클러스터링: 가까운 레벨을 병합 (0.1% 이내)
        clustered = self._cluster_levels(levels, current_price, threshold_pct=0.1)

        # 터치 횟수 필터링
        valid_levels = []
        for level in clustered:
            touches = self._count_touches(level, candles, tolerance_pct=0.15)
            if touches >= self.min_touches:
                valid_levels.append(level)

        # 유효 레벨이 부족하면 클러스터 전체 사용
        if len(valid_levels) < 2:
            valid_levels = clustered

        # 현재가 기준 지지/저항선 탐색
        supports = [l for l in valid_levels if l < current_price]
        resistances = [l for l in valid_levels if l > current_price]

        nearest_support = max(supports) if supports else 0.0
        nearest_resistance = min(resistances) if resistances else 0.0

        support_dist = ((current_price - nearest_support) / current_price * 100
                        if nearest_support > 0 else 0.0)
        resistance_dist = ((nearest_resistance - current_price) / current_price * 100
                           if nearest_resistance > 0 else 0.0)

        return {
            "nearest_support": round(nearest_support, 2),
            "nearest_resistance": round(nearest_resistance, 2),
            "support_distance_pct": round(support_dist, 4),
            "resistance_distance_pct": round(resistance_dist, 4),
        }

    def _cluster_levels(self, levels, ref_price, threshold_pct=0.1):
        """가까운 레벨을 클러스터링 (평균으로 병합)"""
        if not levels:
            return []
        sorted_levels = sorted(levels)
        threshold = ref_price * threshold_pct / 100

        clusters = []
        current_cluster = [sorted_levels[0]]

        for i in range(1, len(sorted_levels)):
            if sorted_levels[i] - sorted_levels[i - 1] <= threshold:
                current_cluster.append(sorted_levels[i])
            else:
                clusters.append(sum(current_cluster) / len(current_cluster))
                current_cluster = [sorted_levels[i]]

        clusters.append(sum(current_cluster) / len(current_cluster))
        return clusters

    def _count_touches(self, level, candles, tolerance_pct=0.15):
        """레벨에 대한 터치 횟수 (high/low가 레벨 근처인 캔들 수)"""
        tolerance = level * tolerance_pct / 100
        touches = 0
        for c in candles:
            if abs(c.high - level) <= tolerance or abs(c.low - level) <= tolerance:
                touches += 1
        return touches
