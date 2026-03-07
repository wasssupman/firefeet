"""Tests for core.news_scraper.NewsScraper."""

import pytest
from collections import OrderedDict
from unittest.mock import patch, MagicMock

from core.news_scraper import NewsScraper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_html(articles):
    """Build minimal Naver Finance HTML with given (href, title) pairs."""
    items = ""
    for href, title in articles:
        items += f'<dd class="articleSubject"><a href="{href}">{title}</a></dd>\n'
    return f"<html><body>{items}</body></html>"


def _mock_response(html):
    mock_resp = MagicMock()
    mock_resp.text = html
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


# ---------------------------------------------------------------------------
# 1. _seen_links FIFO 제거 (H8 회귀)
# ---------------------------------------------------------------------------

def test_seen_links_fifo_eviction():
    """When _seen_links reaches 1000 and a new item is added, the oldest is evicted."""
    scraper = NewsScraper()

    # Fill _seen_links to exactly 1000 entries
    first_key = "https://finance.naver.com/news/FIRST"
    scraper._seen_links[first_key] = True
    for i in range(1, 1000):
        scraper._seen_links[f"https://finance.naver.com/news/{i}"] = True

    assert len(scraper._seen_links) == 1000
    assert first_key in scraper._seen_links

    # fetch_news adds one more new article → should evict the first entry
    new_href = "/news/NEW_ARTICLE"
    html = _make_html([(new_href, "새 기사 제목")])
    with patch("requests.get", return_value=_mock_response(html)):
        scraper.fetch_news()

    # First entry must have been evicted
    assert first_key not in scraper._seen_links
    # Size stays at 1000
    assert len(scraper._seen_links) <= 1000


# ---------------------------------------------------------------------------
# 2. 최대 크기 제한: _seen_links는 1000 이하 유지
# ---------------------------------------------------------------------------

def test_seen_links_max_size_never_exceeds_1000():
    """After fetching many pages, _seen_links never exceeds 1000 items."""
    scraper = NewsScraper()

    for batch in range(5):
        articles = [(f"/news/{batch}_{i}", f"기사 {batch}-{i}") for i in range(300)]
        html = _make_html(articles)
        with patch("requests.get", return_value=_mock_response(html)):
            scraper.fetch_news()

    assert len(scraper._seen_links) <= 1000


# ---------------------------------------------------------------------------
# 3. filter_news(): 키워드 매칭
# ---------------------------------------------------------------------------

def test_filter_news_keyword_matching():
    """filter_news returns only items whose title contains at least one keyword."""
    scraper = NewsScraper()
    news = [
        {"title": "삼성전자 실적 발표", "link": "http://a", "time": "09:00:00"},
        {"title": "SK하이닉스 매수", "link": "http://b", "time": "09:01:00"},
        {"title": "코스피 급락", "link": "http://c", "time": "09:02:00"},
    ]
    keywords = ["삼성전자", "SK하이닉스"]
    result = scraper.filter_news(news, keywords)

    assert len(result) == 2
    titles = [r["title"] for r in result]
    assert "삼성전자 실적 발표" in titles
    assert "SK하이닉스 매수" in titles


# ---------------------------------------------------------------------------
# 4. filter_news(): 중복 방지 (같은 뉴스에 여러 키워드 매칭 시 1건)
# ---------------------------------------------------------------------------

def test_filter_news_no_duplicate_on_multiple_keyword_match():
    """An item matching multiple keywords appears only once in results."""
    scraper = NewsScraper()
    news = [
        {"title": "삼성전자 SK하이닉스 동반 상승", "link": "http://a", "time": "09:00:00"},
    ]
    keywords = ["삼성전자", "SK하이닉스"]
    result = scraper.filter_news(news, keywords)

    assert len(result) == 1
    assert result[0]["keyword"] in keywords


# ---------------------------------------------------------------------------
# 5. fetch_news(): HTML 파싱 (mock requests.get 응답)
# ---------------------------------------------------------------------------

def test_fetch_news_parses_html_correctly():
    """fetch_news parses dd.articleSubject a tags and returns news dicts."""
    scraper = NewsScraper()
    articles = [
        ("/news/article001", "코스피 상승 마감"),
        ("/news/article002", "원달러 환율 하락"),
    ]
    html = _make_html(articles)

    with patch("requests.get", return_value=_mock_response(html)):
        result = scraper.fetch_news()

    assert len(result) == 2
    links = [item["link"] for item in result]
    assert "https://finance.naver.com/news/article001" in links
    assert "https://finance.naver.com/news/article002" in links
    for item in result:
        assert "title" in item
        assert "link" in item
        assert "time" in item


def test_fetch_news_skips_already_seen():
    """fetch_news does not return links already present in _seen_links."""
    scraper = NewsScraper()
    href = "/news/already_seen"
    full_link = "https://finance.naver.com/news/already_seen"
    scraper._seen_links[full_link] = True

    html = _make_html([(href, "이미 본 기사")])
    with patch("requests.get", return_value=_mock_response(html)):
        result = scraper.fetch_news()

    assert result == []


def test_fetch_news_returns_empty_on_request_error():
    """fetch_news returns [] instead of raising when requests.get fails."""
    scraper = NewsScraper()
    with patch("requests.get", side_effect=Exception("network error")):
        result = scraper.fetch_news()
    assert result == []
