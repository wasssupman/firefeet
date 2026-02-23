import yaml
import os

from core.technical.overlay import TAOverlay
from core.technical.indicators.atr import ATRIndicator
from core.technical.indicators.bollinger import BollingerIndicator
from core.technical.indicators.support_resistance import SRIndicator


class IntradayAnalyzer:
    """인트라데이 기술적 분석 오케스트레이터"""

    def __init__(self, candle_history, config_path="config/technical_config.yaml", config=None):
        self.candle_history = candle_history
        if config is not None:
            self._config = config
        else:
            self._config = self._load_config(config_path)

        atr_cfg = self._config.get("atr", {})
        bb_cfg = self._config.get("bollinger", {})
        sr_cfg = self._config.get("support_resistance", {})

        self.atr = ATRIndicator(
            period=atr_cfg.get("period", 14),
            tp_multiplier=atr_cfg.get("tp_multiplier", 1.5),
            sl_multiplier=atr_cfg.get("sl_multiplier", 1.0),
            min_tp=atr_cfg.get("min_tp", 0.3),
            max_tp=atr_cfg.get("max_tp", 1.5),
            min_sl=atr_cfg.get("min_sl", -0.8),
            max_sl=atr_cfg.get("max_sl", -0.2),
        )
        self.bb = BollingerIndicator(
            period=bb_cfg.get("period", 20),
            num_std=bb_cfg.get("num_std", 2.0),
        )
        self.sr = SRIndicator(
            lookback=sr_cfg.get("lookback", 30),
            min_touches=sr_cfg.get("min_touches", 2),
        )

        self._min_candles = max(
            atr_cfg.get("period", 14) + 1,
            bb_cfg.get("period", 20),
            5,  # SR 최소
        )

    def _load_config(self, path):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[IntradayAnalyzer] Config load failed: {e}")
        return {}

    def analyze(self, code) -> TAOverlay:
        """모든 지표 계산 -> TAOverlay 생성"""
        # 캔들 부족 시 기본값 반환 (기존 전략에 영향 없음)
        if self.candle_history.count(code) < self._min_candles:
            return TAOverlay()

        atr_result = self.atr.calculate(code, self.candle_history)
        bb_result = self.bb.calculate(code, self.candle_history)
        sr_result = self.sr.calculate(code, self.candle_history)

        bb_threshold = self._config.get("bollinger", {}).get("early_exit_threshold", 0.8)

        return TAOverlay(
            atr_pct=atr_result["atr_pct"],
            suggested_tp=atr_result["suggested_tp"],
            suggested_sl=atr_result["suggested_sl"],
            bb_position=bb_result["position"],
            nearest_support=sr_result["nearest_support"],
            nearest_resistance=sr_result["nearest_resistance"],
            support_distance_pct=sr_result["support_distance_pct"],
            resistance_distance_pct=sr_result["resistance_distance_pct"],
            bb_exit_threshold=bb_threshold,
        )
