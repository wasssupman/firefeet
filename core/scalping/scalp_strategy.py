import yaml
import os

class ScalpStrategy:
    """스캘핑 복합 시그널 전략 — 신뢰도 스코어 생성"""

    def __init__(self, scalp_signals, settings_path="config/scalping_settings.yaml"):
        self.signals = scalp_signals
        self.settings = self._load_settings(settings_path)
        self.confidence_threshold = self.settings.get("default_confidence_threshold", 0.65)

        # 하이브리드 모드
        hybrid = self.settings.get("hybrid", {})
        self.mode = hybrid.get("mode", "auto")
        self.micro_swing_tp = hybrid.get("micro_swing_tp", 0.5)
        self.micro_swing_sl = hybrid.get("micro_swing_sl", -0.25)
        self.aggressive_tp = hybrid.get("aggressive_tp", 1.5)
        self.aggressive_sl = hybrid.get("aggressive_sl", -0.5)
        self.switch_threshold = hybrid.get("switch_threshold", 40)

        # 온도 레벨
        self.temperature_level = "NEUTRAL"
        self.temperature_value = 0

    def _load_settings(self, path):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[ScalpStrategy] Settings load failed: {e}")
        return {}

    def evaluate(self, code, tick_buffer, orderbook_analyzer, profile=None, ta_overlay=None):
        """
        종합 평가 → 진입 신호.
        profile이 주어지면 profile의 가중치/임계값/TP/SL 사용.
        Returns: {
            "code": str,
            "signals": dict,       # 개별 시그널 점수
            "composite": float,    # 가중 합산 점수 (0~100)
            "confidence": float,   # 페널티 적용 신뢰도 (0~1)
            "should_enter": bool,  # 진입 여부
            "mode": str,           # 전략명 또는 micro_swing | aggressive
            "take_profit": float,  # TP %
            "stop_loss": float,    # SL %
        }
        """
        # 1. 개별 시그널 계산
        signals = self.signals.calculate_all(code, tick_buffer, orderbook_analyzer)

        # 2. 가중 합산 (profile 가중치 우선)
        weights = profile.weights if profile else None
        composite = self.signals.get_composite_score(signals, weights=weights)

        # 3. 페널티: 곱셈이 아닌 거부권(veto) 방식
        # 기존 문제: confidence = composite/100 * penalty → 이중 감점으로 진입 불가
        # 개선: confidence = composite/100 (시그널 품질만 반영), penalty < 0.5이면 거부
        spread_penalty = self._spread_penalty(code, orderbook_analyzer)
        volume_penalty = self._volume_penalty(code, tick_buffer)
        combined_penalty = min(spread_penalty, volume_penalty)

        confidence = composite / 100.0
        penalty_veto = combined_penalty < 0.5  # 극단적 스프레드/거래량만 차단

        # 4. 모드/파라미터 결정 (profile 우선)
        if profile:
            mode = profile.name
            tp, sl = profile.take_profit, profile.stop_loss
            threshold = max(profile.confidence_threshold, self.confidence_threshold)
        else:
            mode = self._get_mode()
            tp, sl = self._get_tp_sl(mode)
            threshold = self.confidence_threshold

        # 4.5. TAOverlay로 TP/SL 동적 조절
        if ta_overlay:
            tp = ta_overlay.effective_tp(tp)
            sl = ta_overlay.effective_sl(sl)

        # 5. 진입 판단: 시그널 품질 + 페널티 거부권
        should_enter = confidence >= threshold and not penalty_veto

        return {
            "code": code,
            "signals": signals,
            "composite": round(composite, 2),
            "confidence": round(confidence, 4),
            "should_enter": should_enter,
            "threshold": threshold,
            "mode": mode,
            "take_profit": tp,
            "stop_loss": sl,
            "penalties": {
                "spread": round(spread_penalty, 3),
                "volume": round(volume_penalty, 3),
                "combined": round(combined_penalty, 3),
            },
        }

    def _spread_penalty(self, code, orderbook_analyzer):
        """스프레드 페널티: 넓은 스프레드 → 신뢰도 감소 (완화)"""
        spread = orderbook_analyzer.get_spread_bps(code)
        if spread <= 15:
            return 1.0
        elif spread <= 30:
            return 0.95
        elif spread <= 50:
            return 0.85
        elif spread <= 80:
            return 0.75
        else:
            return 0.60

    def _volume_penalty(self, code, tick_buffer):
        """거래량 페널티: 거래량 부족 시 신뢰도 감소 (완화)"""
        vol_accel = tick_buffer.get_volume_acceleration(code)
        if vol_accel >= 1.2:
            return 1.0
        elif vol_accel >= 0.8:
            return 0.95
        elif vol_accel >= 0.4:
            return 0.85
        else:
            return 0.65

    def _get_mode(self):
        """현재 모드 결정 (hybrid.mode 또는 온도 기반 자동 전환)"""
        if self.mode != "auto":
            return self.mode
        # 온도 기반 자동 전환
        if self.temperature_value >= self.switch_threshold:
            return "aggressive"
        else:
            return "micro_swing"

    def _get_tp_sl(self, mode):
        """모드별 TP/SL 반환"""
        if mode == "aggressive":
            return self.aggressive_tp, self.aggressive_sl
        else:
            return self.micro_swing_tp, self.micro_swing_sl

    def apply_temperature(self, temp_result, rules_path="config/scalping_rules.yaml"):
        """온도 결과 적용 → 신뢰도 임계값 + 모드 조절"""
        self.temperature_value = temp_result.get("temperature", 0)
        self.temperature_level = temp_result.get("level", "NEUTRAL")

        # scalping_rules.yaml의 temperature_overrides 적용
        try:
            if os.path.exists(rules_path):
                with open(rules_path, "r", encoding="utf-8") as f:
                    rules = yaml.safe_load(f) or {}
                overrides = rules.get("temperature_overrides", {}).get(self.temperature_level, {})
                if overrides:
                    old_thresh = self.confidence_threshold
                    self.confidence_threshold = overrides.get("confidence", self.confidence_threshold)

                    if overrides.get("mode"):
                        self.mode = overrides["mode"]
                    if overrides.get("take_profit_pct"):
                        self.aggressive_tp = overrides["take_profit_pct"]
                        self.micro_swing_tp = overrides["take_profit_pct"]
                    if overrides.get("stop_loss_pct"):
                        self.aggressive_sl = overrides["stop_loss_pct"]
                        self.micro_swing_sl = overrides["stop_loss_pct"]

                    print(f"[ScalpStrategy] 온도 적용 ({self.temperature_level}): "
                          f"threshold={old_thresh}→{self.confidence_threshold}, mode={self.mode}")
        except Exception as e:
            print(f"[ScalpStrategy] 온도 오버라이드 적용 실패: {e}")

    def should_exit(self, code, buy_price, current_price, hold_seconds, tick_buffer, orderbook_analyzer, confidence_threshold=0.15, profile=None, ta_overlay=None):
        """
        매도 시그널 판단 — 단순화된 3조건.
        Returns: (should_sell: bool, reason: str, is_market_order: bool)
        """
        if buy_price <= 0:
            return False, "", False

        profit_rate = (current_price - buy_price) / buy_price * 100

        if profile:
            tp = profile.take_profit
            sl = profile.stop_loss
            max_hold = profile.max_hold_seconds
        else:
            mode = self._get_mode()
            tp, sl = self._get_tp_sl(mode)
            max_hold = self.settings.get("max_hold_seconds", 120)

        # TAOverlay로 TP/SL 동적 조절
        if ta_overlay:
            tp = ta_overlay.effective_tp(tp)
            sl = ta_overlay.effective_sl(sl)

        # 1. 손절 (SL) — 시장가
        if profit_rate <= sl:
            return True, f"SCALP_SELL_SL({profit_rate:+.2f}%)", True

        # 2. 익절 (TP) — 지정가
        if profit_rate >= tp:
            return True, f"SCALP_SELL_TP({profit_rate:+.2f}%)", False

        # 3. 시간 초과 — 지정가
        if hold_seconds >= max_hold:
            return True, f"SCALP_SELL_TIMEOUT({hold_seconds:.0f}s)", False

        return False, "", False
