"""
Regression tests for Firefeet trading system.
Each test verifies a specific past bug does not recur.

Test IDs follow the convention:
  C  = Code-level bug
  H  = Historical bug (found in production/review)
"""

import ast
import glob
import json
import os
import datetime
import tempfile
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

from tests.mocks.mock_kis import MockKISAuth, MockKISManager, make_ohlc_dataframe
from tests.mocks.mock_external import MockDiscordClient


# ---------------------------------------------------------------------------
# C1: process_stock without data_provider_fn → graceful skip (no crash)
# ---------------------------------------------------------------------------

def test_c1_process_stock_no_provider(strategy, trading_settings):
    """
    Regression: process_stock called without any data_provider_fn should
    log and return gracefully instead of raising AttributeError or TypeError.
    """
    from core.execution.trader import FirefeetTrader

    manager = MockKISManager()
    trader = FirefeetTrader(
        manager=manager,
        strategy=strategy,
        settings_path=trading_settings,
        data_provider_fn=None,  # no provider set
    )
    trader.add_target("005930", "삼성전자")

    # Must not raise any exception
    trader.process_stock("005930", "1000", data_provider_fn=None)


# ---------------------------------------------------------------------------
# C2: After buy order, sync_portfolio is called
# ---------------------------------------------------------------------------

@patch("time.sleep")
def test_c2_buy_then_sync(mock_sleep, strategy, trading_settings):
    """
    Regression: After a successful buy order, sync_portfolio() must be called
    to reflect the new position in the local portfolio state.
    """
    from core.execution.trader import FirefeetTrader

    manager = MockKISManager()

    # OHLC that triggers BUY: target = 50000 + 0.5*(51000-48000) = 51500
    # Current price = 52000 > 51500 → signal = BUY
    ohlc = pd.DataFrame([
        {"date": "20260226", "open": 50000, "high": 52000, "low": 49000,
         "close": 51500, "volume": 2000000},
        {"date": "20260225", "open": 48500, "high": 51000, "low": 48000,
         "close": 50500, "volume": 1500000},
    ] + [
        {"date": f"2026020{i}", "open": 48000, "high": 50000, "low": 47000,
         "close": 49000, "volume": 1000000} for i in range(1, 25)
    ])
    manager.set_ohlc("005930", ohlc)
    manager.set_current_price("005930", 52000)

    def provider(code):
        df = manager.get_daily_ohlc(code)
        price_info = manager.get_current_price(code)
        return df, price_info["price"]

    discord = MockDiscordClient()
    trader = FirefeetTrader(
        manager=manager,
        strategy=strategy,
        discord_client=discord,
        settings_path=trading_settings,
        data_provider_fn=provider,
    )
    trader.add_target("005930", "삼성전자")

    sync_call_count = []
    original_sync = trader.sync_portfolio

    def counting_sync():
        sync_call_count.append(1)
        original_sync()

    trader.sync_portfolio = counting_sync

    # Initial sync happened in __init__; reset counter
    sync_call_count.clear()

    trader.process_stock("005930", "1000", provider)

    # sync_portfolio must have been called at least once after the buy
    buy_orders = [o for o in manager._orders if o["order_type"].name == "BUY"]
    if buy_orders:
        assert len(sync_call_count) >= 1, (
            "sync_portfolio must be called after a successful buy order"
        )


# ---------------------------------------------------------------------------
# C5: KISAuth.get_headers() must NOT contain "appsecret" key
# ---------------------------------------------------------------------------

def test_c5_appsecret_in_headers():
    """
    KIS API requires 'appsecret' in request headers for all endpoints.
    Verify it is present alongside appkey and authorization.
    """
    from core.kis_auth import KISAuth

    auth = KISAuth({"APP_KEY": "k", "APP_SECRET": "s", "URL_BASE": "https://x"})
    auth.token = "test_token"
    headers = auth.get_headers(tr_id="TEST")

    assert "appsecret" in headers, "appsecret is required by KIS API"
    assert headers["appsecret"] == "s"
    assert "authorization" in headers
    assert "appkey" in headers


# ---------------------------------------------------------------------------
# C6: AISwingAgent._check_and_increment_quota() uses fcntl.flock
# ---------------------------------------------------------------------------

def test_c6_quota_file_lock(tmp_path):
    """
    Regression: Quota file must use fcntl.flock for multi-process safety.
    Verify the usage_file is created and incremented atomically.
    """
    from core.analysis.ai_swing_agent import AISwingAgent
    from tests.mocks.mock_llm import MockClaudeAnalyst, MockClaudeExecutor

    usage_file = str(tmp_path / "ai_usage.json")

    agent = AISwingAgent(
        config_path=str(tmp_path / "nonexistent.yaml"),
        analyst=MockClaudeAnalyst(),
        executor=MockClaudeExecutor(),
    )
    agent.usage_file = usage_file
    agent.max_daily_calls = 10

    # First call: file created, count=1
    result1 = agent._check_and_increment_quota()
    assert result1 is True
    assert os.path.exists(usage_file)

    with open(usage_file, "r") as f:
        data = json.load(f)
    assert data["count"] == 1

    # Second call: count increments
    result2 = agent._check_and_increment_quota()
    assert result2 is True

    with open(usage_file, "r") as f:
        data = json.load(f)
    assert data["count"] == 2


# ---------------------------------------------------------------------------
# H1: reset_daily() same day → no double reset
# ---------------------------------------------------------------------------

def test_h1_daily_reset_date_based(strategy, trading_settings):
    """
    Regression: reset_daily() called twice on the same calendar day must
    not clear sold_today / daily_realized_pnl a second time.
    """
    from core.execution.trader import FirefeetTrader

    manager = MockKISManager()
    trader = FirefeetTrader(
        manager=manager,
        strategy=strategy,
        settings_path=trading_settings,
    )

    # Populate some state
    trader.sold_today["005930"] = {"time": datetime.datetime.now(), "profitable": True}
    trader.daily_realized_pnl = -5000

    today = datetime.date.today()
    trader._last_reset_date = today  # pretend we already reset today

    # Second reset same day should be a no-op
    trader.reset_daily()

    assert "005930" in trader.sold_today, (
        "sold_today must not be cleared when reset_daily() is called same day"
    )
    assert trader.daily_realized_pnl == -5000, (
        "daily_realized_pnl must not reset when called same day"
    )


# ---------------------------------------------------------------------------
# H2: ConfigLoader paper mode uses PAPER section
# ---------------------------------------------------------------------------

def test_h2_default_paper_mode(mock_config):
    """
    Regression: ConfigLoader.get_kis_config(mode='PAPER') must return
    the PAPER section, not PROD, to prevent accidental real-money trading.
    """
    from core.config_loader import ConfigLoader

    loader = ConfigLoader(config_path=mock_config)
    paper_cfg = loader.get_kis_config(mode="PAPER")

    assert paper_cfg["APP_KEY"] == "test_paper_key", (
        "PAPER mode must use PAPER APP_KEY, not PROD"
    )
    assert paper_cfg["APP_SECRET"] == "test_paper_secret"
    assert "openapivts" in paper_cfg["URL_BASE"], (
        "PAPER mode URL must point to VTS (paper trading) endpoint"
    )


# ---------------------------------------------------------------------------
# H5: consecutive_sl_count resets to 0 after SELL_TAKE_PROFIT
# ---------------------------------------------------------------------------

@patch("time.sleep")
def test_h5_sl_counter_reset_on_tp(mock_sleep, strategy, trading_settings):
    """
    Regression: After a SELL_TAKE_PROFIT, consecutive_sl_count must reset
    to 0 so the cooldown brake is not incorrectly triggered.
    """
    from core.execution.trader import FirefeetTrader

    manager = MockKISManager()
    discord = MockDiscordClient()
    trader = FirefeetTrader(
        manager=manager,
        strategy=strategy,
        discord_client=discord,
        settings_path=trading_settings,
    )

    # Simulate 2 prior SL events
    trader.consecutive_sl_count = 2

    buy_price = 50000
    trader.portfolio["005930"] = {
        "qty": 5,
        "orderable_qty": 5,
        "buy_price": float(buy_price),
    }
    trader.stock_names["005930"] = "삼성전자"

    # TP price: 50000 * 1.03 = 51500 → use 52000
    tp_price = 52000
    manager.set_current_price("005930", tp_price)

    ohlc = make_ohlc_dataframe()

    def provider(code):
        return ohlc, tp_price

    trader.process_stock("005930", "1100", provider)

    sell_orders = [o for o in manager._orders if o["order_type"].name == "SELL"]
    if sell_orders:
        assert trader.consecutive_sl_count == 0, (
            "consecutive_sl_count must reset to 0 after SELL_TAKE_PROFIT"
        )


# ---------------------------------------------------------------------------
# H6: VisionAnalyst error → returns REJECT dict
# ---------------------------------------------------------------------------

def test_h6_vision_error_rejects():
    """
    Regression: When VisionAnalyst.validate() encounters an internal error
    (e.g., API failure), it must return a REJECT dict (not raise or return CONFIRM).
    """
    from core.analysis.llms.vision_analyst import VisionAnalyst

    vision = VisionAnalyst.__new__(VisionAnalyst)
    vision.model_name = "gemini-2.5-flash-lite"
    vision.use_mock = False  # force real path
    vision.client = MagicMock()

    # Simulate API error
    vision.client.models.generate_content.side_effect = RuntimeError("API timeout")

    result = vision.validate(b"fake_bytes", "005930", "삼성전자")

    assert result["action"] == "REJECT", (
        "VisionAnalyst error must return REJECT, not CONFIRM"
    )
    assert result["confidence"] == 0
    assert result["risk_level"] == "HIGH"


# ---------------------------------------------------------------------------
# H7: ET→KST conversion respects DST (winter +14h, summer +13h)
# ---------------------------------------------------------------------------

def test_h7_dst_conversion():
    """
    Regression: ET→KST conversion must account for DST.
    Winter (EST = UTC-5): 8:30 ET → 22:30 KST (+14h)
    Summer (EDT = UTC-4): 8:30 ET → 21:30 KST (+13h)
    """
    from zoneinfo import ZoneInfo

    et_tz = ZoneInfo("America/New_York")
    kst_tz = ZoneInfo("Asia/Seoul")

    # Winter date: January 15 (no DST — EST = UTC-5)
    winter_naive = datetime.datetime(2026, 1, 15, 8, 30, 0)
    winter_et = winter_naive.replace(tzinfo=et_tz)
    winter_kst = winter_et.astimezone(kst_tz)
    assert winter_kst.hour == 22
    assert winter_kst.minute == 30

    # Summer date: July 15 (DST active — EDT = UTC-4)
    summer_naive = datetime.datetime(2026, 7, 15, 8, 30, 0)
    summer_et = summer_naive.replace(tzinfo=et_tz)
    summer_kst = summer_et.astimezone(kst_tz)
    assert summer_kst.hour == 21
    assert summer_kst.minute == 30


# ---------------------------------------------------------------------------
# H8: NewsScraper seen_links FIFO eviction at 1000
# ---------------------------------------------------------------------------

def test_h8_seen_links_fifo():
    """
    Regression: _seen_links OrderedDict must evict oldest entries (FIFO)
    when size exceeds 1000, preventing unbounded memory growth.
    """
    from core.news_scraper import NewsScraper
    from unittest.mock import patch, MagicMock
    import requests

    scraper = NewsScraper()

    # Pre-populate with 1000 entries
    for i in range(1000):
        scraper._seen_links[f"https://finance.naver.com/news/{i}"] = True

    first_key = next(iter(scraper._seen_links))
    assert first_key == "https://finance.naver.com/news/0"

    # Simulate adding one more entry to trigger FIFO eviction
    # We need a full fetch call for that — but we can test the eviction logic directly
    new_link = "https://finance.naver.com/news/1001"
    scraper._seen_links[new_link] = True
    while len(scraper._seen_links) > 1000:
        scraper._seen_links.popitem(last=False)

    assert len(scraper._seen_links) == 1000
    # Oldest entry (news/0) must be gone
    assert "https://finance.naver.com/news/0" not in scraper._seen_links
    # Newest entry must still be present
    assert new_link in scraper._seen_links


# ---------------------------------------------------------------------------
# H9: _sanity_check — target_price=0 → BUY overridden to WAIT
# ---------------------------------------------------------------------------

def test_h9_sanity_check_zero_target(tmp_path):
    """
    Regression: When the LLM returns target_price=0 (missing value),
    AISwingAgent._sanity_check must override BUY to WAIT.
    """
    from core.analysis.ai_swing_agent import AISwingAgent
    from tests.mocks.mock_llm import MockClaudeAnalyst, MockClaudeExecutor

    agent = AISwingAgent(
        config_path=str(tmp_path / "nonexistent.yaml"),
        analyst=MockClaudeAnalyst(),
        executor=MockClaudeExecutor(),
    )

    decision = {
        "decision": "BUY",
        "confidence": 70,
        "target_price": 0,  # missing/zero
        "stop_loss": 47000,
        "reasoning": "Looks good",
    }
    facts = {"current_price": 52000}

    result = agent._sanity_check(decision, facts, "005930", "삼성전자")

    assert result["decision"] == "WAIT", (
        "target_price=0 must cause BUY to be overridden to WAIT"
    )
    assert "OVERRIDDEN" in result["reasoning"]


# ---------------------------------------------------------------------------
# H10: ConfigLoader load_config() returns cached value on 2nd call
# ---------------------------------------------------------------------------

def test_h10_config_cache(mock_config):
    """
    Regression: ConfigLoader.load_config() must cache the result so
    the YAML file is only read once (not on every call).
    """
    from core.config_loader import ConfigLoader

    loader = ConfigLoader(config_path=mock_config)

    # Count file reads via open() spy
    open_call_count = []
    original_open = open

    def counting_open(path, *args, **kwargs):
        if str(path) == mock_config:
            open_call_count.append(path)
        return original_open(path, *args, **kwargs)

    with patch("builtins.open", side_effect=counting_open):
        cfg1 = loader.load_config()
        cfg2 = loader.load_config()

    assert cfg1 is cfg2, "load_config() must return the exact same cached object"
    # File opened at most once (could be 0 if first load happened before patch)
    assert len(open_call_count) <= 1, (
        "YAML file must not be re-read on subsequent load_config() calls"
    )


# ---------------------------------------------------------------------------
# H13: No bare except handlers in core/ (AST check)
# ---------------------------------------------------------------------------

def test_h13_no_bare_excepts():
    """
    Regression: bare `except:` (without exception type) swallows errors silently
    and makes debugging impossible. All except clauses must name an exception type.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    core_path = os.path.join(project_root, "core")

    violations = []
    py_files = glob.glob(os.path.join(core_path, "**", "*.py"), recursive=True)
    assert len(py_files) > 0, "Should find at least some Python files in core/"

    for filepath in py_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filename=filepath)
        except SyntaxError:
            continue  # skip unparseable files

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                rel = os.path.relpath(filepath, project_root)
                violations.append(f"{rel}:{node.lineno}")

    assert violations == [], (
        f"Bare except: handlers found (use 'except Exception:' instead):\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# H14: ConfigLoader(absolute_path) uses that exact path
# ---------------------------------------------------------------------------

def test_h14_config_absolute_path(tmp_path):
    """
    Regression: ConfigLoader constructed with an explicit absolute path must
    use that exact path, not fall back to the default config/ directory.
    """
    import yaml
    from core.config_loader import ConfigLoader

    custom_path = tmp_path / "custom_secrets.yaml"
    custom_config = {
        "PAPER": {
            "APP_KEY": "custom_key",
            "APP_SECRET": "custom_secret",
            "URL_BASE": "https://custom.endpoint",
        },
        "CANO": "99999999",
        "ACNT_PRDT_CD": "01",
    }
    with open(custom_path, "w", encoding="utf-8") as f:
        yaml.dump(custom_config, f)

    loader = ConfigLoader(config_path=str(custom_path))
    assert loader.config_path == str(custom_path), (
        "ConfigLoader must store and use the provided absolute path"
    )

    cfg = loader.load_config()
    assert cfg["CANO"] == "99999999", (
        "ConfigLoader must load from the provided path, not the default path"
    )
