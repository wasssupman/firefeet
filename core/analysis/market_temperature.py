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

    def _compute_regime(self, components, details, liquidity_data=None):
        """
        기존 모듈 결과(components, details)를 재활용해 regime 벡터 산출.
        liquidity_data: optional dict with "spread_bps" or "volume_ratio".
        예외 발생 시 모두 중립값 반환.
        """
        _DEFAULT = {
            "trend": "SIDEWAYS",
            "volatility": "STABLE",
            "liquidity": "NORMAL",
            "event_risk": "LOW",
        }
        try:
            # --- trend: macro us_index avg_change 기반 ---
            trend = "SIDEWAYS"
            macro_details = details.get("macro", {})
            us_index = macro_details.get("us_index", {})
            trend_info = us_index.get("trend_info", {})
            avg_change = trend_info.get("avg_change")
            if avg_change is not None:
                if avg_change > 0.5:
                    trend = "UPTREND"
                elif avg_change < -0.5:
                    trend = "DOWNTREND"
                else:
                    trend = "SIDEWAYS"

            # --- volatility: macro vix current_price 기반 ---
            volatility = "STABLE"
            vix_details = macro_details.get("vix", {})
            vix_individual = vix_details.get("individual", {})
            vix_data = vix_individual.get("VIX", {})
            vix_price = vix_data.get("current_price")
            if vix_price is not None:
                if vix_price > 25:
                    volatility = "EXPANDING"
                elif vix_price < 15:
                    volatility = "CONTRACTING"
                else:
                    volatility = "STABLE"

            # --- liquidity: 외부 주입 데이터 기반 ---
            liquidity = "NORMAL"
            if liquidity_data:
                spread_bps = liquidity_data.get("spread_bps")
                volume_ratio = liquidity_data.get("volume_ratio")
                if spread_bps is not None:
                    if spread_bps <= 5:
                        liquidity = "HIGH"
                    elif spread_bps <= 15:
                        liquidity = "NORMAL"
                    elif spread_bps <= 30:
                        liquidity = "LOW"
                    else:
                        liquidity = "DRY"
                elif volume_ratio is not None:
                    if volume_ratio >= 3.0:
                        liquidity = "HIGH"
                    elif volume_ratio >= 1.5:
                        liquidity = "NORMAL"
                    elif volume_ratio >= 0.5:
                        liquidity = "LOW"
                    else:
                        liquidity = "DRY"

            # --- event_risk: econ uncertainty pending_events 기반 ---
            event_risk = "LOW"
            econ_details = details.get("econ", {})
            uncertainty = econ_details.get("uncertainty", {})
            pending = uncertainty.get("pending_events", 0)
            if pending >= 2:
                event_risk = "HIGH"
            elif pending == 1:
                event_risk = "MEDIUM"
            else:
                event_risk = "LOW"

            return {
                "trend": trend,
                "volatility": volatility,
                "liquidity": liquidity,
                "event_risk": event_risk,
            }
        except Exception:
            return dict(_DEFAULT)

    def calculate(self, liquidity_data=None):
        """온도 산출. 모든 활성 모듈을 실행하고 가중 합산.

        Args:
            liquidity_data: optional dict with "spread_bps" (float) or "volume_ratio" (float).
        """
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

        # 실패 모듈 과반수 경고
        total_modules = len(self.modules)
        if total_modules > 0 and len(failed) > total_modules / 2:
            warning_msg = (
                f"[MarketTemperature] 온도 모듈 과반수 실패! "
                f"({len(failed)}/{total_modules}): {', '.join(failed)}"
            )
            print(warning_msg)
            try:
                from core.discord_client import DiscordClient
                discord = DiscordClient()
                discord.send_message(f"**온도 모듈 과반수 실패 경고**\n{len(failed)}/{total_modules} 모듈 실패: {', '.join(failed)}\n시장 온도가 부정확할 수 있습니다.")
            except Exception:
                pass

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
                "regime": self._compute_regime({}, {}, liquidity_data),
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

        # 부분 실패 감지: 성공 모듈이 있지만 전부 score=0이고 details도 비어있으면 degraded
        degraded = (
            len(results) > 0 and
            all(r["score"] == 0 and not r.get("details") for r in results.values())
        )

        return {
            "temperature": temperature,
            "level": self._to_level(temperature),
            "components": components,
            "details": details,
            "failed": failed,
            "degraded": degraded,
            "regime": self._compute_regime(components, details, liquidity_data),
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
        if result.get("degraded"):
            lines.append(f"\n🟡 데이터 불완전: 모든 모듈이 score=0 (데이터 소스 응답 없을 수 있음)")
        if result["failed"]:
            lines.append(f"\n⚠️ 실패 모듈: {', '.join(result['failed'])}")

        return "\n".join(lines)


if __name__ == "__main__":
    mt = MarketTemperature()
    print(f"활성 모듈: {list(mt.modules.keys())}")
    result = mt.calculate()
    print(mt.generate_report(result))
