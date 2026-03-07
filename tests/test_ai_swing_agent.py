"""Tests for AISwingAgent (core/analysis/ai_swing_agent.py)."""

import json
import pytest
from unittest.mock import patch, MagicMock

from tests.mocks.mock_llm import MockClaudeAnalyst, MockClaudeExecutor, MockVisionAnalyst


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent(analyst=None, executor=None, config_path="config/deep_analysis.yaml"):
    """Construct AISwingAgent with mocked VisionAnalyst and optional LLM overrides."""
    with patch("core.analysis.ai_swing_agent.VisionAnalyst", MockVisionAnalyst):
        from core.analysis.ai_swing_agent import AISwingAgent
        return AISwingAgent(
            config_path=config_path,
            analyst=analyst or MockClaudeAnalyst(),
            executor=executor or MockClaudeExecutor(),
        )


def make_data(price=50000, score=75):
    return {
        "current_data": {"price": price, "high": 51000},
        "screener_score": score,
    }


def make_facts(price=50000, score=75):
    return {"current_price": price, "score": score}


# ---------------------------------------------------------------------------
# _sanity_check: target_price <= 0 → WAIT (H9 regression)
# ---------------------------------------------------------------------------

def test_sanity_check_zero_target_overrides_to_wait():
    agent = make_agent()
    decision = {"decision": "BUY", "target_price": 0, "stop_loss": 47000, "reasoning": "test"}
    facts = make_facts(price=50000)
    result = agent._sanity_check(decision, facts, "005930", "삼성전자")
    assert result["decision"] == "WAIT"
    assert "OVERRIDDEN" in result["reasoning"]


# ---------------------------------------------------------------------------
# _sanity_check: target <= current_price → WAIT
# ---------------------------------------------------------------------------

def test_sanity_check_target_at_or_below_current_price_overrides_to_wait():
    agent = make_agent()
    decision = {"decision": "BUY", "target_price": 50000, "stop_loss": 47000, "reasoning": "test"}
    facts = make_facts(price=50000)
    result = agent._sanity_check(decision, facts, "005930", "삼성전자")
    assert result["decision"] == "WAIT"


def test_sanity_check_target_below_current_price_overrides_to_wait():
    agent = make_agent()
    decision = {"decision": "BUY", "target_price": 48000, "stop_loss": 46000, "reasoning": "test"}
    facts = make_facts(price=50000)
    result = agent._sanity_check(decision, facts, "005930", "삼성전자")
    assert result["decision"] == "WAIT"


# ---------------------------------------------------------------------------
# _sanity_check: stop_loss >= current_price → WAIT
# ---------------------------------------------------------------------------

def test_sanity_check_stop_loss_at_or_above_current_price_overrides_to_wait():
    agent = make_agent()
    decision = {"decision": "BUY", "target_price": 55000, "stop_loss": 50000, "reasoning": "test"}
    facts = make_facts(price=50000)
    result = agent._sanity_check(decision, facts, "005930", "삼성전자")
    assert result["decision"] == "WAIT"


# ---------------------------------------------------------------------------
# _sanity_check: valid BUY passes through unchanged
# ---------------------------------------------------------------------------

def test_sanity_check_valid_buy_not_overridden():
    agent = make_agent()
    decision = {"decision": "BUY", "target_price": 55000, "stop_loss": 47000, "reasoning": "ok"}
    facts = make_facts(price=50000)
    result = agent._sanity_check(decision, facts, "005930", "삼성전자")
    assert result["decision"] == "BUY"


# ---------------------------------------------------------------------------
# _check_and_increment_quota: file lock counter increments
# ---------------------------------------------------------------------------

def test_check_and_increment_quota_increments_count(tmp_path):
    agent = make_agent()
    agent.usage_file = str(tmp_path / "usage.json")
    agent.max_daily_calls = 5

    assert agent._check_and_increment_quota() is True

    with open(agent.usage_file) as f:
        data = json.load(f)
    assert data["count"] == 1


def test_check_and_increment_quota_multiple_calls(tmp_path):
    agent = make_agent()
    agent.usage_file = str(tmp_path / "usage.json")
    agent.max_daily_calls = 3

    for _ in range(3):
        agent._check_and_increment_quota()

    # 4th call should exceed quota
    result = agent._check_and_increment_quota()
    assert result is False


# ---------------------------------------------------------------------------
# _check_and_increment_quota: quota exceeded returns False
# ---------------------------------------------------------------------------

def test_check_and_increment_quota_exceeded_returns_false(tmp_path):
    agent = make_agent()
    agent.usage_file = str(tmp_path / "usage.json")
    agent.max_daily_calls = 2

    import datetime
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    # Pre-seed the file at the limit
    with open(agent.usage_file, "w") as f:
        json.dump({"date": today_str, "count": 2}, f)

    result = agent._check_and_increment_quota()
    assert result is False


# ---------------------------------------------------------------------------
# analyze_trading_opportunity: normal BUY flow
# ---------------------------------------------------------------------------

def test_analyze_trading_opportunity_buy_flow(tmp_path):
    import sys
    import types

    analyst = MockClaudeAnalyst()
    executor = MockClaudeExecutor(decision={
        "decision": "BUY",
        "confidence": 80,
        "strategy_type": "BREAKOUT",
        "target_price": 55000,
        "stop_loss": 47000,
        "qty_ratio": 0.5,
        "reasoning": "Strong breakout setup.",
    })
    agent = make_agent(analyst=analyst, executor=executor)
    agent.usage_file = str(tmp_path / "usage.json")

    # Provide a fake chart_renderer module so the local import inside
    # ai_swing_agent succeeds and returns dummy bytes (vision confirm via MockVisionAnalyst).
    fake_renderer = types.ModuleType("utils.chart_renderer")
    fake_renderer.render_chart_to_bytes = MagicMock(return_value=b"fakepng")

    prev = sys.modules.get("utils.chart_renderer")
    sys.modules["utils.chart_renderer"] = fake_renderer
    try:
        result = agent.analyze_trading_opportunity("005930", "삼성전자", make_data(price=50000))
    finally:
        if prev is None:
            sys.modules.pop("utils.chart_renderer", None)
        else:
            sys.modules["utils.chart_renderer"] = prev

    assert result["decision"] == "BUY"
    assert analyst.call_count == 1
    assert executor.call_count == 1


# ---------------------------------------------------------------------------
# analyze_trading_opportunity: executor raises → fallback JSON
# ---------------------------------------------------------------------------

def test_analyze_trading_opportunity_executor_failure_returns_fallback(tmp_path):
    analyst = MockClaudeAnalyst()
    executor = MockClaudeExecutor()
    executor.set_error()  # forces RuntimeError on execute_decision

    agent = make_agent(analyst=analyst, executor=executor)
    agent.usage_file = str(tmp_path / "usage.json")

    data = make_data(price=50000)
    result = agent.analyze_trading_opportunity("005930", "삼성전자", data)

    assert result["decision"] == "WAIT"
    assert result["confidence"] == 0
