import yaml
import os
import datetime
from datetime import timezone, timedelta
from dataclasses import dataclass, field
from typing import Dict, Optional

KST = timezone(timedelta(hours=9))


@dataclass
class StrategyProfile:
    name: str
    weights: Dict[str, float]
    take_profit: float
    stop_loss: float
    confidence_threshold: float
    max_hold_seconds: int


class StrategySelector:
    """시간대 + 온도 조건에 따라 최적 전략 프로파일 선택"""

    def __init__(self, config_path: str = "config/scalping_strategies.yaml"):
        self.config_path = config_path
        self._temperature_level = "NEUTRAL"
        self._temperature_value = 0
        self._last_strategy_name = "adaptive"

    def apply_temperature(self, temp_result: dict):
        """온도 결과 저장 (select() 시 참조)"""
        self._temperature_level = temp_result.get("level", "NEUTRAL")
        self._temperature_value = temp_result.get("temperature", 0)

    def current_strategy_name(self) -> str:
        """마지막으로 선택된 전략명 반환 (로깅용)"""
        return self._last_strategy_name

    def select(self) -> Optional[StrategyProfile]:
        """
        현재 시간 + 온도 조건으로 StrategyProfile 선택.
        점심 구간(12:00~13:30)이면 None 반환 → 진입 차단.
        """
        cfg = self._load_config()
        now_str = datetime.datetime.now(KST).strftime("%H%M")

        # 1. 점심 구간 차단
        lunch_start = cfg.get("lunch_block_start", "1200")
        lunch_end   = cfg.get("lunch_block_end",   "1330")
        if lunch_start <= now_str < lunch_end:
            self._last_strategy_name = "blocked(lunch)"
            return None

        # 2. 전략 매칭 (순서대로 AND 조건)
        for strat in cfg.get("strategies", []):
            if self._time_matches(now_str, strat.get("active_times", [])) \
               and self._temp_matches(strat.get("temperatures", "any")):
                profile = self._build_profile(strat)
                self._last_strategy_name = profile.name
                return profile

        # 3. Fallback: adaptive
        adaptive = cfg.get("adaptive", {})
        if adaptive:
            profile = self._build_profile(adaptive)
            self._last_strategy_name = profile.name
            return profile

        # adaptive도 없으면 기본값
        self._last_strategy_name = "adaptive"
        return self._default_profile()

    def get_profile_by_name(self, name):
        """이름으로 전략 프로필 조회 (레짐 기반 선택용)"""
        cfg = self._load_config()
        for s in cfg.get("strategies", []):
            if s.get("name") == name:
                return self._build_profile(s)
        # fallback: momentum은 기본 프로필 생성
        if name == "momentum":
            return self._momentum_default_profile()
        return None

    def _momentum_default_profile(self):
        """모멘텀 기본 프로필"""
        return StrategyProfile(
            name="momentum",
            weights={"momentum_burst": 50, "micro_trend": 30, "orderbook_pressure": 20},
            confidence_threshold=0.50,
            take_profit=1.0,
            stop_loss=-0.4,
            max_hold_seconds=180,
        )

    # ── Private helpers ───────────────────────────────────────

    def _load_config(self) -> dict:
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[StrategySelector] 설정 로드 실패: {e}")
        return {}

    def _time_matches(self, now_str: str, time_ranges: list) -> bool:
        """현재 시각이 active_times 중 하나에 속하는지 확인"""
        for rng in time_ranges:
            if rng["start"] <= now_str < rng["end"]:
                return True
        return False

    def _temp_matches(self, temperatures) -> bool:
        """온도 레벨이 조건에 맞는지 확인"""
        if temperatures == "any":
            return True
        if isinstance(temperatures, list):
            return self._temperature_level in temperatures
        return True

    def _build_profile(self, strat: dict) -> StrategyProfile:
        return StrategyProfile(
            name=strat.get("name", "adaptive"),
            weights=strat.get("signal_weights", {}),
            take_profit=strat.get("take_profit", 1.0),
            stop_loss=strat.get("stop_loss", -0.4),
            confidence_threshold=strat.get("confidence_threshold", 0.45),
            max_hold_seconds=strat.get("max_hold_seconds", 300),
        )

    def _default_profile(self) -> StrategyProfile:
        return StrategyProfile(
            name="adaptive",
            weights={
                "vwap_reversion": 80,
                "orderbook_pressure": 20,
            },
            take_profit=0.6,
            stop_loss=-0.4,
            confidence_threshold=0.45,
            max_hold_seconds=120,
        )
