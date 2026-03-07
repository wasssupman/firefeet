"""Unit tests for RiskGuard (core/execution/risk_guard.py)."""

import datetime
import pytest

from core.execution.risk_guard import RiskGuard


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def guard():
    return RiskGuard()


@pytest.fixture
def base_rules():
    return {
        "no_rebuy_after_sell": {"enabled": True, "allow_if_profitable": False, "cooldown_minutes": 0},
        "max_holdings": {"enabled": False, "default_count": 5},
        "consecutive_sl_brake": {"enabled": True, "max_consecutive": 3, "cooldown_minutes": 30},
        "daily_loss_limit": {"enabled": True, "max_loss_amount": -50000},
    }


# ── reset_daily ───────────────────────────────────────────────

class TestResetDaily:

    def test_clears_all_state(self, guard):
        guard.sold_today = {"005930": {"time": datetime.datetime.now(), "profitable": False}}
        guard.daily_realized_pnl = -30000
        guard.consecutive_sl_count = 2
        guard.sl_brake_until = datetime.datetime.now() + datetime.timedelta(minutes=10)

        guard.reset_daily()

        assert guard.sold_today == {}
        assert guard.daily_realized_pnl == 0
        assert guard.consecutive_sl_count == 0
        assert guard.sl_brake_until is None

    def test_idempotent_same_day(self, guard):
        guard._last_reset_date = datetime.date.today()
        guard.sold_today = {"005930": {"time": datetime.datetime.now(), "profitable": True}}

        guard.reset_daily()

        assert "005930" in guard.sold_today  # not cleared

    def test_resets_on_new_day(self, guard):
        guard._last_reset_date = datetime.date.today() - datetime.timedelta(days=1)
        guard.sold_today = {"005930": {"time": datetime.datetime.now(), "profitable": False}}

        guard.reset_daily()

        assert guard.sold_today == {}
        assert guard._last_reset_date == datetime.date.today()


# ── can_buy ───────────────────────────────────────────────────

class TestCanBuy:

    def test_allowed_when_no_restrictions(self, guard, base_rules):
        ok, reason = guard.can_buy("005930", base_rules, 0, {})
        assert ok is True
        assert reason == ""

    def test_blocked_by_sl_brake(self, guard, base_rules):
        guard.sl_brake_until = datetime.datetime.now() + datetime.timedelta(minutes=30)
        ok, reason = guard.can_buy("005930", base_rules, 0, {})
        assert ok is False
        assert "브레이크" in reason

    def test_blocked_by_daily_loss_limit(self, guard, base_rules):
        guard.daily_realized_pnl = -50000
        ok, reason = guard.can_buy("005930", base_rules, 0, {})
        assert ok is False
        assert "손실한도" in reason

    def test_blocked_by_sold_today(self, guard, base_rules):
        guard.sold_today["005930"] = {"time": datetime.datetime.now(), "profitable": False}
        ok, reason = guard.can_buy("005930", base_rules, 0, {"005930": "삼성전자"})
        assert ok is False
        assert "재매수" in reason

    def test_blocked_by_max_holdings(self, guard, base_rules):
        base_rules["max_holdings"]["enabled"] = True
        base_rules["max_holdings"]["default_count"] = 2
        ok, reason = guard.can_buy("005930", base_rules, 2, {})
        assert ok is False
        assert "최대 보유" in reason

    def test_cooldown_allows_profitable_after_time(self, guard, base_rules):
        base_rules["no_rebuy_after_sell"]["cooldown_minutes"] = 10
        base_rules["no_rebuy_after_sell"]["allow_if_profitable"] = True
        guard.sold_today["005930"] = {
            "time": datetime.datetime.now() - datetime.timedelta(minutes=15),
            "profitable": True,
        }
        ok, reason = guard.can_buy("005930", base_rules, 0, {})
        assert ok is True

    def test_cooldown_blocks_within_window(self, guard, base_rules):
        base_rules["no_rebuy_after_sell"]["cooldown_minutes"] = 60
        base_rules["no_rebuy_after_sell"]["allow_if_profitable"] = True
        guard.sold_today["005930"] = {
            "time": datetime.datetime.now() - datetime.timedelta(minutes=5),
            "profitable": True,
        }
        ok, reason = guard.can_buy("005930", base_rules, 0, {"005930": "삼성전자"})
        assert ok is False
        assert "쿨다운" in reason


# ── record_sell ───────────────────────────────────────────────

class TestRecordSell:

    def test_tracks_sold_today(self, guard, base_rules):
        guard.record_sell("005930", "SELL_AI", 5000, base_rules)
        assert "005930" in guard.sold_today
        assert guard.sold_today["005930"]["profitable"] is True

    def test_accumulates_pnl(self, guard, base_rules):
        guard.record_sell("005930", "SELL_AI", 3000, base_rules)
        guard.record_sell("000660", "SELL_AI", -2000, base_rules)
        assert guard.daily_realized_pnl == 1000

    def test_sl_increments_count(self, guard, base_rules):
        guard.record_sell("005930", "SELL_STOP_LOSS", -5000, base_rules)
        assert guard.consecutive_sl_count == 1

    def test_hard_stop_increments_count(self, guard, base_rules):
        guard.record_sell("005930", "SELL_HARD_STOP", -8000, base_rules)
        assert guard.consecutive_sl_count == 1

    def test_tp_resets_count(self, guard, base_rules):
        guard.consecutive_sl_count = 2
        guard.record_sell("005930", "SELL_TAKE_PROFIT", 5000, base_rules)
        assert guard.consecutive_sl_count == 0

    def test_eod_preserves_count(self, guard, base_rules):
        """SELL_EOD는 카운터를 유지 (SELL_TAKE_PROFIT만 리셋)."""
        guard.consecutive_sl_count = 1
        guard.record_sell("005930", "SELL_EOD", 100, base_rules)
        assert guard.consecutive_sl_count == 1

    def test_brake_triggers_after_max_consecutive(self, guard, base_rules):
        base_rules["consecutive_sl_brake"]["max_consecutive"] = 2
        guard.record_sell("000001", "SELL_STOP_LOSS", -5000, base_rules)
        brake = guard.record_sell("000002", "SELL_STOP_LOSS", -5000, base_rules)
        assert brake is True
        assert guard.sl_brake_until is not None
        assert guard.sl_brake_until > datetime.datetime.now()
        assert guard.consecutive_sl_count == 0  # reset after brake

    def test_no_brake_below_max(self, guard, base_rules):
        base_rules["consecutive_sl_brake"]["max_consecutive"] = 3
        brake = guard.record_sell("005930", "SELL_STOP_LOSS", -5000, base_rules)
        assert brake is False
        assert guard.sl_brake_until is None

    def test_negative_pnl_marked_not_profitable(self, guard, base_rules):
        guard.record_sell("005930", "SELL_HARD_STOP", -10000, base_rules)
        assert guard.sold_today["005930"]["profitable"] is False


# ── P1: SELL_AI/EOD counter behavior (cross-validated) ──────

class TestSellAIDoesNotResetCounter:
    """SELL_AI와 SELL_EOD는 consecutive_sl_count를 리셋하지 않아야 함.
    (교차검증: Quality Reviewer + Test Engineer 동시 발견)"""

    def test_sell_ai_preserves_sl_count(self, guard, base_rules):
        """SELL_AI는 연속SL 카운터를 유지."""
        guard.consecutive_sl_count = 2
        guard.record_sell("005930", "SELL_AI", -3000, base_rules)
        assert guard.consecutive_sl_count == 2

    def test_sell_eod_preserves_sl_count(self, guard, base_rules):
        """SELL_EOD는 연속SL 카운터를 유지."""
        guard.consecutive_sl_count = 1
        guard.record_sell("005930", "SELL_EOD", 100, base_rules)
        assert guard.consecutive_sl_count == 1

    def test_sell_tp_resets_sl_count(self, guard, base_rules):
        """SELL_TAKE_PROFIT만 카운터 리셋."""
        guard.consecutive_sl_count = 2
        guard.record_sell("005930", "SELL_TAKE_PROFIT", 5000, base_rules)
        assert guard.consecutive_sl_count == 0

    def test_sl_brake_not_evaded_by_sell_ai(self, guard, base_rules):
        """SL→AI→SL 시퀀스에서 브레이크가 정상 발동."""
        base_rules["consecutive_sl_brake"]["max_consecutive"] = 3
        guard.record_sell("000001", "SELL_STOP_LOSS", -5000, base_rules)  # count=1
        guard.record_sell("000002", "SELL_AI", -2000, base_rules)         # count=1 유지
        guard.record_sell("000003", "SELL_STOP_LOSS", -5000, base_rules)  # count=2
        guard.record_sell("000004", "SELL_STOP_LOSS", -5000, base_rules)  # count=3 → 브레이크
        assert guard.sl_brake_until is not None


# ── P1: Discord alert + disabled rules ──────────────────────

class TestRecordSellDiscordAlert:

    def test_brake_sends_discord_alert(self, guard, base_rules):
        from unittest.mock import MagicMock
        discord = MagicMock()
        base_rules["consecutive_sl_brake"]["max_consecutive"] = 2
        guard.record_sell("000001", "SELL_STOP_LOSS", -5000, base_rules, discord)
        guard.record_sell("000002", "SELL_STOP_LOSS", -5000, base_rules, discord)
        discord.send.assert_called_once()
        msg = discord.send.call_args[0][0]
        assert "브레이크" in msg

    def test_no_crash_when_discord_is_none(self, guard, base_rules):
        base_rules["consecutive_sl_brake"]["max_consecutive"] = 1
        guard.record_sell("000001", "SELL_STOP_LOSS", -5000, base_rules, discord=None)


class TestCanBuyDisabledRules:

    def test_no_rebuy_disabled_allows_buy(self, guard, base_rules):
        base_rules["no_rebuy_after_sell"]["enabled"] = False
        guard.sold_today["005930"] = {"time": datetime.datetime.now(), "profitable": False}
        ok, _ = guard.can_buy("005930", base_rules, 0, {})
        assert ok is True

    def test_daily_loss_disabled_allows_buy(self, guard, base_rules):
        base_rules["daily_loss_limit"]["enabled"] = False
        guard.daily_realized_pnl = -999_999
        ok, _ = guard.can_buy("005930", base_rules, 0, {})
        assert ok is True

    def test_expired_sl_brake_allows_buy(self, guard, base_rules):
        guard.sl_brake_until = datetime.datetime.now() - datetime.timedelta(seconds=1)
        ok, reason = guard.can_buy("005930", base_rules, 0, {})
        assert ok is True

    def test_zero_pnl_is_not_profitable(self, guard, base_rules):
        guard.record_sell("005930", "SELL_EOD", 0, base_rules)
        assert guard.sold_today["005930"]["profitable"] is False
