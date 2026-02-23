import re
import datetime
from core.temperature.base import TempModule, clamp
from core.econ_calendar import EconCalendar


def parse_number(s):
    """숫자 문자열 파싱 — '%', ',', 'K', 'M' 등 처리"""
    if not s or s == '-':
        return None
    s = s.strip().replace(',', '').replace('%', '').replace('$', '')
    # 'K' / 'M' suffix
    multiplier = 1
    if s.upper().endswith('K'):
        s = s[:-1]
        multiplier = 1000
    elif s.upper().endswith('M'):
        s = s[:-1]
        multiplier = 1000000
    try:
        return float(s) * multiplier
    except ValueError:
        return None


class EconModule(TempModule):
    """경제 지표 온도 모듈 — 서프라이즈 분석 + 불확실성 페널티"""

    name = "econ"

    def calculate(self):
        try:
            calendar = EconCalendar()
            events = calendar.fetch_all()
            sub_configs = self.config.get("sub_modules", {})

            score = 0
            details = {}

            # 서프라이즈 분석
            surprise_cfg = sub_configs.get("surprise", {})
            if surprise_cfg.get("enabled", True):
                surprise = self._calc_surprise(events, surprise_cfg)
                score += surprise["score"]
                details["surprise"] = surprise

            # 불확실성 분석
            uncertainty_cfg = sub_configs.get("uncertainty", {})
            if uncertainty_cfg.get("enabled", True):
                uncertainty = self._calc_uncertainty(events, uncertainty_cfg)
                score += uncertainty["score"]
                details["uncertainty"] = uncertainty

            return {"score": clamp(round(score, 1), -100, 100), "details": details, "error": None}

        except Exception as e:
            return {"score": 0, "details": {}, "error": str(e)}

    def _calc_surprise(self, events, cfg):
        """
        최근 발표 결과의 서프라이즈 점수.

        단위별 계산 방식:
        - pct / index: 차이 기반. (actual - forecast) 자체가 서프라이즈.
          예) CPI 실제 0.3% vs 예상 0.2% → +0.1%p → 스코어 +0.1 * 스케일
          예) ISM 실제 52.1 vs 예상 50.5 → +1.6pt → 스코어 +1.6 * 스케일
        - abs: 비율 기반이되 ±50% 캡.
          예) NFP 실제 130K vs 예상 55K → +136% → 캡 → +50%
        """
        released = [e for e in events if e.get('actual') and e['actual'] != '-']
        importance_mult = cfg.get("importance_multiplier", {"high": 3, "medium": 2, "low": 1})
        score_range = cfg.get("score_range", [-60, 60])

        # 단위별 스케일링 팩터 (차이값 → 점수 변환 비율)
        DIFF_SCALE = {
            "pct": 10.0,    # 0.1%p 차이 → 1점
            "index": 2.0,   # 1pt 차이 → 2점
        }
        ABS_RATIO_CAP = 50  # 비율 방식 최대 ±50%

        total_score = 0
        items = []

        for e in released:
            actual = parse_number(e['actual'])
            forecast = parse_number(e.get('forecast'))
            if actual is None or forecast is None:
                continue

            unit = e.get('unit', 'pct')

            if unit in ('pct', 'index'):
                # 차이 기반: actual - forecast (원래 단위 그대로)
                diff = actual - forecast
                scale = DIFF_SCALE.get(unit, 10.0)
                surprise_val = diff * scale
            else:
                # 비율 기반 (abs 등): forecast가 0이면 스킵
                if forecast == 0:
                    continue
                ratio = (actual - forecast) / abs(forecast) * 100
                surprise_val = clamp(ratio, -ABS_RATIO_CAP, ABS_RATIO_CAP)

            weight = importance_mult.get(e.get('importance', 'low'), 1)
            contribution = clamp(surprise_val * weight, -20, 20)
            total_score += contribution
            items.append({
                "name": e.get('target_name', e.get('name', 'Unknown')),
                "actual": e['actual'],
                "forecast": e.get('forecast', '-'),
                "unit": unit,
                "surprise": round(surprise_val, 1),
                "contribution": round(contribution, 1),
            })

        return {
            "score": clamp(round(total_score, 1), score_range[0], score_range[1]),
            "items": items,
        }

    def _calc_uncertainty(self, events, cfg):
        """오늘 미발표 고중요도 이벤트 → 불확실성 페널티 (target_name 기준 그룹핑)"""
        today = datetime.date.today().isoformat()
        penalty_per = cfg.get("penalty_per_event", -10)
        score_range = cfg.get("score_range", [-40, 0])

        today_high = [
            e for e in events
            if e.get('date') == today
            and e.get('importance') == 'high'
            and (not e.get('actual') or e['actual'] == '-')
        ]
        # CPI 4건 → 1건 등, 같은 지표의 세부 항목을 하나로 카운트
        unique_names = list(dict.fromkeys(
            e.get('target_name', e.get('name', '')) for e in today_high
        ))
        penalty = penalty_per * len(unique_names)

        return {
            "score": clamp(penalty, score_range[0], score_range[1]),
            "pending_events": len(unique_names),
            "event_names": unique_names,
        }
