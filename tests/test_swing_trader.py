"""
tests/test_swing_trader.py

SwingTrader 버그 검증 테스트.
분석 파일: docs/swing_strategy_review.md, docs/swing_code_review.md

각 테스트의 의미:
  - 버그가 존재할 때 PASS: 버그 동작을 정확히 포착한 것 (assert 조건 = 버그 동작)
  - 버그가 수정될 때 FAIL: 수정 후 테스트를 수정해야 함을 의미
  - 단, CRITICAL 버그는 예외가 발생하므로 pytest.fail()로 구분
"""

import datetime
import pytest
import yaml
from unittest.mock import MagicMock, patch, call

from tests.mocks.mock_kis import MockKISManager, MockKISAuth, make_ohlc_dataframe
from tests.mocks.mock_external import MockDiscordClient
from tests.mocks.mock_llm import MockClaudeAnalyst, MockClaudeExecutor, MockVisionAnalyst


# ─────────────────────────────────────────────────────────
# Fixtures & Helpers
# ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """테스트에서 sleep() 호출 제거."""
    monkeypatch.setattr("time.sleep", lambda x: None)


@pytest.fixture(autouse=True)
def patch_trade_logger(tmp_path, monkeypatch):
    """TradeLogger CSV 출력을 임시 디렉토리로 우회."""
    import core.trade_logger as tl_module
    original_init = tl_module.TradeLogger.__init__

    def patched_init(self, log_dir="logs", strategy="main"):
        original_init(self, log_dir=str(tmp_path), strategy=strategy)

    monkeypatch.setattr(tl_module.TradeLogger, "__init__", patched_init)


@pytest.fixture(autouse=True)
def patch_db_writer(monkeypatch):
    """BackgroundWriter를 MagicMock으로 대체."""
    monkeypatch.setattr(
        "core.execution.swing_trader.BackgroundWriter",
        lambda **kw: MagicMock(),
    )


def make_ai_agent(decision=None, confidence=85):
    """기본 BUY 결정을 내리는 Mock AI 에이전트 생성."""
    with patch("core.analysis.ai_swing_agent.VisionAnalyst", MockVisionAnalyst):
        from core.analysis.ai_swing_agent import AISwingAgent
        agent = AISwingAgent(
            config_path="config/deep_analysis.yaml",
            analyst=MockClaudeAnalyst(),
            executor=MockClaudeExecutor(decision=decision or {
                "decision": "BUY",
                "confidence": confidence,
                "strategy_type": "BREAKOUT",
                "target_price": 55000,
                "stop_loss": 47000,
                "qty_ratio": 0.5,
                "reasoning": "Mock: Strong breakout.",
            }),
        )
    return agent


def make_swing_trader(tmp_path, manager=None, ai_agent=None, discord=None,
                      total_budget=1_000_000):
    """SwingTrader 인스턴스 생성 헬퍼."""
    settings = {"total_budget": total_budget, "whitelist": []}
    settings_path = str(tmp_path / "trading_settings.yaml")
    with open(settings_path, "w") as f:
        yaml.dump(settings, f)

    if manager is None:
        manager = MockKISManager(auth=MockKISAuth())
        manager.set_balance(
            holdings=[],
            total_asset=total_budget,
            deposit=total_budget,
            available_cash=total_budget,
        )

    if ai_agent is None:
        ai_agent = make_ai_agent()

    if discord is None:
        discord = MockDiscordClient()

    from core.execution.swing_trader import SwingTrader
    trader = SwingTrader(
        manager=manager,
        ai_agent=ai_agent,
        strategy=None,
        discord_client=discord,
        settings_path=settings_path,
    )
    return trader, manager, discord


def make_ai_data(price=50000, ohlc=None):
    """process_stock_with_ai에 전달되는 ai_data dict 생성."""
    if ohlc is None:
        ohlc = make_ohlc_dataframe(days=30, base_open=50000,
                                   base_high=52000, base_low=48000,
                                   base_close=51000)
    return {
        "current_data": {"price": price, "high": price * 1.02},
        "screener_score": 75,
        "ohlc": ohlc,
        "supply": {"sentiment": "BULLISH"},
        "news": [],
    }


# ─────────────────────────────────────────────────────────
# BUG 1: log_trade() 메서드 미존재
#
# swing_trader.py:111,167 — TradeLogger.log_trade()를 호출하지만
# TradeLogger에는 log_buy()/log_sell()만 존재한다.
# 매수/매도 API 호출 직후 AttributeError 발생 → 거래 미로깅,
# 매수/매도 이후 로직(알림, 상태 업데이트)이 모두 실행되지 않음.
# ─────────────────────────────────────────────────────────

class TestBug1LogTradeMissing:
    """BUG 1: TradeLogger에 log_trade() 메서드가 없어 매수/매도 시 AttributeError 발생."""

    def test_trade_logger_has_no_log_trade_method(self, tmp_path):
        """TradeLogger에 log_trade() 메서드가 없음을 직접 확인한다."""
        from core.trade_logger import TradeLogger
        logger = TradeLogger(log_dir=str(tmp_path), strategy="swing")
        assert not hasattr(logger, "log_trade"), (
            "BUG 1: log_trade()가 존재하지 않아야 한다. "
            "이 assert가 실패하면 버그가 이미 수정된 것이다."
        )

    def test_buy_execution_raises_attribute_error_from_log_trade(self, tmp_path):
        """BUG 1 수정됨: log_buy()로 교체되어 AttributeError가 발생하지 않는다."""
        trader, manager, discord = make_swing_trader(tmp_path)
        code = "005930"
        trader.stock_names[code] = "삼성전자"

        # 매수 가능 상태: portfolio 비어 있음, 잔고 충분, confidence >= 80
        manager.set_balance(holdings=[], deposit=1_000_000, available_cash=1_000_000)

        ai_data = make_ai_data(price=50000)
        data_fn = lambda c: ai_data

        # 수정 후: AttributeError 없이 정상 실행됨
        trader.process_stock_with_ai(code, "1000", data_fn)
        assert hasattr(trader.trade_logger, "log_buy"), "log_buy()가 존재한다."

    def test_sell_execution_raises_attribute_error_from_log_trade(self, tmp_path):
        """BUG 1 수정됨: log_sell()로 교체되어 AttributeError가 발생하지 않는다."""
        trader, manager, discord = make_swing_trader(tmp_path)
        code = "005930"
        trader.stock_names[code] = "삼성전자"
        trader.portfolio[code] = {
            "qty": 5, "orderable_qty": 5, "buy_price": 50000.0
        }
        trader.trading_rules["hard_stop_loss_pct"] = -7.0

        # ohlc=None: ATR 계산 비활성화 → effective_hard_sl = -7.0 고정
        # price=45000: profit_rate = -10% → -10 <= -7 → 하드 손절 발동
        ai_data = make_ai_data(price=45000, ohlc=None)
        ai_data["ohlc"] = None  # ATR 확대 차단
        data_fn = lambda c: ai_data

        # 수정 후: AttributeError 없이 정상 실행됨, portfolio에서 삭제됨
        trader.process_stock_with_ai(code, "1000", data_fn)
        assert code not in trader.portfolio, "하드 손절 후 portfolio에서 제거됨"

    def test_trade_logger_has_log_buy_and_log_sell(self, tmp_path):
        """TradeLogger는 log_buy()와 log_sell()을 정상 제공한다 (올바른 API)."""
        from core.trade_logger import TradeLogger
        logger = TradeLogger(log_dir=str(tmp_path), strategy="swing")
        assert hasattr(logger, "log_buy"), "log_buy()가 존재해야 한다."
        assert hasattr(logger, "log_sell"), "log_sell()이 존재해야 한다."


# ─────────────────────────────────────────────────────────
# BUG 2: send_trade_alert() 메서드 미존재
#
# swing_trader.py:117,172 — discord.send_trade_alert()를 호출하지만
# DiscordClient에는 send()만 있다.
# 매매 실행 후 Discord 알림 경로에서 AttributeError 발생.
# ─────────────────────────────────────────────────────────

class TestBug2SendTradeAlertMissing:
    """BUG 2: DiscordClient에 send_trade_alert()가 없어 매매 알림 시 AttributeError."""

    def test_discord_client_has_no_send_trade_alert_method(self):
        """MockDiscordClient(실제 인터페이스 반영)에 send_trade_alert()가 없음 확인."""
        discord = MockDiscordClient()
        assert not hasattr(discord, "send_trade_alert"), (
            "BUG 2: send_trade_alert()가 존재하지 않아야 한다."
        )

    def test_execute_sell_raises_attribute_error_from_send_trade_alert(self, tmp_path):
        """BUG 2 수정됨: send()로 교체되어 AttributeError가 발생하지 않는다."""
        trader, manager, discord = make_swing_trader(tmp_path)
        code = "005930"
        trader.stock_names[code] = "삼성전자"
        trader.portfolio[code] = {"qty": 5, "orderable_qty": 5, "buy_price": 50000.0}

        # 수정 후: AttributeError 없이 정상 실행됨
        trader._execute_sell(code, "삼성전자", 5, 51000, "SELL_AI", "test")
        assert len(discord.messages) >= 1, "discord.send()가 호출되어 메시지가 전송됨"

    def test_discord_has_send_method_as_correct_api(self):
        """DiscordClient는 send()를 정상 제공한다 (올바른 API)."""
        discord = MockDiscordClient()
        assert hasattr(discord, "send"), "send()가 올바른 Discord API이다."
        discord.send("테스트 메시지")
        assert len(discord.messages) == 1


# ─────────────────────────────────────────────────────────
# BUG 3: reset_daily() 메인 루프 미호출
#
# run_ai_swing_bot.py — 메인 while 루프에서 trader.reset_daily() 미호출.
# sold_today, daily_realized_pnl, consecutive_sl_count가 영구 누적됨.
# 다음 날에도 전날 매도 종목 재매수 불가, 손실한도 초과로 매수 차단.
# ─────────────────────────────────────────────────────────

class TestBug3ResetDailyNotCalled:
    """BUG 3: 메인 루프에서 reset_daily() 미호출로 일일 상태가 영구 누적된다."""

    def test_sold_today_blocks_rebuy_on_next_day_without_reset(self, tmp_path):
        """reset_daily() 미호출 시 다음 날에도 어제 매도 종목의 재매수가 차단된다."""
        trader, manager, discord = make_swing_trader(tmp_path)
        code = "005930"

        # 어제 날짜로 sold_today에 추가 (다른 날 매도 시뮬레이션)
        yesterday = datetime.datetime.now() - datetime.timedelta(days=1)
        trader.sold_today[code] = {"time": yesterday, "profitable": False}
        # _last_reset_date를 어제로 설정 (오늘 리셋이 필요한 상태)
        trader._last_reset_date = datetime.date.today() - datetime.timedelta(days=1)

        # reset_daily()를 호출하지 않으면 어제 기록이 남아 재매수 차단됨
        can_buy, reason = trader._can_buy(code)
        assert can_buy is False, (
            "BUG 3: reset_daily() 미호출 시 어제 매도 종목의 재매수가 금지된다."
        )

    def test_reset_daily_restores_rebuy_on_new_day(self, tmp_path):
        """reset_daily() 호출 후에는 어제 매도 종목을 오늘 재매수 가능하다."""
        trader, manager, discord = make_swing_trader(tmp_path)
        code = "005930"

        yesterday = datetime.datetime.now() - datetime.timedelta(days=1)
        trader.sold_today[code] = {"time": yesterday, "profitable": False}
        trader._last_reset_date = datetime.date.today() - datetime.timedelta(days=1)

        # reset_daily() 호출하면 초기화됨
        trader.reset_daily()

        can_buy, reason = trader._can_buy(code)
        assert can_buy is True, f"reset_daily() 이후 재매수 가능해야 한다: {reason}"
        assert trader.sold_today == {}
        assert trader.daily_realized_pnl == 0
        assert trader.consecutive_sl_count == 0
        assert trader.sl_brake_until is None

    def test_daily_loss_pnl_accumulates_across_days_without_reset(self, tmp_path):
        """reset_daily() 미호출 시 daily_realized_pnl이 음수로 누적되어 매수가 영구 차단된다."""
        trader, manager, discord = make_swing_trader(tmp_path)

        # 전날 손실한도 도달 상태 시뮬레이션
        trader.daily_realized_pnl = -50_001
        trader.trading_rules["daily_loss_limit"]["enabled"] = True
        trader.trading_rules["daily_loss_limit"]["max_loss_amount"] = -50_000

        code = "005930"
        can_buy, reason = trader._can_buy(code)
        assert can_buy is False, (
            "BUG 3 파생: reset_daily() 미호출 시 전날 손실이 누적되어 "
            "오늘 매수가 영구 차단된다."
        )

    def test_reset_daily_is_idempotent_within_same_day(self, tmp_path):
        """같은 날 두 번 reset_daily() 호출 시 두 번째는 무시된다."""
        trader, manager, discord = make_swing_trader(tmp_path)
        trader._last_reset_date = None  # 첫 번째 리셋 허용

        trader.sold_today["005930"] = {
            "time": datetime.datetime.now(), "profitable": False
        }
        trader.reset_daily()  # 첫 번째: 초기화됨
        assert trader.sold_today == {}

        # 첫 번째 리셋 이후 다시 추가
        trader.sold_today["005930"] = {
            "time": datetime.datetime.now(), "profitable": False
        }
        trader.reset_daily()  # 두 번째: 같은 날이므로 무시됨
        assert "005930" in trader.sold_today, (
            "같은 날 두 번째 reset_daily()는 무시되어야 한다."
        )


# ─────────────────────────────────────────────────────────
# BUG 4: avg_price == 0 포지션 무한 보유
#
# swing_trader.py:131-132 — avg_price <= 0이면 즉시 return하여
# 포지션이 portfolio에서 제거되지 않음 → 영구 잔류.
# 하드 손절도 동작하지 않음.
# ─────────────────────────────────────────────────────────

class TestBug4AvgPriceZeroInfiniteHold:
    """BUG 4: avg_price == 0인 포지션이 매도 불가 상태로 영구 잔류한다."""

    def test_avg_price_zero_position_survives_ai_sell_decision(self, tmp_path):
        """buy_price=0인 포지션은 AI SELL 결정이 있어도 매도되지 않는다."""
        sell_decision = {
            "decision": "SELL",
            "confidence": 90,
            "strategy_type": "AI_SELL",
            "target_price": 0,
            "stop_loss": 0,
            "qty_ratio": 1.0,
            "reasoning": "Sell now.",
        }
        ai_agent = make_ai_agent(decision=sell_decision)
        trader, manager, discord = make_swing_trader(tmp_path, ai_agent=ai_agent)

        code = "005930"
        trader.stock_names[code] = "삼성전자"
        # avg_price(buy_price) = 0으로 손상된 포지션
        trader.portfolio[code] = {
            "qty": 5, "orderable_qty": 5, "buy_price": 0.0
        }

        ai_data = make_ai_data(price=51000)
        data_fn = lambda c: ai_data

        # _process_ai_sell()이 avg_price<=0 에서 조기 return하므로 예외 없음
        trader.process_stock_with_ai(code, "1000", data_fn)

        # BUG 4: portfolio에서 제거되지 않음
        assert code in trader.portfolio, (
            "BUG 4 확인: avg_price=0인 포지션이 portfolio에서 제거되지 않았다."
        )
        assert len(manager._orders) == 0, (
            "BUG 4 확인: avg_price=0이면 매도 주문이 발생하지 않는다."
        )

    def test_avg_price_zero_position_survives_extreme_price_drop(self, tmp_path):
        """buy_price=0이면 -90% 폭락에도 하드 손절이 동작하지 않는다."""
        trader, manager, discord = make_swing_trader(tmp_path)
        code = "005930"
        trader.stock_names[code] = "삼성전자"
        trader.portfolio[code] = {
            "qty": 5, "orderable_qty": 5, "buy_price": 0.0
        }
        trader.trading_rules["hard_stop_loss_pct"] = -7.0

        # 극단적인 가격 하락도 손절 안 됨 (avg_price=0 조기 return)
        ai_data = make_ai_data(price=1000)
        data_fn = lambda c: ai_data

        trader.process_stock_with_ai(code, "1000", data_fn)

        assert code in trader.portfolio, (
            "BUG 4 파생: avg_price=0이면 하드 손절도 작동하지 않는다."
        )


# ─────────────────────────────────────────────────────────
# BUG 5: 매도 후 상태 미추적
#
# swing_trader.py:162-177 _execute_sell() — 매도 성공 후
# sold_today, daily_realized_pnl, consecutive_sl_count,
# portfolio 삭제를 수행하지 않는다.
# 모든 안전장치(일일 손실한도, 재매수 금지, 연속SL 브레이크)가 무력화됨.
#
# 주의: BUG 1(log_trade)이 먼저 충돌하므로 log_trade를 mock으로 우회하여
#       BUG 5를 독립 검증한다.
# ─────────────────────────────────────────────────────────

class TestBug5SellStateNotTracked:
    """BUG 5: _execute_sell() 성공 후 상태 변수를 업데이트하지 않는다."""

    def _make_trader_with_position(self, tmp_path, code="005930"):
        """테스트용 SwingTrader 생성 (포지션 보유 상태)."""
        trader, manager, discord = make_swing_trader(tmp_path)
        trader.stock_names[code] = "삼성전자"
        trader.portfolio[code] = {
            "qty": 5, "orderable_qty": 5, "buy_price": 50000.0
        }
        return trader, manager, discord

    def test_portfolio_not_deleted_after_execute_sell(self, tmp_path):
        """BUG 5 수정됨: _execute_sell() 후 portfolio에서 종목이 삭제된다."""
        code = "005930"
        trader, manager, discord = self._make_trader_with_position(tmp_path, code)

        trader._execute_sell(code, "삼성전자", 5, 51000, "SELL_AI", "test reason")

        assert code not in trader.portfolio, (
            "_execute_sell() 후 portfolio에서 종목이 삭제되어야 한다."
        )

    def test_sold_today_not_updated_after_execute_sell(self, tmp_path):
        """BUG 5 수정됨: _execute_sell() 후 sold_today에 종목이 등록된다."""
        code = "005930"
        trader, manager, discord = self._make_trader_with_position(tmp_path, code)

        trader._execute_sell(code, "삼성전자", 5, 51000, "SELL_AI", "test reason")

        assert code in trader.sold_today, (
            "_execute_sell() 후 sold_today에 종목이 등록되어야 한다."
        )

    def test_daily_realized_pnl_not_updated_after_execute_sell(self, tmp_path):
        """BUG 5 수정됨: _execute_sell() 후 daily_realized_pnl이 업데이트된다."""
        code = "005930"
        trader, manager, discord = self._make_trader_with_position(tmp_path, code)
        trader.portfolio[code]["buy_price"] = 50000.0
        initial_pnl = trader.daily_realized_pnl  # 0

        # 수익 매도: 51000 > 50000 → 양수 손익
        trader._execute_sell(code, "삼성전자", 5, 51000, "SELL_AI", "profit")

        assert trader.daily_realized_pnl != initial_pnl, (
            "_execute_sell() 후 daily_realized_pnl이 업데이트되어야 한다."
        )

    def test_consecutive_sl_count_not_incremented_after_hard_stop(self, tmp_path):
        """BUG 5 수정됨: 하드 손절(SELL_HARD_STOP) 후 consecutive_sl_count가 증가한다."""
        code = "005930"
        trader, manager, discord = self._make_trader_with_position(tmp_path, code)
        initial_sl_count = trader.consecutive_sl_count  # 0

        trader._execute_sell(code, "삼성전자", 5, 45000, "SELL_HARD_STOP", "ATR 손절")

        assert trader.consecutive_sl_count > initial_sl_count or trader.sl_brake_until is not None, (
            "SELL_HARD_STOP 후 consecutive_sl_count가 증가하거나 브레이크가 설정되어야 한다."
        )

    def test_multiple_sells_dont_trigger_sl_brake_due_to_bug5(self, tmp_path):
        """BUG 5 수정됨: 연속 3회 손절 후 sl_brake_until이 설정된다."""
        trader, manager, discord = make_swing_trader(tmp_path)
        trader.trading_rules["consecutive_sl_brake"]["enabled"] = True
        trader.trading_rules["consecutive_sl_brake"]["max_consecutive"] = 3
        trader.trading_rules["consecutive_sl_brake"]["cooldown_minutes"] = 30

        for i, code in enumerate(["000001", "000002", "000003"]):
            trader.stock_names[code] = f"테스트{i}"
            trader.portfolio[code] = {"qty": 3, "orderable_qty": 3, "buy_price": 100_000.0}
            trader._execute_sell(code, f"테스트{i}", 3, 93_000, "SELL_HARD_STOP", "손절")

        assert trader.sl_brake_until is not None, (
            "3회 연속 손절 후 sl_brake_until이 설정되어야 한다."
        )


# ─────────────────────────────────────────────────────────
# BUG 6: discard_client 파라미터 타이포
#
# trader.py:10 — 파라미터명이 discard_client (discord_client이어야 함)
# 키워드 인자로 discord_client=dc 전달 시 TypeError 발생
# (Python이 미지의 키워드 인자를 받지 않음).
# ─────────────────────────────────────────────────────────

class TestBug6DiscardClientTypo:
    """BUG 6: trader.py 파라미터명 타이포 discard_client vs discord_client."""

    def test_keyword_discord_client_raises_typeerror(self, tmp_path):
        """BUG 6 수정됨: discord_client= 키워드 인자가 정상 동작한다."""
        settings = {"total_budget": 1_000_000, "whitelist": []}
        settings_path = str(tmp_path / "s.yaml")
        with open(settings_path, "w") as f:
            yaml.dump(settings, f)

        manager = MockKISManager(auth=MockKISAuth())
        discord = MockDiscordClient()

        from core.execution.trader import FirefeetTrader
        from core.analysis.technical import VolatilityBreakoutStrategy
        strategy = VolatilityBreakoutStrategy(k=0.5)

        # 수정 후: discord_client= 키워드 인자가 정상 동작함
        trader = FirefeetTrader(
            manager=manager,
            strategy=strategy,
            discord_client=discord,
            settings_path=settings_path,
        )
        assert trader.discord is discord, "discord_client= 키워드 인자로 discord가 설정된다."

    def test_correct_keyword_discard_client_works(self, tmp_path):
        """실제 파라미터명 discard_client=로 전달하면 discord가 설정된다 (혼동 유발)."""
        settings = {"total_budget": 1_000_000, "whitelist": []}
        settings_path = str(tmp_path / "s.yaml")
        with open(settings_path, "w") as f:
            yaml.dump(settings, f)

        manager = MockKISManager(auth=MockKISAuth())
        discord = MockDiscordClient()

        from core.execution.trader import FirefeetTrader
        from core.analysis.technical import VolatilityBreakoutStrategy
        strategy = VolatilityBreakoutStrategy(k=0.5)

        # BUG 6 수정됨: discard_client=는 이제 TypeError를 발생시킨다
        with pytest.raises(TypeError):
            FirefeetTrader(
                manager=manager,
                strategy=strategy,
                discard_client=discord,  # 이제 잘못된 키워드명 → TypeError
                settings_path=settings_path,
            )

    def test_positional_argument_bypasses_typo(self, tmp_path):
        """위치 인자로 전달하면 타이포와 무관하게 작동한다 (SwingTrader 방식)."""
        settings = {"total_budget": 1_000_000, "whitelist": []}
        settings_path = str(tmp_path / "s.yaml")
        with open(settings_path, "w") as f:
            yaml.dump(settings, f)

        manager = MockKISManager(auth=MockKISAuth())
        discord = MockDiscordClient()

        from core.execution.trader import FirefeetTrader
        from core.analysis.technical import VolatilityBreakoutStrategy
        strategy = VolatilityBreakoutStrategy(k=0.5)

        # 위치 인자로 전달 (SwingTrader.__init__이 super().__init__ 호출 방식)
        trader = FirefeetTrader(manager, strategy, discord, settings_path)
        assert trader.discord is discord, (
            "위치 인자로 전달하면 discord가 올바르게 설정된다."
        )


# ─────────────────────────────────────────────────────────
# BUG 7: TradeLogger 잘못된 생성자 호출
#
# swing_trader.py:27 — TradeLogger("trades_swing.csv") 호출.
# TradeLogger(log_dir, strategy) 시그니처에서 "trades_swing.csv"가
# log_dir로 해석됨 → strategy가 기본값 "main"이 됨.
# 결과적으로 올바른 전략명 "swing"이 아닌 "main"으로 초기화됨.
# ─────────────────────────────────────────────────────────

class TestBug7TradeLoggerWrongConstructor:
    """BUG 7: SwingTrader가 TradeLogger를 잘못된 인자로 초기화한다."""

    def test_swing_trader_trade_logger_strategy_is_not_swing(self, tmp_path):
        """BUG 7 수정됨: SwingTrader의 trade_logger.strategy가 'swing'이다."""
        trader, manager, discord = make_swing_trader(tmp_path)

        assert trader.trade_logger.strategy == "swing", (
            "BUG 7 수정: TradeLogger(strategy='swing')으로 올바르게 초기화되어야 한다."
        )

    def test_correct_trade_logger_init_signature(self, tmp_path):
        """TradeLogger의 올바른 초기화 방식을 확인한다."""
        from core.trade_logger import TradeLogger
        logger = TradeLogger(log_dir=str(tmp_path), strategy="swing")
        assert logger.strategy == "swing"
        assert logger.log_dir == str(tmp_path)
        import os
        assert logger.csv_path == os.path.join(str(tmp_path), "trades_swing.csv")


# ─────────────────────────────────────────────────────────
# BUG 8: screener_score 항상 0으로 하드코딩
#
# run_ai_swing_bot.py:275 — "screener_score": 0으로 하드코딩.
# AI Executor가 받는 facts의 score가 항상 0 → 종목 품질 정보 미반영.
# ─────────────────────────────────────────────────────────

class TestBug8ScreenerScoreHardcoded:
    """BUG 8: ai_data의 screener_score가 항상 0으로 하드코딩된다."""

    def _make_agent_with_executor_capture(self, tmp_path):
        """AI Executor 호출을 캡처하는 에이전트 생성."""
        executor = MockClaudeExecutor()
        analyst = MockClaudeAnalyst()
        with patch("core.analysis.ai_swing_agent.VisionAnalyst", MockVisionAnalyst):
            from core.analysis.ai_swing_agent import AISwingAgent
            agent = AISwingAgent(
                config_path="config/deep_analysis.yaml",
                analyst=analyst,
                executor=executor,
            )
        agent.usage_file = str(tmp_path / "usage.json")
        return agent, executor

    def _run_analysis(self, agent, score):
        """screener_score를 지정하여 분석 실행."""
        import sys, types
        fake_renderer = types.ModuleType("utils.chart_renderer")
        fake_renderer.render_chart_to_bytes = MagicMock(return_value=b"fakepng")
        prev = sys.modules.get("utils.chart_renderer")
        sys.modules["utils.chart_renderer"] = fake_renderer
        try:
            ai_data = {
                "current_data": {"price": 50000, "high": 51000},
                "screener_score": score,
            }
            agent.analyze_trading_opportunity("005930", "삼성전자", ai_data)
        finally:
            if prev is None:
                sys.modules.pop("utils.chart_renderer", None)
            else:
                sys.modules["utils.chart_renderer"] = prev

    def test_score_zero_is_passed_to_executor_facts(self, tmp_path):
        """screener_score=0이면 Executor facts에 score=0이 전달된다 (run_ai_swing_bot 현재 동작)."""
        agent, executor = self._make_agent_with_executor_capture(tmp_path)
        self._run_analysis(agent, score=0)

        assert executor._calls, "Executor가 호출되어야 한다."
        received_score = executor._calls[0]["facts"].get("score", -1)
        assert received_score == 0, (
            "BUG 8 확인: Executor가 score=0을 수신한다.\n"
            "7팩터 스코어링 결과가 AI 판단에 반영되지 않는다."
        )

    def test_nonzero_score_is_passed_correctly_when_provided(self, tmp_path):
        """screener_score가 0이 아닌 값으로 전달되면 Executor facts에 정상 반영된다."""
        agent, executor = self._make_agent_with_executor_capture(tmp_path)
        self._run_analysis(agent, score=82)

        assert executor._calls, "Executor가 호출되어야 한다."
        received_score = executor._calls[0]["facts"].get("score", -1)
        assert received_score == 82, (
            f"screener_score=82가 facts에 전달되어야 한다. 실제: {received_score}"
        )


# ─────────────────────────────────────────────────────────
# BUG 9: 온도 시스템 미연결
#
# run_ai_swing_bot.py — strategy.apply_temperature() 미호출.
# 항상 NEUTRAL 파라미터로 매매 (k=0.5, TP=3.0%, SL=-3.0%).
# ─────────────────────────────────────────────────────────

class TestBug9TemperatureNotApplied:
    """BUG 9: VolatilityBreakoutStrategy에 온도가 적용되지 않는다."""

    def test_strategy_temperature_level_defaults_to_neutral_without_apply(self):
        """apply_temperature() 미호출 시 temperature_level이 NEUTRAL로 고정된다."""
        from core.analysis.technical import VolatilityBreakoutStrategy
        strategy = VolatilityBreakoutStrategy(k=0.5)

        # 기본값 확인 (온도 미적용 상태)
        assert strategy.temperature_level == "NEUTRAL"
        assert strategy.k == 0.5

    def test_apply_temperature_changes_k_value(self):
        """apply_temperature() 호출 시 k값이 온도 프로파일에 맞게 변경된다."""
        from core.analysis.technical import VolatilityBreakoutStrategy
        strategy = VolatilityBreakoutStrategy(k=0.5)

        hot_profile = {
            "k": 0.3, "tp_pct": 4.0, "sl_pct": -3.0,
            "max_position_pct": 0.35,
            "atr_sl_multiplier": 2.0, "atr_tp_multiplier": 3.5,
        }
        strategy.apply_temperature({"level": "HOT", "score": 75}, {"HOT": hot_profile})

        assert strategy.k == 0.3, f"HOT 온도에서 k=0.3이어야 한다. 실제: {strategy.k}"
        assert strategy.temperature_level == "HOT"

    def test_cold_temperature_increases_k_value(self):
        """COLD 온도 적용 시 k값이 보수적으로(높게) 변경된다."""
        from core.analysis.technical import VolatilityBreakoutStrategy
        strategy = VolatilityBreakoutStrategy(k=0.5)

        cold_profile = {
            "k": 0.7, "tp_pct": 2.0, "sl_pct": -2.0,
            "max_position_pct": 0.15,
            "atr_sl_multiplier": 3.0, "atr_tp_multiplier": 2.0,
        }
        strategy.apply_temperature({"level": "COLD", "score": -70}, {"COLD": cold_profile})

        assert strategy.k == 0.7, f"COLD 온도에서 k=0.7이어야 한다. 실제: {strategy.k}"
        assert strategy.temperature_level == "COLD"


# ─────────────────────────────────────────────────────────
# BUG 10: 포지션 사이징 무제한
#
# swing_trader.py:99 — target_allocation_per_stock 미정의 → 기본값 1,000,000원.
# max_position_amount 규칙이 SwingTrader._process_ai_buy()에서 체크되지 않음.
# ─────────────────────────────────────────────────────────

class TestBug10UnboundedPositionSizing:
    """BUG 10: SwingTrader의 포지션 사이징에 상한선이 없다."""

    def test_target_allocation_per_stock_not_in_trading_rules(self, tmp_path):
        """trading_rules에 target_allocation_per_stock이 정의되지 않았다."""
        trader, manager, discord = make_swing_trader(tmp_path)

        assert "target_allocation_per_stock" not in trader.trading_rules, (
            "BUG 10 확인: target_allocation_per_stock이 trading_rules에 없어 "
            "기본값 1,000,000원이 사용된다."
        )

    def test_buy_amount_exceeds_max_position_limit(self, tmp_path):
        """max_position_amount(15만원) 규칙이 SwingTrader에서 적용되지 않는다.

        주당 10,000원 × 100주 = 1,000,000원 (가용 잔고 전액 매수)
        max_position_amount=150,000원이 적용됐다면 15주만 매수해야 함.
        """
        trader, manager, discord = make_swing_trader(
            tmp_path, total_budget=1_000_000
        )
        # max_position_amount 활성화
        trader.trading_rules["max_position_amount"] = {
            "enabled": True,
            "default_amount": 150_000
        }

        code = "005930"
        trader.stock_names[code] = "삼성전자"
        manager.set_balance(holdings=[], deposit=1_000_000, available_cash=1_000_000)

        ai_data = make_ai_data(price=10_000)  # 주당 10,000원
        data_fn = lambda c: ai_data

        try:
            trader.process_stock_with_ai(code, "1000", data_fn)
        except (AttributeError, Exception):
            pass  # log_trade/send_trade_alert 에러 무시

        buy_orders = [o for o in manager._orders]
        if buy_orders:
            qty = buy_orders[0]["qty"]
            # max_position_amount(15만원) 적용 시: 최대 15주
            # 미적용 시: target_allocation=100만원 → 최대 100주
            assert qty > 15, (
                "BUG 10 확인: max_position_amount 미적용으로 "
                f"{qty}주를 매수한다 (제한 적용 시 최대 15주)."
            )


# ─────────────────────────────────────────────────────────
# 정상 동작 회귀 테스트
# ─────────────────────────────────────────────────────────

class TestSwingTraderCorrectBehavior:
    """버그와 무관하게 올바르게 작동해야 하는 기능들."""

    def test_can_buy_returns_false_when_sold_today(self, tmp_path):
        """당일 매도한 종목은 재매수 불가."""
        trader, manager, discord = make_swing_trader(tmp_path)
        code = "005930"
        trader.sold_today[code] = {
            "time": datetime.datetime.now(), "profitable": False
        }

        can_buy, reason = trader._can_buy(code)
        assert can_buy is False
        assert "재매수" in reason or "금지" in reason

    def test_can_buy_returns_false_during_sl_brake(self, tmp_path):
        """sl_brake_until 활성 시 매수 불가."""
        trader, manager, discord = make_swing_trader(tmp_path)
        trader.sl_brake_until = (
            datetime.datetime.now() + datetime.timedelta(minutes=30)
        )

        can_buy, reason = trader._can_buy("005930")
        assert can_buy is False

    def test_process_stock_with_ai_skips_when_price_is_zero(self, tmp_path):
        """current_price=0이면 조용히 스킵하고 주문이 발생하지 않는다."""
        trader, manager, discord = make_swing_trader(tmp_path)
        code = "005930"

        ai_data = make_ai_data(price=0)
        data_fn = lambda c: ai_data

        trader.process_stock_with_ai(code, "1000", data_fn)

        assert len(manager._orders) == 0

    def test_hard_stop_triggers_sell_order_at_7pct_loss(self, tmp_path):
        """하드 손절(-7%) 도달 시 매도 API가 호출된다.

        ohlc=None으로 ATR 확대를 비활성화하여 hard_stop_loss_pct=-7.0을 고정시킨다.
        BUG 1(log_trade)이 충돌하지만 place_order는 그 이전에 실행됨을 확인한다.
        """
        trader, manager, discord = make_swing_trader(tmp_path)
        trader.trading_rules["hard_stop_loss_pct"] = -7.0

        code = "005930"
        trader.stock_names[code] = "삼성전자"
        trader.portfolio[code] = {
            "qty": 5, "orderable_qty": 5, "buy_price": 100_000.0
        }

        # ohlc=None: ATR 계산 비활성화 → effective_hard_sl = -7.0
        # price=92_000: profit_rate = -8% → -8 <= -7 → 하드 손절 발동
        ai_data = make_ai_data(price=92_000)
        ai_data["ohlc"] = None  # ATR 확대 차단
        data_fn = lambda c: ai_data

        # BUG 1으로 인해 AttributeError 발생하지만 그 전에 place_order는 호출됨
        try:
            trader.process_stock_with_ai(code, "1000", data_fn)
        except AttributeError:
            pass  # log_trade 에러는 예상된 BUG 1

        sell_orders = [o for o in manager._orders]
        assert len(sell_orders) >= 1, (
            "하드 손절(-8%)에서 place_order(SELL)가 호출되어야 한다."
        )

    def test_ai_decision_cache_prevents_duplicate_api_calls(self, tmp_path):
        """AI 결정 캐시(TTL=30분) 내에는 AI를 재호출하지 않는다."""
        import time as time_module
        trader, manager, discord = make_swing_trader(tmp_path)
        code = "005930"
        trader.stock_names[code] = "삼성전자"

        # 30분 TTL 내 WAIT 캐시 삽입
        trader._ai_decision_cache[code] = {
            "decision": "WAIT",
            "timestamp": time_module.time(),
        }

        ai_data = make_ai_data(price=50000)
        trader.process_stock_with_ai(code, "1000", lambda c: ai_data)

        # 캐시 히트 → AI 미호출 → 주문 없음
        assert len(manager._orders) == 0

    def test_process_stock_with_ai_holds_position_during_ai_hold(self, tmp_path):
        """AI가 HOLD를 판단하면 보유 포지션에서 매도하지 않는다."""
        hold_decision = {
            "decision": "HOLD",
            "confidence": 60,
            "strategy_type": "HOLD",
            "target_price": 0,
            "stop_loss": 0,
            "qty_ratio": 0,
            "reasoning": "Hold signal.",
        }
        ai_agent = make_ai_agent(decision=hold_decision)
        trader, manager, discord = make_swing_trader(tmp_path, ai_agent=ai_agent)

        code = "005930"
        trader.stock_names[code] = "삼성전자"
        # 손익 중립 구간 (하드 손절 미트리거)
        trader.portfolio[code] = {
            "qty": 5, "orderable_qty": 5, "buy_price": 50_000.0
        }
        trader.trading_rules["hard_stop_loss_pct"] = -7.0

        # 현재가 51,000 → 수익률 +2% → 하드 손절 미트리거
        ai_data = make_ai_data(price=51_000)
        data_fn = lambda c: ai_data

        trader.process_stock_with_ai(code, "1000", data_fn)

        # HOLD → 매도 없음
        assert len(manager._orders) == 0
        assert code in trader.portfolio
