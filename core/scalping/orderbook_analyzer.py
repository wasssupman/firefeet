import time
import numpy as np


class OrderbookAnalyzer:
    """호가 10단계 데이터 분석기"""

    def __init__(self):
        self._orderbooks = {}   # {code: latest_orderbook_data}
        self._history = {}      # {code: [(timestamp, imbalance), ...]}
        self._history_max = 60  # 최근 60개 호가 스냅샷 (약 1분)

    def update(self, orderbook_data):
        """호가 데이터 업데이트"""
        code = orderbook_data.get("code")
        if not code:
            return
        self._orderbooks[code] = orderbook_data

        # 불균형 이력 저장 (속도 계산용)
        imbalance = self._calc_imbalance(orderbook_data)
        if code not in self._history:
            self._history[code] = []
        self._history[code].append((time.time(), imbalance))
        # 이력 크기 제한
        if len(self._history[code]) > self._history_max:
            self._history[code] = self._history[code][-self._history_max:]

    def _calc_imbalance(self, ob):
        """호가 불균형 비율 계산: (매수잔량 - 매도잔량) / 총잔량"""
        total_bid = ob.get("total_bid_volume", 0)
        total_ask = ob.get("total_ask_volume", 0)
        total = total_bid + total_ask
        if total == 0:
            return 0.0
        return (total_bid - total_ask) / total

    def get_imbalance(self, code):
        """호가 불균형 비율 (-1 ~ +1, 양수 = 매수 우위)"""
        ob = self._orderbooks.get(code)
        if not ob:
            return 0.0
        return self._calc_imbalance(ob)

    def get_spread_bps(self, code):
        """스프레드 (bps): (최우선매도 - 최우선매수) / 최우선매수 x 10000"""
        ob = self._orderbooks.get(code)
        if not ob:
            return float('inf')

        ask_prices = ob.get("ask_prices", [])
        bid_prices = ob.get("bid_prices", [])
        if not ask_prices or not bid_prices:
            return float('inf')

        # ask_prices[0] = 최우선매도 (가장 낮은 매도호가)
        # bid_prices[0] = 최우선매수 (가장 높은 매수호가)
        best_ask = ask_prices[0]
        best_bid = bid_prices[0]

        if best_bid <= 0:
            return float('inf')
        return (best_ask - best_bid) / best_bid * 10000

    def get_imbalance_velocity(self, code, window_seconds=10):
        """불균형 속도: 최근 N초간 불균형의 변화율"""
        history = self._history.get(code, [])
        if len(history) < 2:
            return 0.0

        now = time.time()
        cutoff = now - window_seconds
        recent = [(t, v) for t, v in history if t >= cutoff]

        if len(recent) < 2:
            return 0.0

        # 선형 기울기 (최소제곱법)
        times = np.array([t for t, _ in recent])
        values = np.array([v for _, v in recent])

        times_centered = times - times.mean()
        if np.sum(times_centered ** 2) == 0:
            return 0.0

        slope = np.sum(times_centered * (values - values.mean())) / np.sum(times_centered ** 2)
        return slope

    def get_volume_distribution_slope(self, code):
        """잔량 분포 기울기: 상위 호가 집중 vs 균등 분포"""
        ob = self._orderbooks.get(code)
        if not ob:
            return 0.0

        bid_volumes = ob.get("bid_volumes", [])
        ask_volumes = ob.get("ask_volumes", [])

        if not bid_volumes or not ask_volumes:
            return 0.0

        # 매수: 1호가 비중 (높을수록 상위 집중)
        total_bid = sum(bid_volumes)
        if total_bid > 0:
            bid_concentration = bid_volumes[0] / total_bid
        else:
            bid_concentration = 0

        # 매도: 1호가 비중
        total_ask = sum(ask_volumes)
        if total_ask > 0:
            ask_concentration = ask_volumes[0] / total_ask
        else:
            ask_concentration = 0

        # 매수 집중 - 매도 집중 (양수 = 매수 쪽 벽이 두꺼움)
        return bid_concentration - ask_concentration

    def detect_large_orders(self, code, threshold_ratio=3.0):
        """대량 주문 탐지: 평균 대비 threshold_ratio 배 이상 잔량"""
        ob = self._orderbooks.get(code)
        if not ob:
            return []

        large_orders = []
        bid_volumes = ob.get("bid_volumes", [])
        ask_volumes = ob.get("ask_volumes", [])
        bid_prices = ob.get("bid_prices", [])
        ask_prices = ob.get("ask_prices", [])

        all_volumes = bid_volumes + ask_volumes
        if not all_volumes:
            return []

        avg_vol = sum(all_volumes) / len(all_volumes)
        if avg_vol == 0:
            return []

        for i, (price, vol) in enumerate(zip(bid_prices, bid_volumes)):
            if vol > avg_vol * threshold_ratio:
                large_orders.append({"side": "bid", "level": i + 1, "price": price, "volume": vol, "ratio": vol / avg_vol})

        for i, (price, vol) in enumerate(zip(ask_prices, ask_volumes)):
            if vol > avg_vol * threshold_ratio:
                large_orders.append({"side": "ask", "level": i + 1, "price": price, "volume": vol, "ratio": vol / avg_vol})

        return large_orders

    def get_analysis(self, code):
        """종합 호가 분석 결과"""
        return {
            "code": code,
            "imbalance": round(self.get_imbalance(code), 4),
            "spread_bps": round(self.get_spread_bps(code), 2),
            "imbalance_velocity": round(self.get_imbalance_velocity(code), 6),
            "volume_slope": round(self.get_volume_distribution_slope(code), 4),
            "large_orders": self.detect_large_orders(code),
            "has_data": code in self._orderbooks,
        }

    def remove_code(self, code):
        """종목 데이터 제거"""
        self._orderbooks.pop(code, None)
        self._history.pop(code, None)

    def reset_all(self):
        """전체 리셋"""
        self._orderbooks.clear()
        self._history.clear()
