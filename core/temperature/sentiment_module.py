import datetime
from core.temperature.base import TempModule, clamp
from core.news_scraper import NewsScraper
from core.news_analyzer import NewsAnalyzer


class SentimentModule(TempModule):
    """뉴스/커뮤니티 감성 온도 모듈 — 네이버 뉴스 + MarketWatch"""

    name = "sentiment"

    def calculate(self):
        try:
            days = self.config.get("days", 3)
            day_weights = self.config.get("day_weights", [0.5, 0.3, 0.2])
            trend_threshold = self.config.get("trend_threshold", 10)
            sub_configs = self.config.get("sub_modules", {})

            daily_scores = {}
            source_details = {}

            active_sources = 0

            # 네이버 뉴스
            naver_cfg = sub_configs.get("naver_news", {})
            if naver_cfg.get("enabled", True):
                active_sources += 1
                naver_result = self._process_naver(days, naver_cfg)
                source_details["naver_news"] = naver_result
                for date, score in naver_result["daily_scores"].items():
                    daily_scores[date] = daily_scores.get(date, 0) + score

            # 글로벌 뉴스
            global_cfg = sub_configs.get("global_news", {})
            if global_cfg.get("enabled", True):
                active_sources += 1
                global_result = self._process_global(global_cfg)
                source_details["global_news"] = global_result
                # MarketWatch는 날짜 구분 없이 최근 기사 → 오늘 날짜에 합산
                today = datetime.date.today().isoformat()
                daily_scores[today] = daily_scores.get(today, 0) + global_result["score"]

            # 모든 소스에서 기사 0건이면 에러 전파
            total_articles = sum(
                s.get("total_bull", 0) + s.get("total_bear", 0)
                for s in source_details.values()
            )
            if active_sources > 0 and total_articles == 0:
                return {"score": 0, "details": {}, "error": "뉴스 데이터 수집 실패 (0건)"}

            # 소스가 여러 개면 평균
            if active_sources > 1:
                daily_scores = {d: v / active_sources for d, v in daily_scores.items()}

            # 날짜별 가중 평균
            sorted_dates = sorted(daily_scores.keys(), reverse=True)
            weighted_sum = 0
            weight_sum = 0
            for i, date in enumerate(sorted_dates[:len(day_weights)]):
                w = day_weights[i] if i < len(day_weights) else day_weights[-1]
                weighted_sum += daily_scores[date] * w
                weight_sum += w

            score = weighted_sum / weight_sum if weight_sum > 0 else 0

            # 추세 판단
            trend = "STABLE"
            if len(sorted_dates) >= 2:
                today_score = daily_scores[sorted_dates[0]]
                yesterday_score = daily_scores[sorted_dates[1]]
                diff = today_score - yesterday_score
                if diff > trend_threshold:
                    trend = "IMPROVING"
                elif diff < -trend_threshold:
                    trend = "WORSENING"

            return {
                "score": clamp(round(score, 1), -100, 100),
                "details": {
                    "daily": daily_scores,
                    "trend": trend,
                    "sources": source_details,
                },
                "error": None,
            }

        except Exception as e:
            return {"score": 0, "details": {}, "error": str(e)}

    def _process_naver(self, days, cfg):
        """네이버 뉴스 날짜별 감성 분석"""
        scraper = NewsScraper()
        pages = cfg.get("pages_per_day", 3)
        bullish = cfg.get("bullish_keywords", [])
        bearish = cfg.get("bearish_keywords", [])

        daily_scores = {}
        total_bull = 0
        total_bear = 0

        for i in range(days):
            date = datetime.date.today() - datetime.timedelta(days=i)
            date_str = date.strftime("%Y%m%d")
            date_iso = date.isoformat()

            titles = scraper.fetch_news_by_date(date_str, pages=pages)
            text = " ".join(titles)

            bull = sum(text.count(kw) for kw in bullish)
            bear = sum(text.count(kw) for kw in bearish)
            total_bull += bull
            total_bear += bear

            total = bull + bear
            daily_scores[date_iso] = ((bull - bear) / total * 100) if total > 0 else 0

        return {
            "daily_scores": daily_scores,
            "total_bull": total_bull,
            "total_bear": total_bear,
            "score": sum(daily_scores.values()) / len(daily_scores) if daily_scores else 0,
        }

    def _process_global(self, cfg):
        """MarketWatch 글로벌 뉴스 감성 분석"""
        analyzer = NewsAnalyzer()
        bullish = cfg.get("bullish_keywords", [])
        bearish = cfg.get("bearish_keywords", [])

        titles = analyzer.fetch_global_news_titles(limit=30)
        text = " ".join(titles).lower()

        bull = sum(text.count(kw.lower()) for kw in bullish)
        bear = sum(text.count(kw.lower()) for kw in bearish)
        total = bull + bear

        score = ((bull - bear) / total * 100) if total > 0 else 0

        return {
            "total_bull": bull,
            "total_bear": bear,
            "score": round(score, 1),
        }
