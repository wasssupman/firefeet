import numpy as np
import time


class TickBuffer:
    """종목별 고정 크기 링 버퍼 (numpy 배열, 3000틱 ~ 최대 180초)"""

    def __init__(self, max_size=3000):
        self.max_size = max_size
        self._buffers = {}  # {code: buffer_data}
        self._candle_callback = None  # 캔들 완성 콜백

    def set_candle_callback(self, callback):
        """캔들 완성 시 호출될 콜백 등록: callback(code, interval, candle_dict)"""
        self._candle_callback = callback

    def _init_buffer(self, code):
        """종목별 버퍼 초기화"""
        self._buffers[code] = {
            "prices": np.zeros(self.max_size, dtype=np.float64),
            "volumes": np.zeros(self.max_size, dtype=np.float64),
            "timestamps": np.zeros(self.max_size, dtype=np.float64),
            "directions": np.zeros(self.max_size, dtype=np.int8),  # 1: up, -1: down, 0: flat
            "index": 0,       # 다음 쓰기 위치
            "count": 0,       # 유효 데이터 수
            # VWAP 누적 (장 시작부터)
            "vwap_cum_pv": 0.0,  # sum(price * volume)
            "vwap_cum_vol": 0,   # sum(volume)
            # Rolling VWAP (최근 N초)
            "rolling_vwap_prices": [],   # deque 대신 list (틱 추가 시 append)
            "rolling_vwap_volumes": [],
            "rolling_vwap_timestamps": [],
            # 마이크로 캔들 집계
            "candles": {},       # {interval: {open, high, low, close, volume, start_time}}
        }

    def add_tick(self, code, price, volume, timestamp=None, direction=0):
        """틱 데이터 추가"""
        if code not in self._buffers:
            self._init_buffer(code)

        buf = self._buffers[code]
        idx = buf["index"]

        if timestamp is None:
            timestamp = time.time()

        buf["prices"][idx] = price
        buf["volumes"][idx] = volume
        buf["timestamps"][idx] = timestamp
        buf["directions"][idx] = direction

        buf["index"] = (idx + 1) % self.max_size
        buf["count"] = min(buf["count"] + 1, self.max_size)

        # VWAP 누적
        buf["vwap_cum_pv"] += price * volume
        buf["vwap_cum_vol"] += volume

        # Rolling VWAP 데이터 축적
        buf["rolling_vwap_prices"].append(price)
        buf["rolling_vwap_volumes"].append(volume)
        buf["rolling_vwap_timestamps"].append(timestamp)

        # 마이크로 캔들 업데이트
        self._update_candles(buf, code, price, volume, timestamp)

    def _get_recent(self, code, field, n):
        """최근 n개 데이터 반환 (시간순)"""
        if code not in self._buffers:
            return np.array([])
        buf = self._buffers[code]
        count = min(n, buf["count"])
        if count == 0:
            return np.array([])

        arr = buf[field]
        end = buf["index"]
        if count <= end:
            return arr[end - count:end]
        else:
            return np.concatenate([arr[self.max_size - (count - end):], arr[:end]])

    def get_count(self, code):
        """종목의 유효 틱 수"""
        if code not in self._buffers:
            return 0
        return self._buffers[code]["count"]

    # -- VWAP --

    def get_vwap(self, code):
        """실시간 VWAP (장 시작부터 누적)"""
        if code not in self._buffers:
            return 0.0
        buf = self._buffers[code]
        if buf["vwap_cum_vol"] == 0:
            return 0.0
        return buf["vwap_cum_pv"] / buf["vwap_cum_vol"]

    def get_vwap_distance(self, code):
        """현재가 대비 VWAP 괴리율 (%)"""
        vwap = self.get_vwap(code)
        if vwap == 0:
            return 0.0
        prices = self._get_recent(code, "prices", 1)
        if len(prices) == 0:
            return 0.0
        return (prices[-1] - vwap) / vwap * 100

    # -- Momentum --

    def get_momentum(self, code, window_seconds):
        """특정 윈도우(초) 동안의 가격 모멘텀 (%)"""
        if code not in self._buffers:
            return 0.0
        buf = self._buffers[code]
        if buf["count"] < 2:
            return 0.0

        now = time.time()
        cutoff = now - window_seconds

        prices = self._get_recent(code, "prices", buf["count"])
        timestamps = self._get_recent(code, "timestamps", buf["count"])

        # 윈도우 내 첫 가격 찾기
        mask = timestamps >= cutoff
        if not np.any(mask):
            return 0.0

        window_prices = prices[mask]
        if len(window_prices) < 2:
            return 0.0

        first_price = window_prices[0]
        last_price = window_prices[-1]

        if first_price == 0:
            return 0.0
        return (last_price - first_price) / first_price * 100

    def get_momentums(self, code):
        """10초/30초/60초/180초 모멘텀 딕셔너리"""
        return {
            "10s": self.get_momentum(code, 10),
            "30s": self.get_momentum(code, 30),
            "60s": self.get_momentum(code, 60),
            "180s": self.get_momentum(code, 180),
        }

    # -- Volume Acceleration --

    def get_volume_acceleration(self, code, recent_seconds=30, avg_seconds=180):
        """거래량 가속도: 최근 N초 거래량 / 이동평균 거래량"""
        if code not in self._buffers:
            return 0.0
        buf = self._buffers[code]
        if buf["count"] < 10:
            return 0.0

        now = time.time()
        volumes = self._get_recent(code, "volumes", buf["count"])
        timestamps = self._get_recent(code, "timestamps", buf["count"])

        recent_mask = timestamps >= (now - recent_seconds)
        avg_mask = timestamps >= (now - avg_seconds)

        recent_vol = np.sum(volumes[recent_mask]) if np.any(recent_mask) else 0
        avg_vol = np.sum(volumes[avg_mask]) if np.any(avg_mask) else 0

        # 시간 보정
        recent_duration = recent_seconds
        avg_duration = avg_seconds

        recent_rate = recent_vol / recent_duration if recent_duration > 0 else 0
        avg_rate = avg_vol / avg_duration if avg_duration > 0 else 0

        if avg_rate == 0:
            return 0.0
        return recent_rate / avg_rate

    # -- Tick Direction Ratio --

    def get_tick_direction_ratio(self, code, n=50):
        """상승틱/하락틱 비율 (N틱 슬라이딩 윈도우, -1 ~ +1)"""
        directions = self._get_recent(code, "directions", n)
        if len(directions) == 0:
            return 0.0
        up = np.sum(directions > 0)
        down = np.sum(directions < 0)
        total = up + down
        if total == 0:
            return 0.0
        return (up - down) / total

    # -- Time-based Tick Direction Ratio --

    def get_tick_direction_ratio_time(self, code, seconds=5):
        """시간 기반 틱 방향 비율 (종목간 비교 가능, -1 ~ +1)"""
        if code not in self._buffers:
            return 0.0
        buf = self._buffers[code]
        if buf["count"] < 5:
            return 0.0

        now = time.time()
        cutoff = now - seconds
        timestamps = self._get_recent(code, "timestamps", buf["count"])
        directions = self._get_recent(code, "directions", buf["count"])

        mask = timestamps >= cutoff
        if not np.any(mask):
            return 0.0

        window_dirs = directions[mask]
        up = np.sum(window_dirs > 0)
        down = np.sum(window_dirs < 0)
        total = up + down
        if total == 0:
            return 0.0
        return (up - down) / total

    # -- Momentum Reversal --

    def get_momentum_reversal(self, code, short_window=10, long_window=30):
        """모멘텀 반전 감지: 하락→상승 전환 (교차 조건)

        Returns: (is_reversing: bool, velocity_change: float)
        - mom_short > +0.1% (최근 반등 시작, threshold로 noise 필터)
        - mom_long < 0 (직전까지 하락 중)
        - velocity_change = mom_short - mom_long
        """
        mom_short = self.get_momentum(code, short_window)
        mom_long = self.get_momentum(code, long_window)

        # 교차 조건: 단기 양전환(threshold) + 장기 아직 음
        is_reversing = mom_short > 0.1 and mom_long < 0
        velocity_change = mom_short - mom_long

        return is_reversing, velocity_change

    # -- Tick Rate Z-Score --

    def get_tick_rate_zscore(self, code, seconds=5, baseline_seconds=300):
        """z-score 정규화된 틱 강도 (종목간 비교 가능)

        Returns: recent_rate / baseline_rate (1.0 = 평균, 3.0 = 3배 과열)
        baseline이 0이면 0.0 반환.
        """
        if code not in self._buffers:
            return 0.0
        buf = self._buffers[code]
        if buf["count"] < 10:
            return 0.0

        now = time.time()
        timestamps = self._get_recent(code, "timestamps", buf["count"])

        # 최근 N초 틱 수
        recent_mask = timestamps >= (now - seconds)
        recent_count = np.sum(recent_mask)
        recent_rate = recent_count / seconds if seconds > 0 else 0

        # 기준선 (최근 5분) 틱 수
        baseline_mask = timestamps >= (now - baseline_seconds)
        baseline_count = np.sum(baseline_mask)
        baseline_rate = baseline_count / baseline_seconds if baseline_seconds > 0 else 0

        if baseline_rate == 0:
            return 0.0
        return recent_rate / baseline_rate

    # -- Rolling VWAP --

    def get_rolling_vwap_distance(self, code, window_seconds=3600):
        """최근 N초 Rolling VWAP 대비 이격도 (%)

        Full-day VWAP와 별개로, 최근 1시간 데이터만으로 VWAP 계산.
        오후 시간대 VWAP 고착(inertia) 문제 해결용.
        """
        if code not in self._buffers:
            return 0.0
        buf = self._buffers[code]

        prices_list = buf["rolling_vwap_prices"]
        volumes_list = buf["rolling_vwap_volumes"]
        timestamps_list = buf["rolling_vwap_timestamps"]

        if not prices_list:
            return 0.0

        now = time.time()
        cutoff = now - window_seconds

        # 윈도우 내 데이터만 필터 (뒤에서부터 탐색)
        cum_pv = 0.0
        cum_vol = 0
        for i in range(len(timestamps_list) - 1, -1, -1):
            if timestamps_list[i] < cutoff:
                break
            cum_pv += prices_list[i] * volumes_list[i]
            cum_vol += volumes_list[i]

        if cum_vol == 0:
            return 0.0

        rolling_vwap = cum_pv / cum_vol
        current_price = prices_list[-1]
        return (current_price - rolling_vwap) / rolling_vwap * 100

    # -- Micro Candles --

    CANDLE_INTERVALS = [5, 15, 30]  # seconds

    def _update_candles(self, buf, code, price, volume, timestamp):
        """마이크로 캔들 업데이트"""
        for interval in self.CANDLE_INTERVALS:
            candle = buf["candles"].get(interval)
            if candle is not None and timestamp - candle["start_time"] >= interval:
                # 기존 캔들 완성 -> 콜백
                if self._candle_callback:
                    self._candle_callback(code, interval, candle)
                candle = None  # 아래에서 새 캔들 생성

            if candle is None:
                buf["candles"][interval] = {
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": volume,
                    "start_time": timestamp,
                }
            else:
                candle["high"] = max(candle["high"], price)
                candle["low"] = min(candle["low"], price)
                candle["close"] = price
                candle["volume"] += volume

    def get_micro_candle(self, code, interval=15):
        """마이크로 캔들 조회"""
        if code not in self._buffers:
            return None
        return self._buffers[code]["candles"].get(interval)

    # -- Latest Price --

    def get_latest_price(self, code):
        """최신 가격"""
        prices = self._get_recent(code, "prices", 1)
        if len(prices) == 0:
            return 0
        return int(prices[-1])

    def get_latest_volume(self, code):
        """최신 거래량"""
        volumes = self._get_recent(code, "volumes", 1)
        if len(volumes) == 0:
            return 0
        return int(volumes[-1])

    # -- Session Management --

    def reset_vwap(self, code):
        """VWAP 리셋 (장 시작 시)"""
        if code in self._buffers:
            self._buffers[code]["vwap_cum_pv"] = 0.0
            self._buffers[code]["vwap_cum_vol"] = 0
            self._buffers[code]["rolling_vwap_prices"] = []
            self._buffers[code]["rolling_vwap_volumes"] = []
            self._buffers[code]["rolling_vwap_timestamps"] = []

    def reset_all(self):
        """전체 버퍼 리셋"""
        self._buffers.clear()

    def remove_code(self, code):
        """종목 버퍼 제거"""
        self._buffers.pop(code, None)

    def has_enough_data(self, code, min_ticks=30):
        """충분한 데이터 존재 여부"""
        return self.get_count(code) >= min_ticks

    def get_summary(self, code):
        """종목 버퍼 요약 (디버깅용)"""
        if code not in self._buffers:
            return None
        buf = self._buffers[code]
        latest_price = self.get_latest_price(code)
        vwap = self.get_vwap(code)
        return {
            "code": code,
            "tick_count": buf["count"],
            "latest_price": latest_price,
            "vwap": round(vwap, 1),
            "vwap_distance": round(self.get_vwap_distance(code), 3),
            "momentums": self.get_momentums(code),
            "volume_accel": round(self.get_volume_acceleration(code), 2),
            "tick_ratio": round(self.get_tick_direction_ratio(code), 3),
            "tick_rate_zscore": round(self.get_tick_rate_zscore(code), 2),
            "rolling_vwap_dist": round(self.get_rolling_vwap_distance(code), 4),
        }
