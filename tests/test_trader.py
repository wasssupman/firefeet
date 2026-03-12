"""Tests for FirefeetTrader — P0 money path."""

import datetime
import pytest
import pandas as pd

from core.execution.trader import FirefeetTrader
from core.providers.kis_api import OrderType
from tests.mocks.mock_kis import MockKISManager, MockKISAuth, make_ohlc_dataframe
from tests.mocks.mock_external import MockDiscordClient


# ── Autouse fixtures ─────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Remove all sleep() calls so tests run instantly."""
    monkeypatch.setattr("time.sleep", lambda x: None)


@pytest.fixture(autouse=True)
def patch_trade_logger(tmp_path, monkeypatch):
    """Redirect TradeLogger CSV output to a temp directory."""
    monkeypatch.setenv("TRADE_LOG_DIR", str(tmp_path))
    # Patch the log_dir used inside TradeLogger constructor
    import core.trade_logger as tl_module
    original_init = tl_module.TradeLogger.__init__

    def patched_init(self, log_dir="logs", strategy="main"):
        original_init(self, log_dir=str(tmp_path), strategy=strategy)

    monkeypatch.setattr(tl_module.TradeLogger, "__init__", patched_init)


# ── Trader factory helper ────────────────────────────────────

def make_trader(tmp_path, manager=None, strategy=None, discord=None,
                total_budget=1_000_000, whitelist=None):
    """Create a FirefeetTrader wired to tmp settings file."""
    import yaml, os
    settings = {
        "total_budget": total_budget,
        "max_concurrent_targets": 3,
        "whitelist": whitelist or [],
    }
    settings_path = str(tmp_path / "trading_settings.yaml")
    with open(settings_path, "w") as f:
        yaml.dump(settings, f)

    if manager is None:
        auth = MockKISAuth()
        manager = MockKISManager(auth=auth)
    if strategy is None:
        from core.analysis.technical import VolatilityBreakoutStrategy
        strategy = VolatilityBreakoutStrategy(k=0.5)
    if discord is None:
        discord = MockDiscordClient()

    def data_provider(code):
        df = manager.get_daily_ohlc(code)
        pi = manager.get_current_price(code)
        return df, pi["price"] if pi else None

    t = FirefeetTrader(
        manager=manager,
        strategy=strategy,
        discord_client=discord,
        settings_path=settings_path,
        data_provider_fn=data_provider,
    )
    return t, manager, discord


# ── process_stock: data_provider_fn 미설정 ───────────────────

class TestProcessStockNoProvider:

    def test_skips_when_no_provider(self, tmp_path):
        """data_provider_fn 미설정 시 조용히 스킵 (주문 없음)."""
        auth = MockKISAuth()
        manager = MockKISManager(auth=auth)
        import yaml
        settings_path = str(tmp_path / "s.yaml")
        with open(settings_path, "w") as f:
            yaml.dump({"total_budget": 1_000_000, "whitelist": []}, f)

        from core.analysis.technical import VolatilityBreakoutStrategy
        strategy = VolatilityBreakoutStrategy(k=0.5)

        t = FirefeetTrader(
            manager=manager,
            strategy=strategy,
            settings_path=settings_path,
            data_provider_fn=None,  # explicitly None
        )
        # Must not raise
        t.process_stock("005930", "1000", data_provider_fn=None)
        assert len(manager._orders) == 0


# ── process_stock: buy signal path ──────────────────────────

class TestProcessStockBuy:

    def test_buy_signal_places_order_and_syncs_portfolio(self, tmp_path):
        """매수 시그널 → place_order(BUY) 호출 + sync_portfolio 호출."""
        trader, manager, discord = make_trader(tmp_path)
        code = "005930"

        # Set price above target so breakout fires
        # Default make_ohlc_dataframe: today open=50000, yesterday high=52100, low=48100
        # target = 50000 + (52100-48100)*0.5 = 52000
        # Set current_price well above target
        manager.set_current_price(code, price=53000)

        trader.process_stock(code, "1000")

        buy_orders = [o for o in manager._orders if o["order_type"] == OrderType.BUY]
        assert len(buy_orders) == 1
        assert buy_orders[0]["code"] == code

    def test_buy_order_skipped_when_whitelist(self, tmp_path):
        """화이트리스트 종목은 process_stock에서 즉시 리턴."""
        code = "005930"
        trader, manager, discord = make_trader(tmp_path, whitelist=[code])

        manager.set_current_price(code, price=53000)
        trader.process_stock(code, "1000")

        assert len(manager._orders) == 0

    def test_buy_skipped_when_budget_exhausted(self, tmp_path):
        """총 투자금 >= total_budget → 매수 스킵."""
        trader, manager, discord = make_trader(tmp_path, total_budget=100_000)
        code = "005930"
        # Make current price higher than remaining budget
        manager.set_current_price(code, price=200_000)

        trader.process_stock(code, "1000")

        buy_orders = [o for o in manager._orders if o["order_type"] == OrderType.BUY]
        assert len(buy_orders) == 0

    def test_buy_blocked_by_max_holdings(self, tmp_path):
        """max_holdings 초과 시 매수 차단."""
        trader, manager, discord = make_trader(tmp_path)
        code = "005930"
        # Fill portfolio to capacity
        trader.trading_rules["max_holdings"]["enabled"] = True
        trader.trading_rules["max_holdings"]["default_count"] = 2
        trader.portfolio = {
            "000001": {"qty": 10, "orderable_qty": 10, "buy_price": 50000},
            "000002": {"qty": 10, "orderable_qty": 10, "buy_price": 50000},
        }
        manager.set_current_price(code, price=53000)

        trader.process_stock(code, "1000")

        buy_orders = [o for o in manager._orders if o["order_type"] == OrderType.BUY]
        assert len(buy_orders) == 0

    def test_buy_blocked_when_sold_today(self, tmp_path):
        """당일 매도 종목 재매수 금지."""
        trader, manager, discord = make_trader(tmp_path)
        code = "005930"
        trader.sold_today[code] = {"time": datetime.datetime.now(), "profitable": False}
        manager.set_current_price(code, price=53000)

        trader.process_stock(code, "1000")

        buy_orders = [o for o in manager._orders if o["order_type"] == OrderType.BUY]
        assert len(buy_orders) == 0


# ── process_stock: sell paths ────────────────────────────────

class TestProcessStockSell:

    def _setup_held_position(self, trader, manager, code="005930",
                              buy_price=100_000, qty=5):
        """포트폴리오에 보유 포지션 직접 설정."""
        trader.portfolio[code] = {
            "qty": qty,
            "orderable_qty": qty,
            "buy_price": float(buy_price),
        }
        trader.stock_names[code] = "테스트종목"
        # Sync manager balance too so re-sync does not wipe it
        manager.set_balance(holdings=[{
            "code": code, "name": "테스트종목",
            "qty": qty, "orderable_qty": qty,
            "buy_price": buy_price,
        }])
        # ATR 기반 TP/SL이 buy_price와 일관되도록 OHLC 설정
        # high-low = 1500 → ATR ≈ 1500 → SL=-1.5%, TP=+3.0% (fixed % floor가 적용됨)
        manager.set_ohlc(code, make_ohlc_dataframe(
            base_open=buy_price, base_high=buy_price + 1000,
            base_low=buy_price - 500, base_close=buy_price + 500,
        ))

    def test_sell_take_profit(self, tmp_path):
        """TP 도달 → SELL_TAKE_PROFIT 주문 + portfolio에서 제거."""
        trader, manager, discord = make_trader(tmp_path)
        code = "005930"
        self._setup_held_position(trader, manager, code, buy_price=100_000, qty=5)
        # profit = +4.5% → triggers take_profit (default 4.0%)
        manager.set_current_price(code, price=104_500)

        trader.process_stock(code, "1200")

        sell_orders = [o for o in manager._orders if o["order_type"] == OrderType.SELL]
        assert len(sell_orders) == 1
        assert code not in trader.portfolio

    def test_sell_stop_loss(self, tmp_path):
        """SL 도달 → SELL_STOP_LOSS 주문."""
        trader, manager, discord = make_trader(tmp_path)
        code = "005930"
        self._setup_held_position(trader, manager, code, buy_price=100_000, qty=5)
        # loss = -3.5%
        manager.set_current_price(code, price=96_500)

        trader.process_stock(code, "1200")

        sell_orders = [o for o in manager._orders if o["order_type"] == OrderType.SELL]
        assert len(sell_orders) == 1
        assert code not in trader.portfolio

    def test_sell_eod(self, tmp_path):
        """EOD(15:20 이후) → SELL_EOD 주문."""
        trader, manager, discord = make_trader(tmp_path)
        code = "005930"
        self._setup_held_position(trader, manager, code, buy_price=100_000, qty=5)
        # Flat price, no TP/SL, but EOD time
        manager.set_current_price(code, price=100_100)

        trader.process_stock(code, "1520")

        sell_orders = [o for o in manager._orders if o["order_type"] == OrderType.SELL]
        assert len(sell_orders) == 1

    def test_sell_tp_resets_consecutive_sl_count(self, tmp_path):
        """TP 달성 시 consecutive_sl_count 리셋."""
        trader, manager, discord = make_trader(tmp_path)
        code = "005930"
        trader.consecutive_sl_count = 2
        self._setup_held_position(trader, manager, code, buy_price=100_000, qty=5)
        manager.set_current_price(code, price=104_500)

        trader.process_stock(code, "1200")

        assert trader.consecutive_sl_count == 0

    def test_sell_no_signal_skips_order(self, tmp_path):
        """매도 시그널 없으면 주문 없음."""
        trader, manager, discord = make_trader(tmp_path)
        code = "005930"
        self._setup_held_position(trader, manager, code, buy_price=100_000, qty=5)
        # Flat price, no signal
        manager.set_current_price(code, price=100_500)

        trader.process_stock(code, "1000")

        sell_orders = [o for o in manager._orders if o["order_type"] == OrderType.SELL]
        assert len(sell_orders) == 0
        assert code in trader.portfolio  # still held


# ── consecutive SL brake ─────────────────────────────────────

class TestConsecutiveSLBrake:

    def _setup_held(self, trader, manager, code, buy_price=100_000, qty=5):
        trader.portfolio[code] = {
            "qty": qty, "orderable_qty": qty,
            "buy_price": float(buy_price),
        }
        trader.stock_names[code] = "테스트"
        manager.set_balance(holdings=[{
            "code": code, "name": "테스트",
            "qty": qty, "orderable_qty": qty,
            "buy_price": buy_price,
        }])
        # ATR 기반 TP/SL이 buy_price와 일관되도록 OHLC 설정
        manager.set_ohlc(code, make_ohlc_dataframe(
            base_open=buy_price, base_high=buy_price + 1000,
            base_low=buy_price - 500, base_close=buy_price + 500,
        ))

    def test_sl_brake_set_after_max_consecutive(self, tmp_path):
        """연속 SL max_consecutive회 도달 시 sl_brake_until 설정."""
        trader, manager, discord = make_trader(tmp_path)
        trader.trading_rules["consecutive_sl_brake"]["enabled"] = True
        trader.trading_rules["consecutive_sl_brake"]["max_consecutive"] = 2
        trader.trading_rules["consecutive_sl_brake"]["cooldown_minutes"] = 30

        for i, code in enumerate(["000001", "000002"]):
            self._setup_held(trader, manager, code, buy_price=100_000, qty=3)
            manager.set_current_price(code, price=96_000)  # -4% → SL
            manager.set_balance(holdings=[{
                "code": code, "name": "테스트", "qty": 3,
                "orderable_qty": 3, "buy_price": 100_000,
            }])
            trader.process_stock(code, "1200")

        assert trader.sl_brake_until is not None
        assert trader.sl_brake_until > datetime.datetime.now()

    def test_sl_brake_blocks_new_buys(self, tmp_path):
        """sl_brake_until 활성화 시 매수 차단."""
        trader, manager, discord = make_trader(tmp_path)
        # Set brake for 30 minutes from now
        trader.sl_brake_until = datetime.datetime.now() + datetime.timedelta(minutes=30)
        code = "005930"
        manager.set_current_price(code, price=53000)

        trader.process_stock(code, "1000")

        buy_orders = [o for o in manager._orders if o["order_type"] == OrderType.BUY]
        assert len(buy_orders) == 0


# ── daily_loss_limit ─────────────────────────────────────────

class TestDailyLossLimit:

    def test_buy_blocked_when_daily_loss_limit_reached(self, tmp_path):
        """일일 손실한도 도달 시 매수 차단."""
        trader, manager, discord = make_trader(tmp_path)
        trader.trading_rules["daily_loss_limit"]["enabled"] = True
        trader.trading_rules["daily_loss_limit"]["max_loss_amount"] = -50_000
        # Simulate realized loss already at limit
        trader.daily_realized_pnl = -50_000

        code = "005930"
        manager.set_current_price(code, price=53000)
        trader.process_stock(code, "1000")

        buy_orders = [o for o in manager._orders if o["order_type"] == OrderType.BUY]
        assert len(buy_orders) == 0


# ── reset_daily ──────────────────────────────────────────────

class TestResetDaily:

    def test_reset_clears_state(self, tmp_path):
        """reset_daily() 호출 시 sold_today, pnl, sl_count 초기화."""
        trader, manager, discord = make_trader(tmp_path)
        trader.sold_today = {"005930": {"time": datetime.datetime.now(), "profitable": False}}
        trader.daily_realized_pnl = -30_000
        trader.consecutive_sl_count = 2
        trader.sl_brake_until = datetime.datetime.now() + datetime.timedelta(minutes=10)
        trader._last_reset_date = None  # force reset

        trader.reset_daily()

        assert trader.sold_today == {}
        assert trader.daily_realized_pnl == 0
        assert trader.consecutive_sl_count == 0
        assert trader.sl_brake_until is None

    def test_reset_does_not_repeat_same_day(self, tmp_path):
        """같은 날 두 번 호출 시 두 번째는 무시."""
        trader, manager, discord = make_trader(tmp_path)
        trader._last_reset_date = datetime.date.today()  # already reset today
        trader.sold_today = {"005930": {"time": datetime.datetime.now(), "profitable": False}}

        trader.reset_daily()

        # sold_today should NOT have been cleared
        assert "005930" in trader.sold_today


# ── sync_portfolio ───────────────────────────────────────────

class TestSyncPortfolio:

    def test_sync_builds_portfolio_from_balance(self, tmp_path):
        """잔고 응답 → portfolio dict 변환."""
        trader, manager, discord = make_trader(tmp_path)
        manager.set_balance(holdings=[
            {"code": "005930", "name": "삼성전자", "qty": 10,
             "orderable_qty": 10, "buy_price": 70_000},
            {"code": "000660", "name": "SK하이닉스", "qty": 5,
             "orderable_qty": 5, "buy_price": 150_000},
        ])

        trader.sync_portfolio()

        assert "005930" in trader.portfolio
        assert "000660" in trader.portfolio
        assert trader.portfolio["005930"]["qty"] == 10
        assert trader.portfolio["005930"]["buy_price"] == pytest.approx(70_000)

    def test_sync_excludes_whitelist(self, tmp_path):
        """화이트리스트 종목은 portfolio에서 제외."""
        code_wl = "005930"
        code_ok = "000660"
        trader, manager, discord = make_trader(tmp_path, whitelist=[code_wl])
        manager.set_balance(holdings=[
            {"code": code_wl, "name": "삼성전자", "qty": 10,
             "orderable_qty": 10, "buy_price": 70_000},
            {"code": code_ok, "name": "SK하이닉스", "qty": 5,
             "orderable_qty": 5, "buy_price": 150_000},
        ])

        trader.sync_portfolio()

        assert code_wl not in trader.portfolio
        assert code_ok in trader.portfolio

    def test_sync_empty_balance_clears_portfolio(self, tmp_path):
        """빈 잔고 응답 → 빈 portfolio."""
        trader, manager, discord = make_trader(tmp_path)
        trader.portfolio = {"005930": {"qty": 5, "orderable_qty": 5, "buy_price": 50_000}}
        manager.set_balance(holdings=[])

        trader.sync_portfolio()

        assert trader.portfolio == {}


# ── update_target_codes ──────────────────────────────────────

class TestUpdateTargetCodes:

    def test_held_codes_are_preserved(self, tmp_path):
        """보유 종목은 target_codes에 유지."""
        trader, manager, discord = make_trader(tmp_path)
        trader.portfolio = {"005930": {"qty": 10, "orderable_qty": 10, "buy_price": 70_000}}

        trader.update_target_codes([{"code": "000660", "name": "SK하이닉스"}])

        assert "005930" in trader.target_codes

    def test_new_stocks_added(self, tmp_path):
        """신규 스캔 종목이 target_codes에 추가."""
        trader, manager, discord = make_trader(tmp_path)

        trader.update_target_codes([
            {"code": "005930", "name": "삼성전자"},
            {"code": "000660", "name": "SK하이닉스"},
        ])

        assert "005930" in trader.target_codes
        assert "000660" in trader.target_codes

    def test_no_duplicates_in_target_codes(self, tmp_path):
        """동일 종목 중복 없이 합산."""
        trader, manager, discord = make_trader(tmp_path)
        trader.portfolio = {"005930": {"qty": 5, "orderable_qty": 5, "buy_price": 70_000}}

        trader.update_target_codes([{"code": "005930", "name": "삼성전자"}])

        assert trader.target_codes.count("005930") == 1

    def test_stock_names_populated(self, tmp_path):
        """update_target_codes 호출 시 stock_names 딕셔너리 갱신."""
        trader, manager, discord = make_trader(tmp_path)

        trader.update_target_codes([{"code": "005930", "name": "삼성전자"}])

        assert trader.stock_names.get("005930") == "삼성전자"


# ── P0: __getattr__/__setattr__ delegation ──────────────────

class TestDelegationLayer:
    """__getattr__/__setattr__ 위임이 올바르게 동작하는지 검증."""

    def test_risk_attrs_delegated_to_risk_guard(self, tmp_path):
        """__getattr__가 _RISK_ATTRS를 _risk_guard로 위임."""
        trader, _, _ = make_trader(tmp_path)
        for attr in ('sold_today', 'consecutive_sl_count', 'sl_brake_until',
                     'daily_realized_pnl', '_last_reset_date'):
            assert getattr(trader, attr) is getattr(trader._risk_guard, attr), (
                f"{attr}는 _risk_guard.{attr}와 동일 객체여야 한다"
            )

    def test_portfolio_attrs_delegated_to_portfolio_mgr(self, tmp_path):
        """__getattr__가 _PORTFOLIO_ATTRS를 _portfolio_mgr로 위임."""
        trader, _, _ = make_trader(tmp_path)
        for attr in ('portfolio', 'stock_names', 'target_codes'):
            assert getattr(trader, attr) is getattr(trader._portfolio_mgr, attr), (
                f"{attr}는 _portfolio_mgr.{attr}와 동일 객체여야 한다"
            )

    def test_setattr_risk_writes_to_guard_not_instance_dict(self, tmp_path):
        """risk attr 설정 시 _risk_guard에 기록, instance __dict__에는 없어야."""
        trader, _, _ = make_trader(tmp_path)
        trader.daily_realized_pnl = -99999
        assert trader._risk_guard.daily_realized_pnl == -99999
        assert 'daily_realized_pnl' not in trader.__dict__

    def test_setattr_portfolio_writes_to_portfolio_mgr(self, tmp_path):
        """portfolio attr 설정 시 _portfolio_mgr에 기록."""
        trader, _, _ = make_trader(tmp_path)
        trader.portfolio = {"TEST": {"qty": 1, "buy_price": 100}}
        assert trader._portfolio_mgr.portfolio == {"TEST": {"qty": 1, "buy_price": 100}}
        assert 'portfolio' not in trader.__dict__

    def test_getattr_raises_for_unknown_attribute(self, tmp_path):
        """미정의 속성 접근 시 AttributeError."""
        trader, _, _ = make_trader(tmp_path)
        with pytest.raises(AttributeError, match="FirefeetTrader"):
            _ = trader.nonexistent_xyz_attribute

    def test_risk_attr_set_then_get_roundtrip(self, tmp_path):
        """__setattr__로 쓰고 __getattr__로 읽으면 동일 값."""
        trader, _, _ = make_trader(tmp_path)
        trader.consecutive_sl_count = 7
        assert trader.consecutive_sl_count == 7

    def test_init_order_guards_exist_before_sync(self, tmp_path):
        """_risk_guard/_portfolio_mgr가 __init__의 sync_portfolio 전에 존재."""
        trader, _, _ = make_trader(tmp_path)
        from core.execution.risk_guard import RiskGuard
        from core.execution.portfolio_manager import PortfolioManager
        assert isinstance(trader._risk_guard, RiskGuard)
        assert isinstance(trader._portfolio_mgr, PortfolioManager)

    def test_del_portfolio_item_visible_through_delegation(self, tmp_path):
        """del trader.portfolio[code] → _portfolio_mgr에 즉시 반영."""
        trader, _, _ = make_trader(tmp_path)
        trader.portfolio["005930"] = {"qty": 5, "buy_price": 50000}
        del trader.portfolio["005930"]
        assert "005930" not in trader._portfolio_mgr.portfolio
