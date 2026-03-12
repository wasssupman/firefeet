import time


class RegimeDetector:
    """무상태 레짐 분류기 — 매 사이클(1.5초)마다 종목별 시장 상태 판단

    Returns: 'momentum' | 'reversion' | 'no_trade'
    """

    def __init__(self):
        self._last_diag_time = 0
        self._diag_interval = 30  # 30초마다 진단 출력

    def detect(self, code, tick_buffer, diag=False):
        """종목별 레짐 감지

        MOMENTUM (모두 충족):
          1. vwap_distance > +0.3%
          2. mom_60s > 0 AND mom_10s > 0
          3. tick_direction_ratio(30) > 0.3
          4. volume_acceleration > 1.5

        REVERSION:
          1. vwap_distance < -0.8%

        NO_TRADE: neither
        """
        if not tick_buffer.has_enough_data(code, 30):
            return "no_trade"

        vwap_dist = tick_buffer.get_vwap_distance(code)

        # Reversion: VWAP 아래 0.8% 이상 이탈
        if vwap_dist < -0.8:
            return "reversion"

        # Momentum: 감지는 하되 시그널 미검증 → no_trade 처리 (2026-03-11)
        # 모멘텀 시그널(momentum_burst, micro_trend)이 386건 분석에서 엣지 없음 확정.
        # 검증된 모멘텀 시그널 설계 전까지 비활성.
        if vwap_dist > 0.3:
            momentums = tick_buffer.get_momentums(code)
            mom_10s = momentums.get("10s", 0)
            mom_60s = momentums.get("60s", 0)
            tick_ratio = tick_buffer.get_tick_direction_ratio(code, n=30)
            vol_accel = tick_buffer.get_volume_acceleration(code)

            if (mom_60s > 0 and mom_10s > 0
                and tick_ratio > 0.3
                and vol_accel > 1.5):
                # return "momentum"  # 비활성: 시그널 엣지 미검증
                return "no_trade"  # MOMENTUM DISABLED: 386건 분석, 엣지 없음 (2026-02-26)

            # 진단 로그 (30초 간격)
            if diag:
                self._print_diag(code, vwap_dist, mom_10s, mom_60s, tick_ratio, vol_accel)

        # 진단: no_trade 직전, 30초마다 모든 종목 상태 출력
        if diag:
            momentums = tick_buffer.get_momentums(code)
            mom_10s = momentums.get("10s", 0)
            mom_60s = momentums.get("60s", 0)
            tick_ratio = tick_buffer.get_tick_direction_ratio(code, n=30)
            vol_accel = tick_buffer.get_volume_acceleration(code)
            self._print_diag(code, vwap_dist, mom_10s, mom_60s, tick_ratio, vol_accel)

        return "no_trade"

    def _print_diag(self, code, vwap_dist, mom_10s, mom_60s, tick_ratio, vol_accel):
        now = time.time()
        if now - self._last_diag_time < self._diag_interval:
            return
        self._last_diag_time = now

        zone = "DEAD" if -0.8 <= vwap_dist <= 0.3 else ("MOM?" if vwap_dist > 0.3 else "REV")
        checks = [
            ("vwap", f"{vwap_dist:+.2f}%"),
            ("m10s", f"{mom_10s:+.3f}%"),
            ("m60s", f"{mom_60s:+.3f}%"),
            ("ratio", f"{tick_ratio:+.3f}"),
            ("vol", f"{vol_accel:.2f}"),
        ]
        vals = " ".join(f"{name}={val}" for name, val in checks)
        print(f"  [REGIME] {code} [{zone}] {vals}")
