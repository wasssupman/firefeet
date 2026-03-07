"""Shared pytest fixtures for Firefeet test suite."""

import os
import pytest
import yaml
import pandas as pd
from unittest.mock import patch, MagicMock

from tests.mocks.mock_kis import MockKISAuth, MockKISManager, make_ohlc_dataframe
from tests.mocks.mock_external import MockDiscordClient, MockNewsScraper
from tests.mocks.mock_llm import MockClaudeAnalyst, MockClaudeExecutor, MockVisionAnalyst


# ── KIS Auth & Manager ──────────────────────────────────────

@pytest.fixture
def mock_auth():
    return MockKISAuth()


@pytest.fixture
def mock_manager(mock_auth):
    return MockKISManager(auth=mock_auth)


# ── External Services ───────────────────────────────────────

@pytest.fixture
def mock_discord():
    return MockDiscordClient()


@pytest.fixture
def mock_news_scraper():
    return MockNewsScraper()


# ── LLM Mocks ──────────────────────────────────────────────

@pytest.fixture
def mock_analyst():
    return MockClaudeAnalyst()


@pytest.fixture
def mock_executor():
    return MockClaudeExecutor()


@pytest.fixture
def mock_vision():
    return MockVisionAnalyst()


# ── Strategy ────────────────────────────────────────────────

@pytest.fixture
def strategy():
    from core.analysis.technical import VolatilityBreakoutStrategy
    return VolatilityBreakoutStrategy(k=0.5)


# ── OHLC Data ──────────────────────────────────────────────

@pytest.fixture
def sample_ohlc():
    """30-day OHLC DataFrame sorted latest-first (index 0 = today)."""
    return make_ohlc_dataframe(days=30)


@pytest.fixture
def breakout_ohlc():
    """OHLC data where today's open + k * yesterday's range triggers a breakout."""
    rows = [
        {"date": "20260226", "open": 50000, "high": 52000, "low": 49000,
         "close": 51500, "volume": 2000000},
        {"date": "20260225", "open": 49000, "high": 51000, "low": 48000,
         "close": 50500, "volume": 1500000},
    ]
    for i in range(2, 30):
        rows.append({
            "date": f"202602{26 - i:02d}" if 26 - i > 0 else f"202601{31 - (i - 26):02d}",
            "open": 48000, "high": 50000, "low": 47000,
            "close": 49000, "volume": 1000000,
        })
    return pd.DataFrame(rows)


# ── Config Fixtures ─────────────────────────────────────────

@pytest.fixture
def mock_config(tmp_path):
    """Create a temporary secrets.yaml and return its path."""
    config = {
        "PROD": {
            "APP_KEY": "test_prod_key",
            "APP_SECRET": "test_prod_secret",
            "URL_BASE": "https://openapi.koreainvestment.com:9443",
        },
        "PAPER": {
            "APP_KEY": "test_paper_key",
            "APP_SECRET": "test_paper_secret",
            "URL_BASE": "https://openapivts.koreainvestment.com:29443",
        },
        "CANO": "12345678",
        "PAPER_CANO": "50000000",
        "ACNT_PRDT_CD": "01",
        "DISCORD_WEBHOOK_URL": "https://mock.discord.webhook",
        "ANTHROPIC_API_KEY": "test_anthropic_key",
        "GEMINI_API_KEY": "test_gemini_key",
    }
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    secrets_path = config_dir / "secrets.yaml"
    with open(secrets_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return str(secrets_path)


@pytest.fixture
def trading_settings(tmp_path):
    """Create temporary trading_settings.yaml."""
    settings = {
        "total_budget": 1000000,
        "max_concurrent_targets": 3,
        "whitelist": [],
    }
    path = tmp_path / "trading_settings.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(settings, f)
    return str(path)


@pytest.fixture
def temperature_config(tmp_path):
    """Create temporary temperature_config.yaml."""
    config = {
        "level_thresholds": {
            "HOT": 70,
            "WARM": 40,
            "NEUTRAL": -20,
            "COOL": -60,
        },
        "modules": {
            "macro": {"enabled": False, "weight": 40},
            "sentiment": {"enabled": False, "weight": 35},
            "econ": {"enabled": False, "weight": 25},
        },
        "strategy_profiles": {
            "HOT": {"k": 0.3, "take_profit": 4.0, "stop_loss": -3.0, "max_position_pct": 0.35},
            "WARM": {"k": 0.4, "take_profit": 3.5, "stop_loss": -3.0, "max_position_pct": 0.30},
            "NEUTRAL": {"k": 0.5, "take_profit": 3.0, "stop_loss": -3.0, "max_position_pct": 0.25},
            "COOL": {"k": 0.6, "take_profit": 2.5, "stop_loss": -2.5, "max_position_pct": 0.20},
            "COLD": {"k": 0.7, "take_profit": 2.0, "stop_loss": -2.0, "max_position_pct": 0.15},
        },
    }
    path = tmp_path / "temperature_config.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return str(path)


# ── Trader Fixture ──────────────────────────────────────────

@pytest.fixture
def trader(mock_manager, strategy, mock_discord, trading_settings):
    """Create FirefeetTrader with all dependencies mocked."""
    from core.execution.trader import FirefeetTrader

    def data_provider(code):
        df = mock_manager.get_daily_ohlc(code)
        price_info = mock_manager.get_current_price(code)
        return df, price_info["price"] if price_info else None

    t = FirefeetTrader(
        manager=mock_manager,
        strategy=strategy,
        discard_client=mock_discord,
        settings_path=trading_settings,
        data_provider_fn=data_provider,
    )
    return t


# ── Scalping Fixtures ──────────────────────────────────────

@pytest.fixture
def scalp_settings(tmp_path):
    """config/scalping_settings.yaml 복사 -> tmp_path."""
    import shutil
    src = os.path.join(os.path.dirname(__file__), "..", "config", "scalping_settings.yaml")
    dst = tmp_path / "scalping_settings.yaml"
    shutil.copy2(src, dst)
    return str(dst)


@pytest.fixture
def scalp_rules(tmp_path):
    """config/scalping_rules.yaml 복사 -> tmp_path."""
    import shutil
    src = os.path.join(os.path.dirname(__file__), "..", "config", "scalping_rules.yaml")
    dst = tmp_path / "scalping_rules.yaml"
    shutil.copy2(src, dst)
    return str(dst)


@pytest.fixture
def scalp_strategies(tmp_path):
    """config/scalping_strategies.yaml 복사 -> tmp_path."""
    import shutil
    src = os.path.join(os.path.dirname(__file__), "..", "config", "scalping_strategies.yaml")
    dst = tmp_path / "scalping_strategies.yaml"
    shutil.copy2(src, dst)
    return str(dst)


@pytest.fixture
def tick_buffer():
    from core.scalping.tick_buffer import TickBuffer
    return TickBuffer(max_size=600)


@pytest.fixture
def orderbook_analyzer():
    from core.scalping.orderbook_analyzer import OrderbookAnalyzer
    return OrderbookAnalyzer()


# ── Data Provider Helper ────────────────────────────────────

@pytest.fixture
def make_data_provider(mock_manager):
    """Factory fixture to create data_provider_fn from mock_manager."""
    def _make():
        def provider(code):
            df = mock_manager.get_daily_ohlc(code)
            price_info = mock_manager.get_current_price(code)
            return df, price_info["price"] if price_info else None
        return provider
    return _make
