import yaml
import os
from core.temperature.base import clamp
from core.temperature.macro_module import MacroModule
from core.temperature.sentiment_module import SentimentModule
from core.temperature.econ_module import EconModule


class MarketTemperature:
    """
    시장 온도 산출 오케스트레이터.
    config에서 활성화된 모듈만 로드하고, 가중 합산한다.
    모듈 실패 시 해당 모듈 제외 + 나머지 가중치 재배분.
    """

    MODULE_REGISTRY = {
        "macro": MacroModule,
        "sentiment": SentimentModule,
        "econ": EconModule,
    }

    def __init__(self, config_path="config/temperature_config.yaml"):
        self.config = self._load_config(config_path)
        self.modules = self._init_modules()

    def _load_config(self, path):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[Temperature] Config load failed: {e}")
        return {}

    def _init_modules(self):
        modules = {}
        for name, cls in self.MODULE_REGISTRY.items():
            mod_config = self.config.get("modules", {}).get(name, {})
            if mod_config.get("enabled", False):
                modules[name] = cls(mod_config)
        return modules

    def _to_level(self, temp):
        thresholds = self.config.get("level_thresholds", {})
        levels = [
            (thresholds.get("HOT", 70), "HOT"),
            (thresholds.get("WARM", 40), "WARM"),
            (thresholds.get("NEUTRAL", -20), "NEUTRAL"),
            (thresholds.get("COOL", -60), "COOL"),
        ]
        for threshold, level in levels:
            if temp >= threshold:
                return level
        return "COLD"

    def calculate(self):
        """온도 산출. 모든 활성 모듈을 실행하고 가중 합산."""
        results = {}
        failed = []

        for name, module in self.modules.items():
            try:
                result = module.calculate()
                if result.get("error"):
                    failed.append(name)
                    print(f"[Temperature] {name} 모듈 실패: {result['error']}")
                else:
                    results[name] = result
            except Exception as e:
                failed.append(name)
                print(f"[Temperature] {name} 모듈 예외: {e}")

        # 활성 모듈만 가중치 재배분
        active_weights = {name: self.modules[name].weight for name in results}
        total_weight = sum(active_weights.values())

        if total_weight == 0:
            return {
                "temperature": 0,
                "level": "NEUTRAL",
                "components": {},
                "details": {},
                "failed": failed,
            }

        temperature = 0
        for name, result in results.items():
            normalized_weight = active_weights[name] / total_weight
            temperature += result["score"] * normalized_weight

        temperature = round(clamp(temperature, -100, 100), 1)

        # --- AI Macro Sentinel Override ---
        ai_override_info = {}
        ai_config = self.config.get("modules", {}).get("ai_macro", {})
        if ai_config.get("enabled", False):
            try:
                from core.temperature.ai_macro_module import AIMacroModule
                ai_macro = AIMacroModule(ai_config)
                override = ai_macro.evaluate_override(temperature)
                
                mult = override.get("multiplier", 1.0)
                
                # Apply narrative multiplier (and re-clamp just in case)
                temperature = round(clamp(temperature * mult, -100, 100), 1)
                ai_override_info = override
                print(f"[Temperature] AI Macro Override Applied: Mult={mult} -> New Temp={temperature}")
            except Exception as e:
                print(f"[Temperature] AIMacroModule Error: {e}")

        components = {name: r["score"] for name, r in results.items()}
        details = {name: r.get("details", {}) for name, r in results.items()}
        
        if ai_override_info:
            details["ai_macro"] = ai_override_info

        return {
            "temperature": temperature,
            "level": self._to_level(temperature),
            "components": components,
            "details": details,
            "failed": failed,
        }

    def generate_report(self, result=None):
        """Discord/콘솔용 온도 리포트 생성"""
        if result is None:
            result = self.calculate()

        temp = result["temperature"]
        level = result["level"]
        level_emoji = {"HOT": "🔴", "WARM": "🟠", "NEUTRAL": "⚪", "COOL": "🔵", "COLD": "🟣"}.get(level, "⚪")

        lines = [f"🌡️ **시장 온도: {temp:+.1f} ({level_emoji} {level})**\n"]

        # 매크로
        if "macro" in result["components"]:
            score = result["components"]["macro"]
            details = result.get("details", {}).get("macro", {})
            lines.append(f"📊 매크로 추세 [{score:+.0f}]")
            for sub_name, sub_data in details.items():
                if isinstance(sub_data, dict) and "trend_info" in sub_data:
                    info = sub_data["trend_info"]
                    changes_str = ", ".join(f"{c:+.2f}%" for c in info.get("daily_changes", []))
                    trend_arrow = {"UP": "↑", "DOWN": "↓", "FLAT": "→"}.get(info.get("trend", ""), "")
                    lines.append(f"  {sub_data.get('label', sub_name)}: {changes_str} ({trend_arrow})")

        # 감성
        if "sentiment" in result["components"]:
            score = result["components"]["sentiment"]
            details = result.get("details", {}).get("sentiment", {})
            trend = details.get("trend", "STABLE")
            lines.append(f"\n📰 뉴스 감성 [{score:+.0f}]")
            sources = details.get("sources", {})
            for src, daily in sources.items():
                if isinstance(daily, dict):
                    label = "한국 뉴스" if src == "naver_news" else "해외 뉴스"
                    bull = daily.get("total_bull", 0)
                    bear = daily.get("total_bear", 0)
                    lines.append(f"  {label}: 긍정 {bull}건 / 부정 {bear}건")
            lines.append(f"  추세: {trend}")

        # 경제 지표
        if "econ" in result["components"]:
            score = result["components"]["econ"]
            details = result.get("details", {}).get("econ", {})
            lines.append(f"\n📅 경제 지표 [{score:+.0f}]")
            surprise = details.get("surprise", {})
            for item in surprise.get("items", [])[:3]:
                unit = item.get("unit", "pct")
                if unit in ("pct", "index"):
                    unit_label = "pt" if unit == "index" else "%p"
                    # 역산: surprise_val = diff * scale → diff = surprise_val / scale
                    scale = 10.0 if unit == "pct" else 2.0
                    diff = item["surprise"] / scale if scale else item["surprise"]
                    lines.append(f"  {item['name']}: 실제 {item['actual']} vs 예상 {item['forecast']} ({diff:+.1f}{unit_label})")
                else:
                    lines.append(f"  {item['name']}: 실제 {item['actual']} vs 예상 {item['forecast']} ({item['surprise']:+.1f}%)")
            uncertainty = details.get("uncertainty", {})
            pending = uncertainty.get("pending_events", 0)
            if pending > 0:
                lines.append(f"  오늘 미발표 고중요도: {pending}건")

        # 실패 모듈
        if result["failed"]:
            lines.append(f"\n⚠️ 실패 모듈: {', '.join(result['failed'])}")

        return "\n".join(lines)


if __name__ == "__main__":
    mt = MarketTemperature()
    print(f"활성 모듈: {list(mt.modules.keys())}")
    result = mt.calculate()
    print(mt.generate_report(result))
