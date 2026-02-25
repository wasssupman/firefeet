import sys
from core.encoding_setup import setup_utf8_stdout
setup_utf8_stdout()

from core.news_scraper import NewsScraper
from core.discord_client import DiscordClient
import time

def run_news_alert_system():
    print("=== Starting News Alert System ===")
    
    scraper = NewsScraper()
    discord = DiscordClient()
    
    # Interested Keywords
    KEYWORDS = ["공시", "계약", "무상증자", "유상증자", "특허", "수주", "개발", "임상", "인수", "합병"]
    print(f"Monitoring keywords: {KEYWORDS}")
    
    # Initial fetch to populate seen_links
    print("Initializing... (Fetching existing news to ignore)")
    init_items = scraper.fetch_news()
    print(f"Initialized with {len(init_items)} existing articles.")
    
    # Send Startup Message
    discord.send_message("🚀 **Firefeet News Alert System Started!**\nMonitoring for: " + ", ".join(KEYWORDS))
    print("Sent startup notification to Discord.")

    print("Watching for new news...")
    
    try:
        while True:
            # 1. Fetch News
            news_items = scraper.fetch_news()
            
            if news_items:
                print(f"[{news_items[0]['time']}] Fetched {len(news_items)} new articles.")
                
                # 2. Filter by Keywords
                alerts = scraper.filter_news(news_items, KEYWORDS)
                
                # 3. Send Alerts
                for alert in alerts:
                    print(f"🚨 ALERT: {alert['title']}")
                    discord.send_alert(alert['title'], alert['link'], alert['keyword'])
            
            # Wait 60 seconds
            time.sleep(60)
            
    except KeyboardInterrupt:
        print("\nStopping News Alert System.")

if __name__ == "__main__":
    run_news_alert_system()
