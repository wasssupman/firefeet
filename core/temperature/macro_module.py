from core.temperature.base import TempModule, clamp
from core.analysis.macro import MacroAnalyzer


class MacroModule(TempModule):
    """매크로 추세 온도 모듈 — 미 3대지수, VIX, 환율, 채권"""

    name = "macro"

    SUB_MODULE_SYMBOLS = {
        "us_index": {"나스닥": "^IXIC", "S&P 500": "^GSPC", "다우존스": "^DJI"},
        "vix": {"VIX": "^VIX"},
        "fx": {"원/달러": "USDKRW=X"},
        "bond": {"미 10년물": "^TNX"},
    }

    def calculate(self):
        try:
            analyzer = MacroAnalyzer()
            days = self.config.get("trend_days", 3)
            sub_configs = self.config.get("sub_modules", {})

            total = 0
            details = {}

            for sub_name, symbols in self.SUB_MODULE_SYMBOLS.items():
                sub_cfg = sub_configs.get(sub_name, {})
                if not sub_cfg.get("enabled", sub_name != "bond"):
                    continue

                trends = analyzer.get_trend_group(symbols, days)
                if not trends:
                    continue

                score = self._calc_sub(sub_name, trends, sub_cfg)
                score_range = sub_cfg.get("score_range", [-30, 30])
                clamped = clamp(score, score_range[0], score_range[1])

                # 리포트용 상세 정보
                first_key = next(iter(trends))
                details[sub_name] = {
                    "score": clamped,
                    "label": first_key if len(trends) == 1 else sub_name,
                    "trend_info": trends[first_key] if len(trends) == 1 else {
                        "daily_changes": [
                            round(sum(t["daily_changes"][i] for t in trends.values()) / len(trends), 2)
                            for i in range(len(next(iter(trends.values()))["daily_changes"]))
                        ],
                        "avg_change": round(sum(t["avg_change"] for t in trends.values()) / len(trends), 2),
                        "trend": self._aggregate_trend(trends),
                    },
                    "individual": {name: t for name, t in trends.items()},
                }
                total += clamped

            enabled_count = sum(
                1 for sub_name in self.SUB_MODULE_SYMBOLS
                if sub_configs.get(sub_name, {}).get("enabled", sub_name != "bond")
            )
            if enabled_count > 0 and len(details) == 0:
                return {"score": 0, "details": {}, "error": "모든 매크로 데이터 소스 응답 없음"}
            return {"score": clamp(total, -100, 100), "details": details, "error": None}

        except Exception as e:
            return {"score": 0, "details": {}, "error": str(e)}

    def _calc_sub(self, sub_name, trends, sub_cfg):
        dispatch = {
            "us_index": self._calc_us_index,
            "vix": self._calc_vix,
            "fx": self._calc_fx,
            "bond": self._calc_bond,
        }
        fn = dispatch.get(sub_name)
        if fn:
            return fn(trends, sub_cfg)
        return 0

    def _calc_us_index(self, trends, sub_cfg):
        """미 3대지수 — 3일 평균 등락률 기반"""
        multiplier = sub_cfg.get("multiplier", 20)
        avg_changes = [t["avg_change"] for t in trends.values()]
        us_avg = sum(avg_changes) / len(avg_changes) if avg_changes else 0
        return us_avg * multiplier

    def _calc_vix(self, trends, sub_cfg):
        """VIX — 절대 레벨 + 추세 방향"""
        vix = trends.get("VIX")
        if not vix:
            return 0

        price = vix["current_price"]
        thresholds = sub_cfg.get("level_thresholds", {})

        extreme = thresholds.get("extreme_fear", 30)
        fear = thresholds.get("fear", 25)
        normal = thresholds.get("normal", 18)
        calm = thresholds.get("calm", 12)

        if price > extreme:
            level_score = -20
        elif price > fear:
            level_score = -10
        elif price > normal:
            level_score = 0
        elif price > calm:
            level_score = 10
        else:
            level_score = 20

        trend_mult = sub_cfg.get("trend_multiplier", 5)
        trend_score = clamp(-vix["avg_change"] * trend_mult, -10, 10)

        return level_score + trend_score

    def _calc_fx(self, trends, sub_cfg):
        """원/달러 — 환율 하락(원화 강세) = 긍정"""
        fx = trends.get("원/달러")
        if not fx:
            return 0
        multiplier = sub_cfg.get("multiplier", 10)
        invert = -1 if sub_cfg.get("invert", True) else 1
        return fx["avg_change"] * multiplier * invert

    def _calc_bond(self, trends, sub_cfg):
        """미 10년물 — 금리 하락 = 주식에 긍정"""
        bond = trends.get("미 10년물")
        if not bond:
            return 0
        multiplier = sub_cfg.get("multiplier", 5)
        invert = -1 if sub_cfg.get("invert", True) else 1
        return bond["avg_change"] * multiplier * invert

    def _aggregate_trend(self, trends):
        """여러 심볼의 추세를 종합"""
        ups = sum(1 for t in trends.values() if t["trend"] == "UP")
        downs = sum(1 for t in trends.values() if t["trend"] == "DOWN")
        if ups > downs:
            return "UP"
        elif downs > ups:
            return "DOWN"
        return "FLAT"
