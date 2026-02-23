import yaml
import os

class ScalpSignals:
    """스캘핑 시그널 계산기 (5개 독립 시그널, 각 0-100)"""

    def __init__(self, settings_path="config/scalping_settings.yaml"):
        self.settings = self._load_settings(settings_path)
        self.weights = self.settings.get("signal_weights", {
            "vwap_reversion": 25,
            "orderbook_pressure": 25,
            "momentum_burst": 20,
            "volume_surge": 15,
            "micro_trend": 15,
        })

    def _load_settings(self, path):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[ScalpSignals] Settings load failed: {e}")
        return {}

    def calculate_all(self, code, tick_buffer, orderbook_analyzer):
        """모든 시그널 계산 → {name: score} 딕셔너리"""
        return {
            "vwap_reversion": self.signal_vwap_reversion(code, tick_buffer),
            "orderbook_pressure": self.signal_orderbook_pressure(code, orderbook_analyzer),
            "momentum_burst": self.signal_momentum_burst(code, tick_buffer),
            "volume_surge": self.signal_volume_surge(code, tick_buffer),
            "micro_trend": self.signal_micro_trend(code, tick_buffer),
        }

    def get_composite_score(self, signals, weights: dict = None):
        """가중 합산 복합 스코어 (0~100)"""
        active_weights = weights if weights is not None else self.weights
        total_weight = sum(active_weights.values())
        if total_weight == 0:
            return 0
        score = 0
        for name, raw in signals.items():
            w = active_weights.get(name, 0)
            score += raw * (w / total_weight)
        return score

    # ── Signal 1: VWAP Reversion (25%) ──────────────────

    def signal_vwap_reversion(self, code, tick_buffer):
        """
        VWAP 회귀: 가격이 VWAP 아래 0.3%+ → 거래량 증가 + 60초 추세 양전환 시 매수 시그널.
        Score: 0 (VWAP 위 또는 하락 바이어스) ~ 100 (VWAP -1%+ 이하 + 거래량 급증 + 반등 추세)
        """
        if not tick_buffer.has_enough_data(code, 30):
            return 0

        vwap_dist = tick_buffer.get_vwap_distance(code)  # (price - vwap) / vwap * 100
        vol_accel = tick_buffer.get_volume_acceleration(code)

        # VWAP 위 0.1% 이상이면 비활성
        if vwap_dist >= 0.1:
            return 0

        # VWAP 근처(±0.1%) — 약한 기본 점수
        if vwap_dist >= -0.1:
            return 15

        # VWAP 방향 바이어스: 60초 추세가 음수이면 반등 가능성 없음 → 0 반환
        momentums = tick_buffer.get_momentums(code)
        if momentums["60s"] <= 0:
            return 0
        trend_bonus = 15

        # VWAP 아래 정도에 따라 기본 점수
        abs_dist = abs(vwap_dist)
        if abs_dist >= 1.0:
            base_score = 70
        elif abs_dist >= 0.5:
            base_score = 55
        elif abs_dist >= 0.3:
            base_score = 40
        else:
            base_score = 25

        # 거래량 가속 보너스
        if vol_accel >= 3.0:
            vol_bonus = 15
        elif vol_accel >= 2.0:
            vol_bonus = 10
        elif vol_accel >= 1.0:
            vol_bonus = 5
        else:
            vol_bonus = 0

        return min(100, base_score + trend_bonus + vol_bonus)

    # ── Signal 2: Orderbook Pressure (25%) ──────────────

    def signal_orderbook_pressure(self, code, orderbook_analyzer):
        """
        호가 압력: 불균형 > +0.3 (매수 우위) + 속도 양수 → 매수 시그널.
        Score: 0 (매도 우위) ~ 100 (강한 매수 불균형 + 가속)
        """
        analysis = orderbook_analyzer.get_analysis(code)
        if not analysis.get("has_data"):
            return 0

        imbalance = analysis["imbalance"]
        velocity = analysis["imbalance_velocity"]
        vol_slope = analysis["volume_slope"]

        # 강한 매도 우위면 0
        if imbalance <= -0.3:
            return 0

        # 약한 매도 우위/중립: 기본 점수
        if imbalance <= 0:
            return 15

        # 불균형 강도에 따른 기본 점수
        if imbalance >= 0.7:
            base_score = 70
        elif imbalance >= 0.5:
            base_score = 55
        elif imbalance >= 0.3:
            base_score = 40
        elif imbalance >= 0.1:
            base_score = 30
        else:
            base_score = 20

        # 속도 보너스 (불균형이 커지는 중)
        velocity_bonus = 0
        if velocity > 0.01:
            velocity_bonus = 15
        elif velocity > 0.005:
            velocity_bonus = 10
        elif velocity > 0:
            velocity_bonus = 5

        # 잔량 분포 보너스
        slope_bonus = 0
        if vol_slope > 0.1:
            slope_bonus = 10
        elif vol_slope > 0.05:
            slope_bonus = 5

        return min(100, base_score + velocity_bonus + slope_bonus)

    # ── Signal 3: Momentum Burst (20%) ──────────────────

    def signal_momentum_burst(self, code, tick_buffer):
        """
        모멘텀 버스트: 연속 상승틱 비율 + 평균 이상 거래량.
        Score: 0 (명확한 약세) ~ 100 (강한 모멘텀)

        P8 원칙 적용: 단일 틱 하락에 과민 반응하지 않도록
        - 틱 윈도우 20 → 30으로 확장 (통계 안정성)
        - 소프트 임계값: 명확한 하락세(-0.2 이하)에서만 0 반환
        - 약한 하락/중립 구간은 50% 감점으로 완화
        """
        if not tick_buffer.has_enough_data(code, 10):
            return 0

        # 틱 방향 비율 (최근 30틱 — 20에서 확장하여 단일 틱 과민도 방지)
        tick_ratio = tick_buffer.get_tick_direction_ratio(code, 30)

        # 10초 모멘텀
        momentums = tick_buffer.get_momentums(code)
        mom_10s = momentums["10s"]

        # 거래량 가속
        vol_accel = tick_buffer.get_volume_acceleration(code, recent_seconds=10)

        # 명확한 하락세일 때만 0 반환
        if tick_ratio < -0.3 and mom_10s < -0.3:
            return 0

        # 약한 하락/중립: 30% 감점 (0.5→0.7로 완화)
        dampening = 1.0
        if tick_ratio <= 0 or mom_10s <= 0:
            dampening = 0.7

        # 틱 비율 기본 점수
        if tick_ratio >= 0.8:
            base_score = 60
        elif tick_ratio >= 0.6:
            base_score = 45
        elif tick_ratio >= 0.4:
            base_score = 30
        else:
            base_score = 15

        # 모멘텀 보너스
        mom_bonus = 0
        if mom_10s >= 0.3:
            mom_bonus = 20
        elif mom_10s >= 0.15:
            mom_bonus = 15
        elif mom_10s >= 0.05:
            mom_bonus = 10

        # 거래량 보너스
        vol_bonus = 0
        if vol_accel >= 2.0:
            vol_bonus = 20
        elif vol_accel >= 1.5:
            vol_bonus = 10

        return min(100, int((base_score + mom_bonus + vol_bonus) * dampening))

    # ── Signal 4: Volume Surge (15%) ────────────────────

    def signal_volume_surge(self, code, tick_buffer):
        """
        거래량 급증: 30초 거래량 > 3배 평균.
        Score: 0 ~ 100 (극심한 거래량 급증)
        """
        if not tick_buffer.has_enough_data(code, 20):
            return 0

        vol_accel = tick_buffer.get_volume_acceleration(code, recent_seconds=30, avg_seconds=180)

        if vol_accel < 0.5:
            return 0
        elif vol_accel < 1.0:
            return 15
        elif vol_accel >= 5.0:
            return 100
        elif vol_accel >= 3.0:
            return 80
        elif vol_accel >= 2.0:
            return 60
        elif vol_accel >= 1.5:
            return 40
        else:
            return 20

    # ── Signal 5: Micro Trend (15%) ─────────────────────

    def signal_micro_trend(self, code, tick_buffer):
        """
        마이크로 추세: 10초/30초/60초 모멘텀 모두 양수.
        Score: 0 (불일치) ~ 100 (전 타임프레임 상승 + 가속)
        """
        if not tick_buffer.has_enough_data(code, 30):
            return 0

        momentums = tick_buffer.get_momentums(code)
        mom_10 = momentums["10s"]
        mom_30 = momentums["30s"]
        mom_60 = momentums["60s"]

        # 기본: 얼마나 많은 타임프레임이 양수인지
        positive_count = sum(1 for m in [mom_10, mom_30, mom_60] if m > 0)

        if positive_count == 0:
            return 10  # 완전 하락에서도 최소 점수
        elif positive_count == 1:
            return 25
        elif positive_count == 2:
            base_score = 45
        else:
            # 전부 양수
            base_score = 65

        # 가속도 보너스: 짧은 타임프레임이 긴 것보다 강한지
        accel_bonus = 0
        if positive_count == 3:
            if mom_10 > mom_30 > mom_60 > 0:
                accel_bonus = 25  # 가속 중
            elif mom_10 > mom_30 > 0:
                accel_bonus = 15
            elif mom_10 > 0:
                accel_bonus = 10

        return min(100, base_score + accel_bonus)
