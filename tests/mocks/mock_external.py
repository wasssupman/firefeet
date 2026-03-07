"""Mock external service clients for testing."""


class MockDiscordClient:
    """Mock Discord client that records messages instead of sending them."""

    MAX_LEN = 1900

    def __init__(self, webhook_key=None):
        self.webhook_url = "https://mock.discord.webhook"
        self.messages = []  # All messages sent

    def send_message(self, message):
        self.messages.append(message)

    def send(self, message):
        if len(message) <= self.MAX_LEN:
            self.send_message(message)
            return
        lines = message.split("\n")
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > self.MAX_LEN:
                self.send_message(chunk)
                chunk = line + "\n"
            else:
                chunk += line + "\n"
        if chunk.strip():
            self.send_message(chunk)

    def send_alert(self, title, link, keyword):
        message = f"🚨 **[{keyword}]** 감지!\n\n**{title}**\n{link}"
        self.send_message(message)

    def get_last_message(self):
        return self.messages[-1] if self.messages else None

    def clear(self):
        self.messages.clear()


class MockNewsScraper:
    """Mock NewsScraper that returns canned data."""

    def __init__(self):
        self.url = "https://mock.naver.finance"
        self._seen_links = {}
        self._news = []

    def set_news(self, news_items):
        """Test helper to set mock news."""
        self._news = news_items

    def fetch_news(self):
        return self._news

    def filter_news(self, news_items, keywords):
        results = []
        for item in news_items:
            for keyword in keywords:
                if keyword in item['title']:
                    item['keyword'] = keyword
                    results.append(item)
                    break
        return results

    def fetch_news_by_date(self, date_str, pages=3):
        return [n['title'] for n in self._news]
