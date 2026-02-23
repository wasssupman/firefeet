import requests
from bs4 import BeautifulSoup
import datetime

class NewsAnalyzer:
    """
    글로벌 경제 뉴스 분석기.
    - 주요 외신(MarketWatch, Reuters 등) 뉴스 수집
    - Reddit API 미연동 시 글로벌 투자 심리 파악용 Fallback
    """
    
    BASE_URLS = [
        "https://www.marketwatch.com/latest-news",
        # "https://www.reuters.com/business/" # 추가 시 헤더 및 파서 대응 필요
    ]

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5"
        }

    def fetch_global_news(self, limit=10):
        """
        MarketWatch 등에서 최신 경제 뉴스를 스크랩합니다.
        """
        news_items = []
        try:
            # MarketWatch Latest News Scraping
            res = requests.get(self.BASE_URLS[0], headers=self.headers, timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'html.parser')

            # MarketWatch article structure: h3.article__headline
            articles = soup.select('.article__content')
            for article in articles[:limit]:
                title_tag = article.select_one('.article__headline a')
                if not title_tag: continue
                
                title = title_tag.text.strip()
                link = title_tag['href']
                summary = ""
                summary_tag = article.select_one('.article__summary')
                if summary_tag:
                    summary = summary_tag.text.strip()

                news_items.append({
                    "source": "MarketWatch",
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                })

        except Exception as e:
            print(f"[NewsAnalyzer] Error fetching news: {e}")
            
        return news_items

    def generate_report_section(self):
        """리포트용 뉴스 섹션 생성"""
        news = self.fetch_global_news(limit=5)
        if not news:
            return "## 🌐 글로벌 경제 뉴스\n- 최신 뉴스를 가져올 수 없습니다.\n"

        lines = ["## 🌐 글로벌 경제 뉴스 (NewsAnalyzer)\n"]
        for item in news:
            lines.append(f"- **{item['title']}** ({item['source']})")
            if item['summary']:
                lines.append(f"  > {item['summary'][:150]}...")
        
        return "\n".join(lines)

    def fetch_global_news_titles(self, limit=30):
        """
        글로벌 뉴스 헤드라인 수집 (감성 분석용).
        1차: MarketWatch, 실패 시 2차: Google News RSS fallback.
        Returns: list of strings
        """
        texts = self._fetch_marketwatch_titles(limit)
        if not texts:
            texts = self._fetch_google_news_titles(limit)
        return texts

    def _fetch_marketwatch_titles(self, limit=30):
        """MarketWatch에서 헤드라인 수집"""
        texts = []
        try:
            res = requests.get(self.BASE_URLS[0], headers=self.headers, timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'html.parser')

            articles = soup.select('.article__content')
            for article in articles[:limit]:
                title_tag = article.select_one('.article__headline a')
                if not title_tag:
                    continue
                title = title_tag.text.strip()
                summary = ""
                summary_tag = article.select_one('.article__summary')
                if summary_tag:
                    summary = summary_tag.text.strip()
                texts.append(f"{title} {summary}".strip())
        except Exception as e:
            print(f"[NewsAnalyzer] MarketWatch fetch failed: {e}")
        return texts

    def _fetch_google_news_titles(self, limit=30):
        """Google News RSS fallback — stock market 관련 최신 뉴스"""
        texts = []
        try:
            url = "https://news.google.com/rss/search?q=stock+market&hl=en-US&gl=US&ceid=US:en"
            res = requests.get(url, headers=self.headers, timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'xml')

            items = soup.select('item')
            for item in items[:limit]:
                title_tag = item.select_one('title')
                if title_tag:
                    texts.append(title_tag.text.strip())
        except Exception as e:
            print(f"[NewsAnalyzer] Google News RSS fetch failed: {e}")
        return texts


if __name__ == "__main__":
    na = NewsAnalyzer()
    print(na.generate_report_section())
