import requests
from bs4 import BeautifulSoup
import time
import datetime

class NewsScraper:
    def __init__(self):
        # Naver Finance Real-time News (Main News)
        self.url = "https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=258"
        self.seen_links = set()

    def fetch_news(self):
        """
        Fetches the latest news from Naver Finance.
        Returns a list of dicts: {'title': str, 'link': str, 'date': str}
        """
        try:
            res = requests.get(self.url, headers={'User-Agent': 'Mozilla/5.0'})
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'lxml')
            
            news_items = []
            
            # Select news list items (structure might change, but usually dl > dd > a)
            # Naver Finance News List structure
            articles = soup.select('dd.articleSubject a')

            for a_tag in articles:
                title = a_tag.get_text(strip=True)
                if not title:
                    continue
                href = a_tag.get('href', '')
                link = href if href.startswith('http') else "https://finance.naver.com" + href
                
                # Deduplication
                if link in self.seen_links:
                    continue
                
                self.seen_links.add(link)
                
                # Keep set size manageable
                if len(self.seen_links) > 1000:
                    self.seen_links.pop()
                    
                news_items.append({
                    'title': title,
                    'link': link,
                    'time': datetime.datetime.now().strftime("%H:%M:%S")
                })
                
            return news_items
            
        except Exception as e:
            print(f"[NewsScraper] Error scraping news: {e}")
            return []

    def filter_news(self, news_items, keywords):
        """
        Filters news items by keywords.
        """
        results = []
        for item in news_items:
            for keyword in keywords:
                if keyword in item['title']:
                    item['keyword'] = keyword
                    results.append(item)
                    break # Avoid duplicate alerts for same news with multiple keywords
        return results

    def fetch_news_by_date(self, date_str, pages=3):
        """
        특정 날짜의 네이버 금융 뉴스 헤드라인을 수집.
        date_str: "YYYYMMDD" (예: "20260212")
        Returns: list of title strings
        """
        titles = []
        base_url = (
            "https://finance.naver.com/news/news_list.naver"
            "?mode=LSS2D&section_id=101&section_id2=258"
        )
        for page in range(1, pages + 1):
            try:
                url = f"{base_url}&date={date_str}&page={page}"
                res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                res.raise_for_status()
                soup = BeautifulSoup(res.text, 'lxml')

                articles = soup.select('dd.articleSubject a')
                for a_tag in articles:
                    title = a_tag.get_text(strip=True)
                    if title:
                        titles.append(title)

                time.sleep(0.3)
            except Exception as e:
                print(f"[NewsScraper] fetch_news_by_date error (page {page}): {e}")
                break
        return titles
