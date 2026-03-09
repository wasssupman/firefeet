import yaml
import os

class ScalpSignals:
    """스캘핑 시그널 계산기 (5개 독립 시그널, 각 0-100)"""

    def __init__(self, settings_path="config/scalping_settings.yaml"):
        self.settings = self._load_settings(settings_path)
        self.weights = self.settings.get("signal_weights", {
            "vwap_reversion": 80,
            "orderbook_pressure": 20,
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
        """활성 시그널 계산 → {name: score} 딕셔너리

        VWAP Reversion 전환: micro_trend, momentum_burst, volume_surge 비활성.
        vwap_reversion이 이벤트 트리거로 동작 (3조건 AND).
        """
        return {
            "vwap_reversion": self.signal_vwap_reversion(code, tick_buffer),
            "orderbook_pressure": self.signal_orderbook_pressure(code, orderbook_analyzer),
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
        """VWAP Deviation Reversion — 이벤트 기반 진입

        3조건 AND — 하나라도 미충족 시 score=0:
        1. VWAP 이격: vwap_dist < -0.8% (과매도, -0.6% 금지)
        2. 거래 과열: tick_rate_zscore > 2.0 OR volume_accel > 2.0
        3. 모멘텀 반전: mom_short > 0.1% AND mom_long < 0 (교차 조건)

        추가 필터:
        - 스프레드 < 20bps (orderbook_pressure에서 별도 처리)

        Score: 0 (조건 미충족) ~ 100 (강한 reversion setup)
        confidence는 최약 조건의 강도가 결정.
        """
        if not tick_buffer.has_enough_data(code, 30):
            return 0

        # 조건 1: VWAP 이격도 (과매도)
        vwap_dist = tick_buffer.get_vwap_distance(code)
        if vwap_dist >= -0.8:
            return 0  # VWAP 아래 0.8% 미만 이탈 → 기회 없음

        # 조건 2: 거래 과열 (volume spike + vwap deviation 동시 충족 시 허용)
        tick_rate_z = tick_buffer.get_tick_rate_zscore(code, seconds=5, baseline_seconds=300)
        vol_accel = tick_buffer.get_volume_acceleration(code, recent_seconds=30, avg_seconds=180)
        if tick_rate_z < 2.0 and vol_accel < 2.0:
            return 0  # 거래 과열 없음 → 진입 불가

        # 조건 3: 모멘텀 반전 (하락→상승 교차)
        is_reversing, velocity_change = tick_buffer.get_momentum_reversal(code, short_window=10, long_window=30)
        if not is_reversing:
            return 0  # 반전 미확인 → 진입 불가

        # === 3조건 모두 충족 ===
        # 각 조건의 강도를 개별 점수로 변환

        # VWAP 이격 강도 (0.8% ~ 2.0%+ 범위를 30~50 점수로)
        abs_dist = abs(vwap_dist)
        if abs_dist >= 1.5:
            dist_score = 50
        elif abs_dist >= 1.0:
            dist_score = 40
        else:
            dist_score = 30  # 0.8~1.0%

        # 거래 과열 강도
        heat_score = min(30, int(max(tick_rate_z, vol_accel) * 8))

        # 반전 속도 강도
        reversal_score = min(20, int(velocity_change * 40))

        return min(100, dist_score + heat_score + reversal_score)

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
