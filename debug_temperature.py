"""시장 온도 도출 과정 상세 디버그 출력"""

import yaml
import datetime
from core.analysis.market_temperature import MarketTemperature
from core.temperature.base import clamp
from core.temperature.econ_module import parse_number
from core.analysis.macro import MacroAnalyzer
from core.news_scraper import NewsScraper
from core.news_analyzer import NewsAnalyzer
from core.econ_calendar import EconCalendar


def sep(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main():
    mt = MarketTemperature()
    config = mt.config
    modules_cfg = config.get("modules", {})

    print("=" * 60)
    print("  시장 온도 상세 도출 과정")
    print("=" * 60)
    print(f"  시각: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  활성 모듈: {list(mt.modules.keys())}")
    print(f"  설정 가중치: macro={modules_cfg.get('macro',{}).get('weight')}, "
          f"sentiment={modules_cfg.get('sentiment',{}).get('weight')}, "
          f"econ={modules_cfg.get('econ',{}).get('weight')}")

    results = {}
    failed = []

    # ────────────────────────────────────────
    # 1. MACRO MODULE
    # ────────────────────────────────────────
    sep("1. 매크로 추세 모듈 (weight=40)")

    macro_cfg = modules_cfg.get("macro", {})
    sub_cfgs = macro_cfg.get("sub_modules", {})
    days = macro_cfg.get("trend_days", 3)
    print(f"  trend_days: {days}")

    analyzer = MacroAnalyzer()

    from core.temperature.macro_module import MacroModule
    symbol_map = MacroModule.SUB_MODULE_SYMBOLS

    macro_total = 0
    for sub_name, symbols in symbol_map.items():
        sub_cfg = sub_cfgs.get(sub_name, {})
        enabled = sub_cfg.get("enabled", sub_name != "bond")
        if not enabled:
            print(f"\n  [{sub_name}] DISABLED — 스킵")
            continue

        score_range = sub_cfg.get("score_range", [-30, 30])
        print(f"\n  [{sub_name}] enabled=True, score_range={score_range}")

        trends = analyzer.get_trend_group(symbols, days)
        if not trends:
            print(f"    데이터 없음 — 스킵")
            continue

        for label, t in trends.items():
            changes_str = ", ".join(f"{c:+.2f}%" for c in t["daily_changes"])
            print(f"    {label}: 현재 {t['current_price']:.2f}")
            print(f"      일별 변화: [{changes_str}]")
            print(f"      평균 변화: {t['avg_change']:+.4f}%")
            print(f"      추세: {t['trend']} (연속 {t['streak']}일)")

        # 점수 계산 상세
        if sub_name == "us_index":
            multiplier = sub_cfg.get("multiplier", 20)
            avg_changes = [t["avg_change"] for t in trends.values()]
            us_avg = sum(avg_changes) / len(avg_changes)
            raw = us_avg * multiplier
            clamped = clamp(raw, score_range[0], score_range[1])
            print(f"    계산: avg({[round(c,4) for c in avg_changes]}) = {us_avg:.4f}")
            print(f"    점수: {us_avg:.4f} × {multiplier} = {raw:.2f} → clamp{score_range} = {clamped:.2f}")

        elif sub_name == "vix":
            vix = trends.get("VIX")
            if vix:
                price = vix["current_price"]
                thresholds = sub_cfg.get("level_thresholds", {})
                extreme = thresholds.get("extreme_fear", 30)
                fear = thresholds.get("fear", 25)
                normal = thresholds.get("normal", 18)
                calm = thresholds.get("calm", 12)

                if price > extreme: level_score = -20
                elif price > fear: level_score = -10
                elif price > normal: level_score = 0
                elif price > calm: level_score = 10
                else: level_score = 20

                print(f"    레벨 판정: {price:.1f} → extreme>{extreme}, fear>{fear}, normal>{normal}, calm>{calm}")
                print(f"    레벨 점수: {level_score}")

                trend_mult = sub_cfg.get("trend_multiplier", 5)
                trend_score = clamp(-vix["avg_change"] * trend_mult, -10, 10)
                print(f"    추세 점수: -{vix['avg_change']:.4f} × {trend_mult} = {-vix['avg_change'] * trend_mult:.2f} → clamp[-10,10] = {trend_score:.2f}")

                raw = level_score + trend_score
                clamped = clamp(raw, score_range[0], score_range[1])
                print(f"    합산: {level_score} + {trend_score:.2f} = {raw:.2f} → clamp{score_range} = {clamped:.2f}")

        elif sub_name == "fx":
            fx = trends.get("원/달러")
            if fx:
                multiplier = sub_cfg.get("multiplier", 10)
                invert = -1 if sub_cfg.get("invert", True) else 1
                raw = fx["avg_change"] * multiplier * invert
                clamped = clamp(raw, score_range[0], score_range[1])
                print(f"    계산: {fx['avg_change']:.4f} × {multiplier} × {invert}(invert) = {raw:.2f} → clamp{score_range} = {clamped:.2f}")

        elif sub_name == "bond":
            bond = trends.get("미 10년물")
            if bond:
                multiplier = sub_cfg.get("multiplier", 5)
                invert = -1 if sub_cfg.get("invert", True) else 1
                raw = bond["avg_change"] * multiplier * invert
                clamped = clamp(raw, score_range[0], score_range[1])
                print(f"    계산: {bond['avg_change']:.4f} × {multiplier} × {invert}(invert) = {raw:.2f} → clamp{score_range} = {clamped:.2f}")

        # macro_total에 clamped 합산
        macro_total += clamped

    macro_score = clamp(macro_total, -100, 100)
    print(f"\n  ▶ 매크로 총점: {macro_total:.2f} → clamp[-100,100] = {macro_score:.1f}")
    results["macro"] = macro_score

    # ────────────────────────────────────────
    # 2. SENTIMENT MODULE
    # ────────────────────────────────────────
    sep("2. 뉴스 감성 모듈 (weight=35)")

    sent_cfg = modules_cfg.get("sentiment", {})
    sent_days = sent_cfg.get("days", 3)
    day_weights = sent_cfg.get("day_weights", [0.5, 0.3, 0.2])
    trend_threshold = sent_cfg.get("trend_threshold", 10)
    sent_sub = sent_cfg.get("sub_modules", {})

    print(f"  days: {sent_days}, day_weights: {day_weights}, trend_threshold: {trend_threshold}")

    daily_scores = {}
    active_sources = 0

    # 네이버 뉴스
    naver_cfg = sent_sub.get("naver_news", {})
    if naver_cfg.get("enabled", True):
        active_sources += 1
        print(f"\n  [naver_news] enabled=True")
        scraper = NewsScraper()
        pages = naver_cfg.get("pages_per_day", 3)
        bullish_kw = naver_cfg.get("bullish_keywords", [])
        bearish_kw = naver_cfg.get("bearish_keywords", [])
        print(f"    pages_per_day: {pages}")
        print(f"    bullish keywords ({len(bullish_kw)}개): {bullish_kw}")
        print(f"    bearish keywords ({len(bearish_kw)}개): {bearish_kw}")

        naver_total_bull = 0
        naver_total_bear = 0
        naver_daily = {}

        for i in range(sent_days):
            date = datetime.date.today() - datetime.timedelta(days=i)
            date_str = date.strftime("%Y%m%d")
            date_iso = date.isoformat()
            titles = scraper.fetch_news_by_date(date_str, pages=pages)
            text = " ".join(titles)
            bull = sum(text.count(kw) for kw in bullish_kw)
            bear = sum(text.count(kw) for kw in bearish_kw)
            total = bull + bear
            score = ((bull - bear) / total * 100) if total > 0 else 0
            naver_daily[date_iso] = score
            naver_total_bull += bull
            naver_total_bear += bear
            daily_scores[date_iso] = daily_scores.get(date_iso, 0) + score
            print(f"    {date_iso}: 기사 {len(titles)}건 → 긍정 {bull} / 부정 {bear} → 점수 {score:.1f}")

        print(f"    합계: 긍정 {naver_total_bull}건, 부정 {naver_total_bear}건")

    # 글로벌 뉴스
    global_cfg = sent_sub.get("global_news", {})
    if global_cfg.get("enabled", True):
        active_sources += 1
        print(f"\n  [global_news] enabled=True")
        na = NewsAnalyzer()
        g_bullish = global_cfg.get("bullish_keywords", [])
        g_bearish = global_cfg.get("bearish_keywords", [])
        print(f"    bullish keywords: {g_bullish}")
        print(f"    bearish keywords: {g_bearish}")

        titles = na.fetch_global_news_titles(limit=30)
        text = " ".join(titles).lower()
        bull = sum(text.count(kw.lower()) for kw in g_bullish)
        bear = sum(text.count(kw.lower()) for kw in g_bearish)
        total = bull + bear
        g_score = ((bull - bear) / total * 100) if total > 0 else 0
        print(f"    기사 {len(titles)}건 → 긍정 {bull} / 부정 {bear} → 점수 {g_score:.1f}")

        today = datetime.date.today().isoformat()
        daily_scores[today] = daily_scores.get(today, 0) + g_score

    # 소스 평균
    if active_sources > 1:
        print(f"\n  소스 수: {active_sources} → 일별 점수 평균 처리")
        daily_scores = {d: v / active_sources for d, v in daily_scores.items()}

    print(f"\n  일별 점수 (소스 평균 후):")
    sorted_dates = sorted(daily_scores.keys(), reverse=True)
    for d in sorted_dates:
        print(f"    {d}: {daily_scores[d]:.2f}")

    # 가중 평균
    weighted_sum = 0
    weight_sum = 0
    print(f"\n  날짜별 가중 평균 계산:")
    for i, date in enumerate(sorted_dates[:len(day_weights)]):
        w = day_weights[i] if i < len(day_weights) else day_weights[-1]
        val = daily_scores[date]
        weighted_sum += val * w
        weight_sum += w
        print(f"    {date}: {val:.2f} × {w} = {val * w:.2f}")

    sentiment_score = weighted_sum / weight_sum if weight_sum > 0 else 0
    sentiment_score = clamp(round(sentiment_score, 1), -100, 100)
    print(f"  가중합: {weighted_sum:.2f} / 가중치합: {weight_sum:.2f} = {weighted_sum / weight_sum if weight_sum else 0:.2f}")

    # 추세
    trend = "STABLE"
    if len(sorted_dates) >= 2:
        today_s = daily_scores[sorted_dates[0]]
        yest_s = daily_scores[sorted_dates[1]]
        diff = today_s - yest_s
        if diff > trend_threshold: trend = "IMPROVING"
        elif diff < -trend_threshold: trend = "WORSENING"
        print(f"  추세: {sorted_dates[0]}({today_s:.1f}) - {sorted_dates[1]}({yest_s:.1f}) = {diff:+.1f} → {trend} (threshold={trend_threshold})")

    print(f"\n  ▶ 감성 총점: {sentiment_score}")
    results["sentiment"] = sentiment_score

    # ────────────────────────────────────────
    # 3. ECON MODULE
    # ────────────────────────────────────────
    sep("3. 경제 지표 모듈 (weight=25)")

    econ_cfg = modules_cfg.get("econ", {})
    econ_sub = econ_cfg.get("sub_modules", {})

    calendar = EconCalendar()
    events = calendar.fetch_all()
    print(f"  수집된 이벤트: {len(events)}건")
    for e in events:
        print(f"    {e['target_name']:20s} | {e['name']}")
        print(f"      actual={e['actual']:>10s} | forecast={e.get('forecast','-'):>10s} | "
              f"importance={e['importance']} | unit={e.get('unit','pct')}")

    # 서프라이즈
    surprise_cfg = econ_sub.get("surprise", {})
    if surprise_cfg.get("enabled", True):
        print(f"\n  [surprise] enabled=True")
        importance_mult = surprise_cfg.get("importance_multiplier", {"high": 3, "medium": 2, "low": 1})
        score_range = surprise_cfg.get("score_range", [-60, 60])
        print(f"    importance_multiplier: {importance_mult}")
        print(f"    score_range: {score_range}")

        released = [e for e in events if e.get('actual') and e['actual'] != '-']
        surprise_total = 0

        for e in released:
            actual = parse_number(e['actual'])
            forecast = parse_number(e.get('forecast'))
            if actual is None or forecast is None:
                print(f"    {e['target_name']}: 파싱 실패 (actual={actual}, forecast={forecast}) → 스킵")
                continue

            unit = e.get('unit', 'pct')
            if unit in ('pct', 'index'):
                diff = actual - forecast
                scale = {"pct": 10.0, "index": 2.0}.get(unit, 10.0)
                surprise_val = diff * scale
                print(f"    {e['target_name']} ({e['name']}): "
                      f"actual={actual} - forecast={forecast} = {diff:+.4f} → × {scale} = {surprise_val:+.2f}")
            else:
                if forecast == 0:
                    print(f"    {e['target_name']}: forecast=0 → 스킵")
                    continue
                ratio = (actual - forecast) / abs(forecast) * 100
                surprise_val = clamp(ratio, -50, 50)
                print(f"    {e['target_name']} ({e['name']}): "
                      f"({actual} - {forecast}) / |{forecast}| × 100 = {ratio:+.1f}% → cap±50 = {surprise_val:+.1f}")

            weight = importance_mult.get(e.get('importance', 'low'), 1)
            contribution = clamp(surprise_val * weight, -20, 20)
            surprise_total += contribution
            print(f"      importance={e['importance']}(×{weight}) → contribution: {surprise_val:+.2f} × {weight} = {surprise_val * weight:+.2f} → clamp[-20,20] = {contribution:+.2f}")

        surprise_score = clamp(round(surprise_total, 1), score_range[0], score_range[1])
        print(f"    서프라이즈 합산: {surprise_total:.2f} → clamp{score_range} = {surprise_score:.1f}")

    # 불확실성
    uncertainty_cfg = econ_sub.get("uncertainty", {})
    uncertainty_score = 0
    if uncertainty_cfg.get("enabled", True):
        print(f"\n  [uncertainty] enabled=True")
        penalty_per = uncertainty_cfg.get("penalty_per_event", -10)
        unc_range = uncertainty_cfg.get("score_range", [-40, 0])
        today = datetime.date.today().isoformat()

        today_high = [
            e for e in events
            if e.get('date') == today
            and e.get('importance') == 'high'
            and (not e.get('actual') or e['actual'] == '-')
        ]
        penalty = penalty_per * len(today_high)
        uncertainty_score = clamp(penalty, unc_range[0], unc_range[1])
        print(f"    오늘({today}) 미발표 high importance: {len(today_high)}건")
        for e in today_high:
            print(f"      - {e['target_name']} ({e['name']})")
        print(f"    페널티: {penalty_per} × {len(today_high)} = {penalty} → clamp{unc_range} = {uncertainty_score}")

    econ_score = clamp(round(surprise_score + uncertainty_score, 1), -100, 100)
    print(f"\n  ▶ 경제 지표 총점: {surprise_score} + {uncertainty_score} = {surprise_score + uncertainty_score} → clamp[-100,100] = {econ_score}")
    results["econ"] = econ_score

    # ────────────────────────────────────────
    # 최종 합산
    # ────────────────────────────────────────
    sep("최종 온도 합산")

    weights = {
        "macro": modules_cfg.get("macro", {}).get("weight", 40),
        "sentiment": modules_cfg.get("sentiment", {}).get("weight", 35),
        "econ": modules_cfg.get("econ", {}).get("weight", 25),
    }
    active_weights = {k: weights[k] for k in results}
    total_weight = sum(active_weights.values())

    print(f"  활성 가중치: {active_weights}")
    print(f"  가중치 합계: {total_weight}")
    print()

    temperature = 0
    for name, score in results.items():
        norm_w = active_weights[name] / total_weight
        contrib = score * norm_w
        temperature += contrib
        print(f"  {name:12s}: 점수 {score:+7.1f} × (가중치 {active_weights[name]}/{total_weight} = {norm_w:.4f}) = {contrib:+.2f}")

    temperature = round(clamp(temperature, -100, 100), 1)

    # 레벨 판정
    thresholds = config.get("level_thresholds", {})
    levels = [
        (thresholds.get("HOT", 70), "HOT"),
        (thresholds.get("WARM", 40), "WARM"),
        (thresholds.get("NEUTRAL", -20), "NEUTRAL"),
        (thresholds.get("COOL", -60), "COOL"),
    ]
    level = "COLD"
    for threshold, lv in levels:
        if temperature >= threshold:
            level = lv
            break

    print(f"\n  합산: {temperature:+.1f}")
    print(f"  레벨 판정: {temperature:+.1f} → {levels} → {level}")

    # 전략 프로파일
    profiles = config.get("strategy_profiles", {})
    profile = profiles.get(level, {})
    print(f"\n  전략 프로파일 ({level}): {profile}")

    sep(f"결과: 온도 {temperature:+.1f} ({level})")


if __name__ == "__main__":
    main()
