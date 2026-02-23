from dataclasses import dataclass


@dataclass
class TAOverlay:
    """기술적 분석 결과 - 전략 파라미터 조절용"""
    atr_pct: float = 0.0
    suggested_tp: float = 0.0       # ATR 기반 TP (%), 0이면 미산출
    suggested_sl: float = 0.0       # ATR 기반 SL (%), 0이면 미산출
    bb_position: float = 0.5        # BB 위치 (0=하단, 1=상단)
    nearest_support: float = 0.0
    nearest_resistance: float = 0.0
    support_distance_pct: float = 0.0
    resistance_distance_pct: float = 0.0
    bb_exit_threshold: float = 0.8  # config에서 주입

    def effective_tp(self, base_tp: float) -> float:
        """ATR 기반 TP와 base_tp 중 보수적 선택 + BB 조절"""
        if self.suggested_tp > 0:
            tp = min(base_tp, self.suggested_tp)
        else:
            tp = base_tp

        # BB 상단 근접 시 조기 익절 유도
        if self.bb_position > self.bb_exit_threshold:
            tp *= 0.8

        return round(tp, 4)

    def effective_sl(self, base_sl: float) -> float:
        """ATR 기반 SL과 base_sl 중 보수적 선택 (둘 다 음수)

        프로파일 SL의 70%보다 좁아지지 않도록 하한 보호.
        예: base_sl=-0.4 → tightest=-0.28 → ATR이 -0.2 제안해도 -0.28로 제한
        """
        if self.suggested_sl < 0:
            sl = max(base_sl, self.suggested_sl)  # ATR이 좁히는 건 허용
            tightest = base_sl * 0.7              # 프로파일 SL의 70%까지만 허용
            sl = min(sl, tightest)                # 그 이상 좁아지면 차단
        else:
            sl = base_sl

        return round(sl, 4)
