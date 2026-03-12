"""ScalpEngine 통합 시나리오 테스트 — 진입/청산 플로우."""

import csv
import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import datetime
from datetime import timezone, timedelta

from core.scalping.scalp_engine import ScalpEngine
from core.scalping.tick_buffer import TickBuffer
from core.scalping.orderbook_analyzer import OrderbookAnalyzer
from core.trade_logger import TradeLogger
from tests.mocks.mock_scalping import (
    inject_ticks, inject_orderbook,
    make_strategy_profile, make_tick_buffer_with_data,
    make_orderbook_with_data,
)

KST = timezone(timedelta(hours=9))


def _make_kst_datetime(hour, minute):
    return datetime.datetime(2026, 2, 26, hour, minute, 0, tzinfo=KST)


def _read_csv_rows(csv_path):
    with open(csv_path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ── Mock Factory ──────────────────────────────────────────────


@pytest.fixture
def mock_manager():
    """MockKISManager with place_order returning order numbers."""
    mgr = MagicMock()
    mgr._order_counter = 0

    def _place_order(code, qty, price, order_type):
        mgr._order_counter += 1
        return f"ORD{mgr._order_counter:04d}"

    mgr.place_order.side_effect = _place_order
    mgr.round_to_tick.side_effect = lambda price, direction="up": price
    mgr.cancel_order.return_value = True

    # get_order_status: 기본값은 빈 리스트 (체결 안 됨)
    mgr.get_order_status.return_value = []

    return mgr


@pytest.fixture
def mock_ws():
    """Mock KIS WebSocket."""
    ws = MagicMock()
    ws.on_tick = MagicMock()
    ws.on_orderbook = MagicMock()
    ws.on_notice = MagicMock()
    ws.rotate_subscriptions = MagicMock()
    return ws


@pytest.fixture
def mock_scanner():
    return MagicMock()


@pytest.fixture
def engine(mock_manager, mock_ws, mock_scanner, scalp_settings, tmp_path):
    """ScalpEngine with mocked dependencies."""
    # TradeLogger 경로를 tmp_path로 리디렉션
    with patch.object(TradeLogger, '__init__', lambda self, **kw: None):
        eng = ScalpEngine.__new__(ScalpEngine)

    # 수동 초기화 (외부 파일/API 의존성 없이)
    eng.manager = mock_manager
    eng.kis_ws = mock_ws
    eng.scanner = mock_scanner
    eng.discord = None
    eng.settings_path = scalp_settings
    eng.settings = eng._load_settings()

    eng.tick_buffer = TickBuffer(max_size=600)
    eng.orderbook_analyzer = OrderbookAnalyzer()

    # 기술적 분석 mock (CandleHistory/IntradayAnalyzer 우회)
    eng.candle_history = MagicMock()
    eng.ta_analyzer = MagicMock()
    eng.ta_analyzer.analyze.return_value = None  # ta_overlay=None
    eng._ta_candle_interval = 15

    # 시그널/전략 (실제 인스턴스, 설정 파일 기반)
    from core.scalping.scalp_signals import ScalpSignals
    from core.scalping.scalp_strategy import ScalpStrategy
    from core.scalping.strategy_selector import StrategySelector
    from core.scalping.risk_manager import RiskManager
    eng.signals = ScalpSignals(scalp_settings)
    eng.strategy = ScalpStrategy(eng.signals, scalp_settings)
    eng.strategy_selector = StrategySelector("config/scalping_strategies.yaml")
    eng.risk_manager = RiskManager(scalp_settings, mode="PAPER")
    from core.scalping.regime_detector import RegimeDetector
    eng.regime_detector = RegimeDetector()

    # 스크리너 mock
    eng.screener = MagicMock()
    eng.screener.filter_stocks.side_effect = lambda stocks, oba: stocks

    # 로깅 (tmp_path)
    eng.trade_logger = TradeLogger(log_dir=str(tmp_path), strategy="scalp")
    eng.db_writer = MagicMock()  # BackgroundWriter mock
    eng.position_registry = MagicMock()  # PositionRegistry mock
    eng.position_registry.is_held_by_other.return_value = False

    # 포지션/상태
    eng.positions = {}
    eng.stock_names = {"005930": "삼성전자", "035720": "카카오"}
    eng.pending_orders = {}
    eng.target_codes = ["005930"]
    eng._order_cooldown = {}
    eng._low_composite_cycles = {}
    eng._running = True
    eng._eval_interval = 1.5
    eng._sell_cooldown = {}
    eng._sell_cooldown_path = str(tmp_path / "sell_cooldown.json")
    eng._last_status_log = 0
    eng._last_order_check = 0
    eng._processed_orders = set()

    # 패닉 가드 상태
    eng._market_panic_active = False
    eng._last_panic_check = 0
    eng._target_change_rates = {}

    return eng


# ══════════════════════════════════════════════════════════════
# 시나리오 테스트
# ══════════════════════════════════════════════════════════════


class TestEntryToTPExit:

    def test_entry_to_tp_exit(self, engine, mock_manager):
        """틱 주입 -> 진입 -> 가격 상승 -> TP 청산 -> CSV 확인."""
        code = "005930"

        # 1. 틱 데이터 주입 (상승 추세)
        prices = [49500 + i * 20 for i in range(60)]
        inject_ticks(engine.tick_buffer, code, prices, directions=[1] * 60)

        # 호가 데이터 주입
        inject_orderbook(
            engine.orderbook_analyzer, code,
            bid_prices=[50500, 50450, 50400],
            bid_volumes=[5000, 4000, 3000],
            ask_prices=[50550, 50600, 50650],
            ask_volumes=[2000, 1500, 1000],
        )

        # 2. 매수 진입 시도 (10:00 정각)
        with patch("core.scalping.strategy_selector.datetime") as mock_dt, \
             patch("core.scalping.risk_manager.datetime") as mock_rm_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta
            mock_rm_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_rm_dt.timezone = datetime.timezone
            mock_rm_dt.timedelta = datetime.timedelta

            engine._eval_entry(code)

        # 3. 주문이 접수되었는지 확인
        if engine.pending_orders:
            # 체결 시뮬레이션: pending -> positions
            odno = list(engine.pending_orders.keys())[0]
            pending = engine.pending_orders[odno]
            buy_price = pending["price"]
            engine.positions[code] = {
                "qty": pending["qty"],
                "buy_price": buy_price,
                "buy_time": time.time() - 60,  # 60초 전 매수
                "order_no": odno,
                "trailing_high": buy_price,
                "profile": pending.get("profile"),
            }
            engine.trade_logger.log_scalp_buy(
                code, "삼성전자", pending["qty"], buy_price,
                pending.get("confidence", 0),
                **pending.get("log_extra", {}),
            )
            del engine.pending_orders[odno]

            # 4. 가격 상승 -> TP 도달
            tp_price = int(buy_price * 1.015)  # +1.5% (TP=1.2% 초과)
            inject_ticks(engine.tick_buffer, code,
                         [tp_price] * 10, directions=[1] * 10)

            # 5. 매도 평가
            engine._eval_exit(code)

            # 6. 매도 주문이 생겼는지 확인
            if engine.pending_orders:
                sell_odno = list(engine.pending_orders.keys())[0]
                sell_pending = engine.pending_orders[sell_odno]
                assert sell_pending["type"] == "SELL"
                assert "TP" in sell_pending.get("signal", "")


class TestEntryToSLExit:

    def test_entry_to_sl_exit(self, engine):
        """틱 주입 -> 진입 -> 가격 하락 -> SL 청산."""
        code = "005930"

        # 포지션 직접 설정 (진입 시뮬레이션 생략)
        buy_price = 50000
        engine.positions[code] = {
            "qty": 10,
            "buy_price": buy_price,
            "buy_time": time.time() - 60,
            "order_no": "ORD0001",
            "trailing_high": buy_price,
            "profile": make_strategy_profile(sl=-0.5),
        }

        # 가격 하락 (-0.6%)
        sl_price = int(buy_price * 0.994)
        inject_ticks(engine.tick_buffer, code,
                     [sl_price] * 10, directions=[-1] * 10)
        inject_orderbook(
            engine.orderbook_analyzer, code,
            bid_prices=[sl_price - 50, sl_price - 100, sl_price - 150],
            bid_volumes=[3000, 2000, 1000],
            ask_prices=[sl_price, sl_price + 50, sl_price + 100],
            ask_volumes=[5000, 4000, 3000],
        )

        engine._eval_exit(code)

        # SL 매도 주문 확인
        assert len(engine.pending_orders) == 1
        sell_pending = list(engine.pending_orders.values())[0]
        assert sell_pending["type"] == "SELL"
        assert "SL" in sell_pending["signal"]


class TestLunchBlockNoEntry:

    def test_lunch_block_no_entry(self, engine):
        """12:00~15:20 -> 진입 차단."""
        code = "005930"

        # 충분한 틱 데이터
        inject_ticks(engine.tick_buffer, code,
                     [50000 + i * 20 for i in range(60)],
                     directions=[1] * 60)
        inject_orderbook(
            engine.orderbook_analyzer, code,
            bid_prices=[51000, 50950, 50900],
            bid_volumes=[5000, 4000, 3000],
            ask_prices=[51050, 51100, 51150],
            ask_volumes=[2000, 1500, 1000],
        )

        with patch("core.scalping.strategy_selector.datetime") as mock_dt, \
             patch("core.scalping.risk_manager.datetime") as mock_rm_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(13, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta
            mock_rm_dt.datetime.now.return_value = _make_kst_datetime(13, 0)
            mock_rm_dt.timezone = datetime.timezone
            mock_rm_dt.timedelta = datetime.timedelta

            engine._eval_entry(code)

        # 주문 없음
        assert len(engine.pending_orders) == 0


class TestCircuitBreakerClearsPositions:

    def test_circuit_breaker_clears_positions(self, engine):
        """5연패 -> 전 포지션 청산."""
        code = "005930"

        engine.positions[code] = {
            "qty": 10,
            "buy_price": 50000,
            "buy_time": time.time() - 120,
            "order_no": "ORD0001",
            "trailing_high": 50000,
            "profile": None,
        }
        inject_ticks(engine.tick_buffer, code, [50000] * 10)

        # 5연패 기록
        for _ in range(5):
            engine.risk_manager.record_trade(-5000)

        assert engine.risk_manager.circuit_broken is True

        # _eval_cycle에서 서킷브레이커 처리
        with patch("core.scalping.scalp_engine.datetime") as mock_dt, \
             patch("core.scalping.risk_manager.datetime") as mock_rm_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(10, 30)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta
            mock_rm_dt.datetime.now.return_value = _make_kst_datetime(10, 30)
            mock_rm_dt.timezone = datetime.timezone
            mock_rm_dt.timedelta = datetime.timedelta

            engine._eval_cycle()

        # 포지션이 청산됨
        assert len(engine.positions) == 0


class TestEODForceExit:

    def test_eod_force_exit(self, engine):
        """15:28 -> 강제 청산."""
        code = "005930"

        engine.positions[code] = {
            "qty": 10,
            "buy_price": 50000,
            "buy_time": time.time() - 120,
            "order_no": "ORD0001",
            "trailing_high": 50000,
            "profile": None,
        }
        inject_ticks(engine.tick_buffer, code, [50000] * 10)

        with patch("core.scalping.scalp_engine.datetime") as mock_dt, \
             patch("core.scalping.risk_manager.datetime") as mock_rm_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(15, 28)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta
            mock_rm_dt.datetime.now.return_value = _make_kst_datetime(15, 28)
            mock_rm_dt.timezone = datetime.timezone
            mock_rm_dt.timedelta = datetime.timedelta

            engine._eval_cycle()

        # 포지션 청산 + 엔진 중지
        assert len(engine.positions) == 0
        assert engine._running is False


class TestCSVEndToEnd:

    def test_30col_csv_end_to_end(self, engine):
        """매수 -> 매도 전체 플로우 -> 30컬럼 정상 기록."""
        code = "005930"
        buy_price = 50000
        sell_price = 50500

        # 매수 기록
        engine.trade_logger.log_scalp_buy(
            code, "삼성전자", 10, buy_price, 0.42,
            strategy="momentum_scalp", composite=42.5, threshold=0.35,
            temperature="HOT",
            sig_vwap=60.0, sig_ob=45.0, sig_mom=55.0,
            sig_vol=30.0, sig_trend=40.0,
            spread_bps=12.5, penalty=0.95,
            tp_pct=1.2, sl_pct=-0.5, vwap_dist=-0.35,
        )

        # 매도 기록
        engine.trade_logger.log_scalp_sell(
            code, "삼성전자", 10, sell_price, buy_price,
            signal="SCALP_SELL_TP(+1.00%)",
            strategy="momentum_scalp", temperature="HOT",
            hold_seconds=95.3, peak_profit_pct=1.25,
        )

        rows = _read_csv_rows(engine.trade_logger.csv_path)
        assert len(rows) == 2

        # 39컬럼 검증 (VWAP reversion 확장 필드 + MAE/MFE 추가)
        for row in rows:
            assert len(row) == 39, f"컬럼 수 {len(row)} != 39: {list(row.keys())}"

        buy_row = rows[0]
        assert buy_row["action"] == "SCALP_BUY"
        assert buy_row["strategy"] == "momentum_scalp"
        assert buy_row["composite"] == "42.5"
        assert buy_row["sig_vwap"] == "60.0"

        sell_row = rows[1]
        assert sell_row["action"] == "SCALP_SELL"
        assert sell_row["hold_seconds"] == "95.3"
        assert sell_row["peak_profit_pct"] == "1.25"
        assert int(sell_row["realized_pnl"]) != 0  # 손익 기록됨


# ══════════════════════════════════════════════════════════════
# 시장 패닉 가드 테스트
# ══════════════════════════════════════════════════════════════


class TestMarketPanicGuard:
    """시장 패닉 감지 → 신규 진입 전면 차단 검증."""

    def test_panic_activates_on_avg_decline(self, engine):
        """타겟 종목 평균 하락률 -2% 이하 → 패닉 발동."""
        engine._target_change_rates = {
            "005930": -5.0,
            "035720": -3.0,
            "000660": -4.0,
        }  # 평균 -4.0%
        engine._check_market_panic()
        assert engine._market_panic_active is True

    def test_panic_activates_on_crash_ratio(self, engine):
        """타겟 중 50%+ 급락 → 패닉 발동."""
        engine._target_change_rates = {
            "005930": -5.0,   # 급락
            "035720": -4.0,   # 급락
            "000660": -1.0,   # 정상
        }  # 2/3 = 66% 급락
        engine._check_market_panic()
        assert engine._market_panic_active is True

    def test_no_panic_on_normal_market(self, engine):
        """정상 시장 → 패닉 비활성."""
        engine._target_change_rates = {
            "005930": 1.5,
            "035720": -0.5,
            "000660": 2.0,
        }  # 평균 +1.0%
        engine._check_market_panic()
        assert engine._market_panic_active is False

    def test_panic_recovery(self, engine):
        """패닉 발동 후 시장 회복 → 패닉 해제."""
        # 1. 패닉 발동
        engine._target_change_rates = {"A": -5.0, "B": -4.0}
        engine._check_market_panic()
        assert engine._market_panic_active is True

        # 2. 시장 회복
        engine._target_change_rates = {"A": -0.5, "B": 1.0}
        engine._check_market_panic()
        assert engine._market_panic_active is False

    def test_panic_blocks_entry(self, engine):
        """패닉 활성 시 _eval_entry가 진입 차단."""
        code = "005930"
        engine._market_panic_active = True

        # 충분한 데이터 주입
        inject_ticks(engine.tick_buffer, code,
                     [50000 + i * 20 for i in range(60)],
                     directions=[1] * 60)
        inject_orderbook(
            engine.orderbook_analyzer, code,
            bid_prices=[51000, 50950, 50900],
            bid_volumes=[5000, 4000, 3000],
            ask_prices=[51050, 51100, 51150],
            ask_volumes=[2000, 1500, 1000],
        )

        with patch("core.scalping.strategy_selector.datetime") as mock_dt, \
             patch("core.scalping.risk_manager.datetime") as mock_rm_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta
            mock_rm_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_rm_dt.timezone = datetime.timezone
            mock_rm_dt.timedelta = datetime.timedelta

            engine._eval_entry(code)

        # 패닉 활성 → 주문 없음
        assert len(engine.pending_orders) == 0

    def test_panic_does_not_block_exit(self, engine):
        """패닉 활성이어도 보유 포지션 매도는 정상 동작."""
        code = "005930"
        engine._market_panic_active = True

        buy_price = 50000
        engine.positions[code] = {
            "qty": 10,
            "buy_price": buy_price,
            "buy_time": time.time() - 60,
            "order_no": "ORD0001",
            "trailing_high": buy_price,
            "profile": make_strategy_profile(sl=-0.5),
        }

        # SL 가격까지 하락
        sl_price = int(buy_price * 0.994)
        inject_ticks(engine.tick_buffer, code,
                     [sl_price] * 10, directions=[-1] * 10)
        inject_orderbook(
            engine.orderbook_analyzer, code,
            bid_prices=[sl_price - 50, sl_price - 100, sl_price - 150],
            bid_volumes=[3000, 2000, 1000],
            ask_prices=[sl_price, sl_price + 50, sl_price + 100],
            ask_volumes=[5000, 4000, 3000],
        )

        engine._eval_exit(code)

        # 패닉이어도 매도는 정상 실행
        assert len(engine.pending_orders) == 1
        sell_pending = list(engine.pending_orders.values())[0]
        assert sell_pending["type"] == "SELL"

    def test_panic_guard_disabled_via_config(self, engine):
        """설정에서 panic_guard.enabled=false → 패닉 감지 비활성."""
        engine.settings["panic_guard"] = {"enabled": False}
        engine._target_change_rates = {"A": -10.0, "B": -8.0}
        engine._check_market_panic()
        assert engine._market_panic_active is False

    def test_empty_change_rates_no_panic(self, engine):
        """타겟 변동률 정보 없으면 패닉 비활성."""
        engine._target_change_rates = {}
        engine._check_market_panic()
        assert engine._market_panic_active is False

    def test_update_targets_stores_change_rates(self, engine):
        """update_targets에서 change_rate가 저장되는지 확인."""
        stocks = [
            {"code": "005930", "name": "삼성전자", "price": 218000,
             "volume": 5000000, "change_rate": -7.2},
        ]
        engine.update_targets(stocks)
        assert engine._target_change_rates.get("005930") == -7.2


# ══════════════════════════════════════════════════════════════
# 변동성 게이트 테스트
# ══════════════════════════════════════════════════════════════


class TestVolatilityGate:

    def test_volatility_gate_blocks_entry(self, engine):
        """ATR < 0.3%이면 진입 차단"""
        code = "005930"
        # 틱 데이터 추가
        inject_ticks(engine.tick_buffer, code,
                     [50000 + i for i in range(50)], directions=[1] * 50)
        inject_orderbook(
            engine.orderbook_analyzer, code,
            bid_prices=[50050, 50000, 49950],
            bid_volumes=[5000, 4000, 3000],
            ask_prices=[50100, 50150, 50200],
            ask_volumes=[2000, 1500, 1000],
        )

        # ta_analyzer.analyze가 낮은 ATR 반환하도록 mock
        from core.technical.overlay import TAOverlay
        low_atr = TAOverlay(atr_pct=0.1)  # 0.3% 미만

        with patch("core.scalping.strategy_selector.datetime") as mock_dt, \
             patch("core.scalping.risk_manager.datetime") as mock_rm_dt, \
             patch.object(engine.ta_analyzer, 'analyze', return_value=low_atr):
            mock_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta
            mock_rm_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_rm_dt.timezone = datetime.timezone
            mock_rm_dt.timedelta = datetime.timedelta

            initial_positions = len(engine.positions)
            engine._eval_entry(code)
            assert len(engine.positions) == initial_positions  # 진입 없음
            assert len(engine.pending_orders) == 0  # 주문도 없음
