import re
from collections import Counter


class RedditAnalyzer:
    """
    Reddit 투자 커뮤니티 감성 분석.
    - 트렌딩 티커 추출
    - Bullish/Bearish 감성 점수 계산
    - Hot Ticker 알림
    """

    BULLISH_WORDS = ['buy', 'moon', 'calls', 'long', 'green', 'bull',
                     'rocket', 'squeeze', 'breakout', 'upside', 'bullish']
    BEARISH_WORDS = ['sell', 'crash', 'puts', 'short', 'red', 'bear',
                     'dump', 'drop', 'downside', 'bearish', 'recession']

    DEFAULT_SUBS = ['wallstreetbets', 'stocks', 'investing']

    def __init__(self, client_id, client_secret, user_agent="firefeet/1.0"):
        try:
            import praw
            self.reddit = praw.Reddit(
                client_id=client_id,
                client_secret=client_secret,
                user_agent=user_agent,
            )
            self.available = True
        except Exception as e:
            print(f"[RedditAnalyzer] 초기화 실패 (API 키 확인): {e}")
            self.available = False

    def get_market_sentiment(self, subreddits=None, limit=50):
        """
        서브레딧에서 트렌딩 티커와 감성 점수를 분석합니다.
        Returns: {sentiment_level, score, hot_tickers, post_count}
        """
        if not self.available:
            return {"error": "Reddit API 미연결. config/secrets.yaml에 Reddit 키를 설정하세요."}

        subs = subreddits or self.DEFAULT_SUBS
        ticker_regex = r'\$([A-Z]{2,5})\b'
        trending_tickers = Counter()
        combined_text = ""
        post_count = 0

        try:
            for sub_name in subs:
                subreddit = self.reddit.subreddit(sub_name)
                for submission in subreddit.hot(limit=limit):
                    text = f"{submission.title} {submission.selftext}"
                    combined_text += text + " "
                    post_count += 1

                    tickers = re.findall(ticker_regex, text)
                    for t in tickers:
                        # 일반적인 단어 필터링
                        if t not in ('THE', 'FOR', 'AND', 'ARE', 'NOT', 'ALL',
                                     'BUT', 'HAS', 'ITS', 'CEO', 'IPO', 'ETF'):
                            trending_tickers[t] += 1

        except Exception as e:
            return {"error": f"Reddit 스크랩 실패: {e}"}

        # 감성 점수
        text_lower = combined_text.lower()
        bull_count = sum(text_lower.count(w) for w in self.BULLISH_WORDS)
        bear_count = sum(text_lower.count(w) for w in self.BEARISH_WORDS)

        total = bull_count + bear_count
        if total > 0:
            score = round((bull_count - bear_count) / total, 2)
        else:
            score = 0.0

        if score > 0.15:
            level = "🟢 Bullish"
        elif score < -0.15:
            level = "🔴 Bearish"
        else:
            level = "⚪ Neutral"

        return {
            "sentiment_level": level,
            "score": score,
            "bull_count": bull_count,
            "bear_count": bear_count,
            "hot_tickers": trending_tickers.most_common(10),
            "post_count": post_count,
        }

    def generate_report_section(self, subreddits=None):
        """리포트에 삽입할 Reddit 감성 분석 섹션"""
        result = self.get_market_sentiment(subreddits)

        if "error" in result:
            return f"## 🗣️ 해외 커뮤니티 분석\n> {result['error']}\n"

        lines = [
            "## 🗣️ 해외 커뮤니티 분석 (Reddit)",
            f"- **시장 심리**: {result['sentiment_level']} (Score: {result['score']:+.2f})",
            f"- **분석 게시글**: {result['post_count']}개",
            f"- **Bullish 키워드**: {result['bull_count']}회 / **Bearish**: {result['bear_count']}회",
            "",
            "**🔥 트렌딩 티커 Top 5:**",
        ]

        for ticker, count in result['hot_tickers'][:5]:
            lines.append(f"  - `${ticker}` — {count}회 언급")

        if not result['hot_tickers']:
            lines.append("  - (트렌딩 티커 없음)")

        return "\n".join(lines)
