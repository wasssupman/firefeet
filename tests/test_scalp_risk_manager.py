"""RiskManager 유닛 테스트 — 리스크 한도 + 서킷브레이커."""

import pytest
import time
from unittest.mock import patch
import datetime
from datetime import timezone, timedelta

from core.scalping.risk_manager import RiskManager

KST = timezone(timedelta(hours=9))


@pytest.fixture
def rm(scalp_settings, scalp_rules):
    """PAPER 모드 RiskManager."""
    return RiskManager(settings_path=scalp_settings,
                       rules_path=scalp_rules, mode="PAPER")


def _make_kst_datetime(hour, minute):
    return datetime.datetime(2026, 2, 26, hour, minute, 0, tzinfo=KST)


class TestCanEnter:

    def test_can_enter_normal(self, rm):
        """정상 상황 -> (True, '')."""
        with patch("core.scalping.risk_manager.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            allowed, reason = rm.can_enter("005930", 500000, {})

        assert allowed is True
        assert reason == ""

    def test_reject_max_positions(self, rm):
        """포지션 수 초과 -> 거절."""
        positions = {
            "005930": {"qty": 10},
            "035720": {"qty": 10},
        }
        # max_simultaneous_positions=2 in settings

        with patch("core.scalping.risk_manager.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            allowed, reason = rm.can_enter("000660", 500000, positions)

        assert allowed is False
        assert "포지션" in reason

    def test_reject_daily_loss_limit(self, rm):
        """일일 손실 -200K 도달 -> 거절."""
        rm.daily_pnl = -200000  # max_daily_loss=200000 for paper

        with patch("core.scalping.risk_manager.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            allowed, reason = rm.can_enter("005930", 500000, {})

        assert allowed is False
        assert "손실" in reason

    def test_circuit_breaker_triggers(self, rm):
        """5연패 -> circuit_broken=True."""
        for _ in range(5):
            rm.record_trade(-5000)

        assert rm.circuit_broken is True
        assert rm.consecutive_losses == 5

    def test_circuit_resets_after_cooldown(self, rm):
        """쿨다운 경과 -> circuit_broken=False."""
        for _ in range(5):
            rm.record_trade(-5000)

        assert rm.circuit_broken is True

        # 쿨다운 시간이 경과한 것처럼 조작
        rm.circuit_break_time = time.time() - 400  # paper cooldown=300s

        with patch("core.scalping.risk_manager.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            allowed, _ = rm.can_enter("005930", 500000, {})

        assert rm.circuit_broken is False
        assert allowed is True

    def test_daily_trade_limit(self, rm):
        """20건 -> 거절."""
        rm.daily_trade_count = 20  # max_daily_trades=20 for paper

        with patch("core.scalping.risk_manager.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            allowed, reason = rm.can_enter("005930", 500000, {})

        assert allowed is False
        assert "거래 횟수" in reason

    def test_force_exit_time(self, rm):
        """15:28 -> should_force_exit()=True."""
        with patch("core.scalping.risk_manager.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(15, 28)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            assert rm.should_force_exit() is True

    def test_no_force_exit_before_time(self, rm):
        """15:20 -> should_force_exit()=False."""
        with patch("core.scalping.risk_manager.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(15, 20)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            assert rm.should_force_exit() is False

    def test_reject_before_market_open(self, rm):
        """08:50 -> no_entry_before='0900' -> 거절."""
        with patch("core.scalping.risk_manager.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(8, 50)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            allowed, reason = rm.can_enter("005930", 500000, {})

        assert allowed is False
        assert "장 초반" in reason

    def test_reject_after_market_close(self, rm):
        """15:26 -> no_entry_after='1525' -> 거절."""
        with patch("core.scalping.risk_manager.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(15, 26)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            allowed, reason = rm.can_enter("005930", 500000, {})

        assert allowed is False
        assert "진입 금지" in reason

    def test_reject_position_value(self, rm):
        """건당 포지션 한도 초과."""
        with patch("core.scalping.risk_manager.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            # paper max_position_value=2,000,000
            allowed, reason = rm.can_enter("005930", 3000000, {})

        assert allowed is False
        assert "포지션 한도" in reason


class TestRecordTrade:

    def test_win_resets_consecutive_losses(self, rm):
        """수익 거래 -> consecutive_losses 리셋."""
        rm.record_trade(-5000)
        rm.record_trade(-5000)
        assert rm.consecutive_losses == 2

        rm.record_trade(3000)
        assert rm.consecutive_losses == 0

    def test_daily_pnl_accumulates(self, rm):
        """일일 손익 누적."""
        rm.record_trade(-5000)
        rm.record_trade(3000)
        rm.record_trade(-2000)

        assert rm.daily_pnl == -4000
        assert rm.daily_trade_count == 3

    def test_reset_daily(self, rm):
        """일일 리셋."""
        rm.record_trade(-5000)
        rm.daily_trade_count = 10

        rm.reset_daily()

        assert rm.daily_pnl == 0
        assert rm.daily_trade_count == 0
        assert rm.consecutive_losses == 0
        assert rm.circuit_broken is False


class TestRecordBuy:

    def test_record_buy_increments_count(self, rm):
        """record_buy() 후 daily_buy_count 증가."""
        assert rm.daily_buy_count == 0
        rm.record_buy("005930")
        assert rm.daily_buy_count == 1
        rm.record_buy("035720")
        assert rm.daily_buy_count == 2

    def test_can_enter_uses_buy_count(self, rm):
        """buy_count가 한도에 도달하면 거절."""
        rm.daily_buy_count = 20  # max_daily_trades=20 for paper

        with patch("core.scalping.risk_manager.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            allowed, reason = rm.can_enter("005930", 500000, {})

        assert allowed is False
        assert "거래 횟수" in reason


class TestCircuitBreakerResets:

    def test_circuit_breaker_max_resets(self, rm):
        """1회 리셋 후 재서킷 시 해제 거부."""
        # 첫 번째 서킷브레이커
        for _ in range(5):
            rm.record_trade(-5000)
        assert rm.circuit_broken is True

        # 쿨다운 경과 → 1회 리셋
        rm.circuit_break_time = time.time() - 400
        assert rm.check_circuit_reset() is True
        assert rm.circuit_reset_count == 1

        # 두 번째 서킷브레이커
        for _ in range(5):
            rm.record_trade(-5000)
        assert rm.circuit_broken is True

        # 쿨다운 경과 → 리셋 거부 (max_circuit_resets=1)
        rm.circuit_break_time = time.time() - 400
        assert rm.check_circuit_reset() is False
        assert rm.circuit_broken is True  # 여전히 broken

    def test_circuit_breaker_resets_daily(self, rm):
        """reset_daily() 후 리셋 카운트 초기화."""
        rm.circuit_reset_count = 1
        rm.reset_daily()
        assert rm.circuit_reset_count == 0


# ══════════════════════════════════════════════════════════════
# C-1 회귀 테스트: 서킷브레이커 이중 리셋 버그 수정 검증
# Task #2 C-1: can_enter()와 check_circuit_reset() 동시 호출 시
#              circuit_reset_count가 2회 증가하던 버그 수정.
# ══════════════════════════════════════════════════════════════


class TestCircuitBreakerNoDuplicateReset:
    """C-1 수정 회귀 테스트: 리셋 카운트 이중 증가 방지."""

    def test_can_enter_and_check_reset_same_cycle_no_double_count(self, rm):
        """같은 사이클에서 check_circuit_reset() + can_enter() 호출 시
        circuit_reset_count가 1번만 증가해야 한다 (C-1 버그 수정 검증)."""
        # 5연패로 서킷브레이커 발동
        for _ in range(5):
            rm.record_trade(-5000)
        assert rm.circuit_broken is True
        assert rm.circuit_reset_count == 0

        # 쿨다운 경과 시뮬레이션
        rm.circuit_break_time = time.time() - 400

        # _eval_cycle() 패턴: check_circuit_reset() 먼저 호출
        reset_result = rm.check_circuit_reset()
        assert reset_result is True         # 해제 성공
        assert rm.circuit_broken is False
        assert rm.circuit_reset_count == 1  # 1회만 증가

        # 이후 can_enter() 호출 (circuit_broken=False이므로 서킷 블록 없음)
        with patch("core.scalping.risk_manager.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            allowed, _ = rm.can_enter("005930", 500000, {})

        # can_enter()가 추가로 reset_count를 증가시키지 않아야 함
        assert rm.circuit_reset_count == 1  # 여전히 1 (이중 증가 없음)
        assert allowed is True

    def test_can_enter_circuit_broken_still_in_cooldown_no_reset(self, rm):
        """쿨다운 미경과 시 can_enter()가 circuit_reset_count를 변경하지 않는다."""
        for _ in range(5):
            rm.record_trade(-5000)
        assert rm.circuit_broken is True

        # 쿨다운 미경과 (50초 전)
        rm.circuit_break_time = time.time() - 50

        with patch("core.scalping.risk_manager.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            allowed, reason = rm.can_enter("005930", 500000, {})

        assert allowed is False
        assert rm.circuit_reset_count == 0   # 카운트 변화 없음
        assert rm.circuit_broken is True     # 여전히 broken

    def test_check_circuit_reset_idempotent_when_not_broken(self, rm):
        """서킷브레이커가 발동되지 않았을 때 check_circuit_reset()은 False 반환,
        카운트 변경 없음."""
        assert rm.circuit_broken is False
        result = rm.check_circuit_reset()
        assert result is False
        assert rm.circuit_reset_count == 0

    def test_sequential_resets_count_correctly(self, rm):
        """서킷브레이커가 여러 번 발동/해제될 때 카운트가 정확히 1씩 증가."""
        max_resets = 1  # paper 모드 기본값

        # 첫 번째 서킷브레이커 발동 → 해제
        for _ in range(5):
            rm.record_trade(-5000)
        rm.circuit_break_time = time.time() - 400
        result1 = rm.check_circuit_reset()
        assert result1 is True
        count_after_first = rm.circuit_reset_count
        assert count_after_first == 1

        # 두 번째 서킷브레이커 발동 → 해제 불가 (한도 초과)
        for _ in range(5):
            rm.record_trade(-5000)
        rm.circuit_break_time = time.time() - 400
        result2 = rm.check_circuit_reset()
        assert result2 is False              # max_resets=1 도달, 해제 거부
        assert rm.circuit_reset_count == 1  # 카운트 변화 없음


class TestPerStockTracking:

    def test_per_stock_loss_blacklist(self, rm):
        """2회 손실 종목 거절."""
        rm.record_trade(-5000, code="005930")
        rm.record_trade(-5000, code="005930")

        allowed, reason = rm.can_trade_stock("005930")
        assert allowed is False
        assert "종목 손실" in reason

    def test_per_stock_entry_limit(self, rm):
        """3회 진입 종목 거절."""
        rm.record_buy("005930")
        rm.record_buy("005930")
        rm.record_buy("005930")

        allowed, reason = rm.can_trade_stock("005930")
        assert allowed is False
        assert "종목 진입" in reason

    def test_can_trade_stock_resets_daily(self, rm):
        """reset_daily() 후 종목별 카운터 초기화."""
        rm.record_trade(-5000, code="005930")
        rm.record_trade(-5000, code="005930")
        rm.record_buy("035720")
        rm.record_buy("035720")
        rm.record_buy("035720")

        rm.reset_daily()

        allowed1, _ = rm.can_trade_stock("005930")
        allowed2, _ = rm.can_trade_stock("035720")
        assert allowed1 is True
        assert allowed2 is True

    def test_record_trade_with_code(self, rm):
        """record_trade(pnl, code) 종목별 손실 추적."""
        rm.record_trade(-3000, code="005930")
        rm.record_trade(2000, code="005930")  # 수익은 카운트 안됨
        rm.record_trade(-4000, code="035720")

        assert rm._per_stock_losses.get("005930") == 1
        assert rm._per_stock_losses.get("035720") == 1


class TestTemperature:

    def test_apply_temperature(self, rm):
        """온도 적용 -> temperature_level 업데이트."""
        rm.apply_temperature({"level": "HOT", "temperature": 80})
        assert rm.temperature_level == "HOT"

    def test_temperature_affects_max_positions(self, rm):
        """HOT -> max_positions=3, COLD -> max_positions=1."""
        rm.apply_temperature({"level": "HOT", "temperature": 80})
        assert rm._get_max_positions() == 3

        rm.apply_temperature({"level": "COLD", "temperature": -80})
        assert rm._get_max_positions() == 1
