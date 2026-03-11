"""
Integration tests for Firefeet trading system.

Tests cover the full pipeline from Scanner → Screener → Trader,
as well as Temperature → Strategy, AI Swing pipeline, and portfolio
state transitions under various market conditions.
"""

import datetime
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

from tests.mocks.mock_kis import MockKISAuth, MockKISManager, make_ohlc_dataframe
from tests.mocks.mock_external import MockDiscordClient
from tests.mocks.mock_llm import MockClaudeAnalyst, MockClaudeExecutor, MockVisionAnalyst


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_breakout_ohlc(open_price=50000, yesterday_high=51000, yesterday_low=48000, k=0.5):
    """
    Build OHLC where today's open + k*(yesterday_high - yesterday_low) gives a clear target.
    target = 50000 + 0.5 * (51000 - 48000) = 50000 + 1500 = 51500
    """
    rows = [
        # index 0 = today (open_price, high/low not used for target calc)
        {"date": "20260226", "open": open_price, "high": open_price + 2000,
         "low": open_price - 1000, "close": open_price + 500, "volume": 2000000},
        # index 1 = yesterday (used for range calculation)
        {"date": "20260225", "open": yesterday_low + 500, "high": yesterday_high,
         "low": yesterday_low, "close": yesterday_high - 200, "volume": 1500000},
    ]
    for i in range(2, 30):
        rows.append({
            "date": f"202602{24 - i:02d}" if 24 - i > 0 else "20260101",
            "open": 48000, "high": 50000, "low": 47000,
            "close": 49000, "volume": 1000000,
        })
    return pd.DataFrame(rows)


def _make_trader(manager, strategy, settings_path, provider_fn=None):
    from core.execution.trader import FirefeetTrader
    discord = MockDiscordClient()
    trader = FirefeetTrader(
        manager=manager,
        strategy=strategy,
        discord_client=discord,
        settings_path=settings_path,
        data_provider_fn=provider_fn,
    )
    return trader, discord


# ---------------------------------------------------------------------------
# Test 1: Full buy-sell cycle (Scanner → Screener → Trader BUY → TP SELL)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@patch("time.sleep")
def test_full_buy_sell_cycle(mock_sleep, strategy, trading_settings):
    """
    Full cycle: MockKISManager with OHLC data that triggers a BUY signal.
    After buy, update mock price to trigger TP. Verify sell order was placed.
    """
    manager = MockKISManager()

    # target = open(50000) + 0.5 * (yesterday_high(51000) - yesterday_low(48000)) = 51500
    ohlc = _make_breakout_ohlc(open_price=50000, yesterday_high=51000, yesterday_low=48000)
    manager.set_ohlc("005930", ohlc)

    # Current price above target → BUY signal
    buy_price = 52000
    manager.set_current_price("005930", buy_price)

    def provider(code):
        df = manager.get_daily_ohlc(code)
        price_info = manager.get_current_price(code)
        return df, price_info["price"]

    trader, discord = _make_trader(manager, strategy, trading_settings, provider_fn=provider)
    trader.add_target("005930", "삼성전자")

    # --- Phase 1: BUY ---
    # After buy, mock balance reflects holding
    def sync_with_holding():
        manager.set_balance(holdings=[{
            "code": "005930",
            "name": "삼성전자",
            "qty": 3,
            "orderable_qty": 3,
            "buy_price": float(buy_price),
            "profit_rate": 0.0,
        }])
        trader.portfolio["005930"] = {
            "qty": 3,
            "orderable_qty": 3,
            "buy_price": float(buy_price),
        }

    with patch.object(trader, "sync_portfolio", side_effect=sync_with_holding):
        trader.process_stock("005930", "1000", provider)

    buy_orders = [o for o in manager._orders if o["order_type"].name == "BUY"]
    assert len(buy_orders) == 1, "Expected exactly one BUY order"

    # --- Phase 2: Price moves up to trigger TAKE PROFIT ---
    # ATR≈3000, atr_tp_multiplier=2.0 → effective TP = (3000*2)/52000 = 11.5%
    # 52000 * 1.115 ≈ 58000, so use 59000
    tp_price = 59000
    manager.set_current_price("005930", tp_price)

    trader.process_stock("005930", "1100", provider)

    sell_orders = [o for o in manager._orders if o["order_type"].name == "SELL"]
    assert len(sell_orders) == 1, "Expected exactly one SELL order after TP"
    assert "005930" not in trader.portfolio, "Stock should be removed from portfolio after sell"
    assert "005930" in trader.sold_today, "Stock should be tracked in sold_today"


# ---------------------------------------------------------------------------
# Test 2: Scanner → Screener pipeline — shape compatibility
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_scanner_screener_shape_compatibility(strategy):
    """
    StockScanner output format is compatible with StockScreener.screen() input.
    Required fields: code, name, price, volume, change_rate.
    """
    from core.execution.scanner import StockScanner
    from core.analysis.scoring_engine import StockScreener

    # Scanner produces stocks via mock fetcher
    fetched = [
        {"code": "005930", "name": "삼성전자", "price": 70000,
         "volume": 5000000, "change_rate": 1.5},
        {"code": "000660", "name": "SK하이닉스", "price": 150000,
         "volume": 3000000, "change_rate": 2.0},
    ]
    scanner = StockScanner(primary_fetcher=lambda limit, min_price: fetched)

    with patch.object(scanner, "_is_market_hours", return_value=True):
        stocks = scanner.get_top_stocks(limit=10)

    # Verify required screener fields are present
    required_fields = {"code", "name", "price", "volume", "change_rate"}
    for s in stocks:
        assert required_fields.issubset(s.keys()), (
            f"Stock {s.get('code')} missing fields: {required_fields - s.keys()}"
        )

    # Screener can accept this data (data_provider_fn returns neutral data)
    ohlc = make_ohlc_dataframe(days=30)
    supply = {"sentiment": "NEUTRAL", "foreign_3d": 0, "institution_3d": 0}
    current_data = {"high": stocks[0]["price"], "price": stocks[0]["price"]}

    screener = StockScreener(strategy=strategy)

    def mock_provider(code):
        return ohlc, supply, current_data

    # pre_filter has min_volume=500000 — our stocks pass
    results = screener.screen(stocks, mock_provider)
    # Results may be empty if score < min_score, but no exception is the key assertion
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Test 3: Temperature → Strategy pipeline
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_temperature_to_strategy_pipeline(strategy, temperature_config):
    """
    MarketTemperature output → Strategy.apply_temperature() changes k/TP/SL correctly.
    Uses temperature_config fixture with all modules disabled → temperature=0 (NEUTRAL).
    """
    from core.analysis.market_temperature import MarketTemperature

    mt = MarketTemperature(config_path=temperature_config)
    result = mt.calculate()

    # All modules disabled → temperature=0, level=NEUTRAL
    assert result["temperature"] == 0
    assert result["level"] == "NEUTRAL"

    # Define profiles matching the fixture
    profiles = {
        "HOT":     {"k": 0.3, "take_profit": 4.0, "stop_loss": -3.0, "max_position_pct": 0.35},
        "WARM":    {"k": 0.4, "take_profit": 3.5, "stop_loss": -3.0, "max_position_pct": 0.30},
        "NEUTRAL": {"k": 0.5, "take_profit": 3.0, "stop_loss": -3.0, "max_position_pct": 0.25},
        "COOL":    {"k": 0.6, "take_profit": 2.5, "stop_loss": -2.5, "max_position_pct": 0.20},
        "COLD":    {"k": 0.7, "take_profit": 2.0, "stop_loss": -2.0, "max_position_pct": 0.15},
    }

    strategy.apply_temperature(result, profiles)

    assert strategy.k == 0.5
    assert strategy.take_profit == 3.0
    assert strategy.stop_loss == -3.0
    assert strategy.max_position_pct == 0.25
    assert strategy.temperature_level == "NEUTRAL"

    # Now mock a HOT temperature and verify params shift
    hot_result = {"temperature": 80, "level": "HOT"}
    strategy.apply_temperature(hot_result, profiles)

    assert strategy.k == 0.3
    assert strategy.take_profit == 4.0
    assert strategy.temperature_level == "HOT"


# ---------------------------------------------------------------------------
# Test 4: AI Swing pipeline — BUY decision flow
# ---------------------------------------------------------------------------

@pytest.mark.integration
@patch("time.sleep")
def test_ai_swing_pipeline_buy_decision(mock_sleep, tmp_path):
    """
    AISwingAgent: MockAnalyst → MockExecutor → MockVision → sanity_check → BUY decision.
    """
    from core.analysis.ai_swing_agent import AISwingAgent

    usage_file = str(tmp_path / "ai_usage.json")

    analyst = MockClaudeAnalyst(memo="## Analysis\n- Strong upward momentum")
    executor = MockClaudeExecutor(decision={
        "decision": "BUY",
        "confidence": 80,
        "strategy_type": "BREAKOUT",
        "target_price": 55000,
        "stop_loss": 47000,
        "qty_ratio": 0.5,
        "reasoning": "Strong breakout signal.",
    })
    vision = MockVisionAnalyst()  # defaults to CONFIRM

    agent = AISwingAgent(
        config_path=str(tmp_path / "nonexistent.yaml"),
        analyst=analyst,
        executor=executor,
    )
    agent.vision = vision
    agent.usage_file = usage_file
    agent.max_daily_calls = 100  # effectively unlimited for test

    data = {
        "current_data": {"price": 52000},
        "screener_score": 75,
    }

    # utils.chart_renderer has a broken import in the dev tree; patch at sys.modules level
    # so the lazy `from utils.chart_renderer import render_chart_to_bytes` inside
    # ai_swing_agent succeeds without touching the real module.
    import sys
    fake_renderer = MagicMock()
    fake_renderer.render_chart_to_bytes = MagicMock(return_value=b"fake_png")
    with patch.dict(sys.modules, {"utils.chart_renderer": fake_renderer}):
        result = agent.analyze_trading_opportunity("005930", "삼성전자", data)

    assert result["decision"] == "BUY"
    assert analyst.call_count == 1
    assert executor.call_count == 1
    assert vision.call_count == 1


# ---------------------------------------------------------------------------
# Test 5: AI Swing pipeline — REJECT by vision
# ---------------------------------------------------------------------------

@pytest.mark.integration
@patch("time.sleep")
def test_ai_swing_pipeline_rejected_by_vision(mock_sleep, tmp_path):
    """
    AISwingAgent: MockAnalyst → MockExecutor (BUY) → MockVision (REJECT) → decision becomes WAIT.
    """
    from core.analysis.ai_swing_agent import AISwingAgent

    usage_file = str(tmp_path / "ai_usage.json")

    analyst = MockClaudeAnalyst()
    executor = MockClaudeExecutor(decision={
        "decision": "BUY",
        "confidence": 75,
        "strategy_type": "BREAKOUT",
        "target_price": 55000,
        "stop_loss": 47000,
        "qty_ratio": 0.5,
        "reasoning": "Looks good.",
    })
    vision = MockVisionAnalyst()
    vision.set_reject("Chart shows bearish pattern")

    agent = AISwingAgent(
        config_path=str(tmp_path / "nonexistent.yaml"),
        analyst=analyst,
        executor=executor,
    )
    agent.vision = vision
    agent.usage_file = usage_file
    agent.max_daily_calls = 100

    data = {
        "current_data": {"price": 52000},
        "screener_score": 70,
    }

    import sys
    fake_renderer = MagicMock()
    fake_renderer.render_chart_to_bytes = MagicMock(return_value=b"fake_png")
    with patch.dict(sys.modules, {"utils.chart_renderer": fake_renderer}):
        result = agent.analyze_trading_opportunity("005930", "삼성전자", data)

    assert result["decision"] == "WAIT", "Vision REJECT should override BUY to WAIT"
    assert "Vision AI 기각" in result.get("reasoning", "") or "vision" in result.get("reasoning", "").lower()
    assert vision.call_count == 1


# ---------------------------------------------------------------------------
# Test 6: Buy then immediate stop loss — portfolio transitions correctly
# ---------------------------------------------------------------------------

@pytest.mark.integration
@patch("time.sleep")
def test_buy_then_stop_loss(mock_sleep, strategy, trading_settings):
    """
    Buy stock, then price drops below SL → SELL_STOP_LOSS order placed,
    portfolio entry removed, sold_today updated, consecutive_sl_count incremented.
    """
    manager = MockKISManager()
    buy_price = 50000
    manager.set_current_price("005930", buy_price + 2000)  # above target → BUY

    ohlc = _make_breakout_ohlc(open_price=50000, yesterday_high=51000, yesterday_low=48000)
    manager.set_ohlc("005930", ohlc)

    def provider(code):
        df = manager.get_daily_ohlc(code)
        price_info = manager.get_current_price(code)
        return df, price_info["price"]

    trader, _ = _make_trader(manager, strategy, trading_settings, provider_fn=provider)

    # Inject a held position directly
    trader.portfolio["005930"] = {
        "qty": 5,
        "orderable_qty": 5,
        "buy_price": float(buy_price),
    }
    trader.stock_names["005930"] = "삼성전자"

    # ATR≈3000, atr_sl_multiplier=1.0 → effective SL = -(3000*1)/50000 = -6.0%
    # 50000 * 0.94 = 47000, so use 46000
    sl_price = 46000
    manager.set_current_price("005930", sl_price)

    initial_sl_count = trader.consecutive_sl_count

    trader.process_stock("005930", "1100", provider)

    sell_orders = [o for o in manager._orders if o["order_type"].name == "SELL"]
    assert len(sell_orders) == 1
    assert "005930" not in trader.portfolio
    assert trader.consecutive_sl_count == initial_sl_count + 1


# ---------------------------------------------------------------------------
# Test 7: Multiple stocks — buy A and B, sell A — portfolio tracks both
# ---------------------------------------------------------------------------

@pytest.mark.integration
@patch("time.sleep")
def test_multiple_stocks_portfolio_tracking(mock_sleep, strategy, trading_settings):
    """
    Buy stock A, buy stock B, then sell A on TP.
    Portfolio must correctly track both positions throughout.
    """
    manager = MockKISManager()

    # Stock A: will be bought and then sold on TP
    ohlc_a = _make_breakout_ohlc(open_price=50000, yesterday_high=51000, yesterday_low=48000)
    manager.set_ohlc("005930", ohlc_a)

    # Stock B: will be bought, stays held
    ohlc_b = _make_breakout_ohlc(open_price=80000, yesterday_high=82000, yesterday_low=79000)
    manager.set_ohlc("000660", ohlc_b)

    buy_price_a = 52000
    buy_price_b = 84000

    # Simulate buying A
    trader, _ = _make_trader(manager, strategy, trading_settings)
    trader.portfolio["005930"] = {"qty": 3, "orderable_qty": 3, "buy_price": float(buy_price_a)}
    trader.portfolio["000660"] = {"qty": 2, "orderable_qty": 2, "buy_price": float(buy_price_b)}
    trader.stock_names["005930"] = "삼성전자"
    trader.stock_names["000660"] = "SK하이닉스"

    assert len(trader.portfolio) == 2

    # ATR≈3000, atr_tp_multiplier=2.0 → effective TP ≈ 11.5%
    # 52000 * 1.115 ≈ 58000, so use 59000
    tp_price_a = 59000
    manager.set_current_price("005930", tp_price_a)
    # Stock B at neutral (no sell signal)
    manager.set_current_price("000660", buy_price_b)  # no profit, no loss

    def provider(code):
        df = manager.get_daily_ohlc(code)
        price_info = manager.get_current_price(code)
        return df, price_info["price"]

    trader.process_stock("005930", "1100", provider)

    # Stock A sold, stock B still held
    assert "005930" not in trader.portfolio, "Stock A should be sold"
    assert "000660" in trader.portfolio, "Stock B should remain in portfolio"
    assert len(trader.portfolio) == 1

    sell_orders = [o for o in manager._orders if o["order_type"].name == "SELL"]
    assert len(sell_orders) == 1
    assert sell_orders[0]["code"] == "005930"


# ---------------------------------------------------------------------------
# Test 8: Temperature change mid-session — strategy params update for future trades
# ---------------------------------------------------------------------------

@pytest.mark.integration
@patch("time.sleep")
def test_temperature_change_mid_session(mock_sleep, strategy, trading_settings, temperature_config):
    """
    Temperature changes mid-session: strategy params must update,
    and future trades use the new params (tighter k when HOT).
    """
    from core.analysis.market_temperature import MarketTemperature

    mt = MarketTemperature(config_path=temperature_config)

    profiles = {
        "HOT":     {"k": 0.3, "take_profit": 4.0, "stop_loss": -3.0, "max_position_pct": 0.35},
        "WARM":    {"k": 0.4, "take_profit": 3.5, "stop_loss": -3.0, "max_position_pct": 0.30},
        "NEUTRAL": {"k": 0.5, "take_profit": 3.0, "stop_loss": -3.0, "max_position_pct": 0.25},
        "COOL":    {"k": 0.6, "take_profit": 2.5, "stop_loss": -2.5, "max_position_pct": 0.20},
        "COLD":    {"k": 0.7, "take_profit": 2.0, "stop_loss": -2.0, "max_position_pct": 0.15},
    }

    # Start: NEUTRAL (all modules disabled → temp=0)
    result_neutral = mt.calculate()
    strategy.apply_temperature(result_neutral, profiles)
    assert strategy.k == 0.5
    assert strategy.temperature_level == "NEUTRAL"

    # Mid-session: HOT market arrives
    hot_result = {"temperature": 75, "level": "HOT"}
    strategy.apply_temperature(hot_result, profiles)
    assert strategy.k == 0.3
    assert strategy.temperature_level == "HOT"

    # Verify get_target_price uses the new tighter k
    # With k=0.3: target = 50000 + 0.3 * (51000 - 48000) = 50000 + 900 = 50900
    ohlc = _make_breakout_ohlc(open_price=50000, yesterday_high=51000, yesterday_low=48000)
    target_info = strategy.get_target_price("005930", ohlc)
    expected_target = 50000 + 0.3 * (51000 - 48000)
    assert abs(target_info["target_price"] - expected_target) < 1
