"""Unit tests for PortfolioManager (core/execution/portfolio_manager.py)."""

import pytest

from core.execution.portfolio_manager import PortfolioManager
from tests.mocks.mock_kis import MockKISManager, MockKISAuth


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def mgr():
    return PortfolioManager()


@pytest.fixture
def mock_manager():
    return MockKISManager(auth=MockKISAuth())


# ── add_target ────────────────────────────────────────────────

class TestAddTarget:

    def test_adds_code(self, mgr):
        mgr.add_target("005930", "삼성전자")
        assert "005930" in mgr.target_codes
        assert mgr.stock_names["005930"] == "삼성전자"

    def test_no_duplicate(self, mgr):
        mgr.add_target("005930")
        mgr.add_target("005930")
        assert mgr.target_codes.count("005930") == 1

    def test_name_optional(self, mgr):
        mgr.add_target("005930")
        assert "005930" in mgr.target_codes
        assert "005930" not in mgr.stock_names


# ── update_target_codes ───────────────────────────────────────

class TestUpdateTargetCodes:

    def test_preserves_held_codes(self, mgr):
        mgr.portfolio = {"005930": {"qty": 10, "buy_price": 70000}}
        mgr.update_target_codes([{"code": "000660", "name": "SK하이닉스"}])
        assert "005930" in mgr.target_codes
        assert "000660" in mgr.target_codes

    def test_populates_stock_names(self, mgr):
        mgr.update_target_codes([{"code": "005930", "name": "삼성전자"}])
        assert mgr.stock_names["005930"] == "삼성전자"

    def test_no_duplicates(self, mgr):
        mgr.portfolio = {"005930": {"qty": 5, "buy_price": 50000}}
        mgr.update_target_codes([{"code": "005930", "name": "삼성전자"}])
        assert mgr.target_codes.count("005930") == 1

    def test_sorted_output(self, mgr):
        mgr.update_target_codes([
            {"code": "000660", "name": "SK하이닉스"},
            {"code": "005930", "name": "삼성전자"},
        ])
        assert mgr.target_codes == ["000660", "005930"]


# ── sync ──────────────────────────────────────────────────────

class TestSync:

    def test_builds_portfolio_from_balance(self, mgr, mock_manager):
        mock_manager.set_balance(holdings=[
            {"code": "005930", "name": "삼성전자", "qty": 10,
             "orderable_qty": 10, "buy_price": 70000},
        ])
        mgr.sync(mock_manager, whitelist=[])
        assert "005930" in mgr.portfolio
        assert mgr.portfolio["005930"]["qty"] == 10
        assert mgr.stock_names["005930"] == "삼성전자"

    def test_excludes_whitelist(self, mgr, mock_manager):
        mock_manager.set_balance(holdings=[
            {"code": "005930", "name": "삼성전자", "qty": 10,
             "orderable_qty": 10, "buy_price": 70000},
            {"code": "000660", "name": "SK하이닉스", "qty": 5,
             "orderable_qty": 5, "buy_price": 150000},
        ])
        mgr.sync(mock_manager, whitelist=["005930"])
        assert "005930" not in mgr.portfolio
        assert "000660" in mgr.portfolio

    def test_empty_balance_clears(self, mgr, mock_manager):
        mgr.portfolio = {"005930": {"qty": 5, "buy_price": 50000}}
        mock_manager.set_balance(holdings=[])
        mgr.sync(mock_manager, whitelist=[])
        assert mgr.portfolio == {}


# ── get_total_invested ────────────────────────────────────────

class TestGetTotalInvested:

    def test_calculates_with_fee(self, mgr):
        mgr.portfolio = {
            "005930": {"qty": 10, "buy_price": 50000},
        }
        # fee_fn: 0.015% buy fee
        total = mgr.get_total_invested(lambda amount: int(amount * 0.00015))
        expected_amount = 10 * 50000
        expected_fee = int(expected_amount * 0.00015)
        assert total == expected_amount + expected_fee

    def test_uses_stored_buy_fee(self, mgr):
        mgr.portfolio = {
            "005930": {"qty": 10, "buy_price": 50000, "buy_fee": 100},
        }
        total = mgr.get_total_invested(lambda a: 0)
        assert total == 500000 + 100

    def test_empty_portfolio_returns_zero(self, mgr):
        total = mgr.get_total_invested(lambda a: 0)
        assert total == 0

    def test_multiple_holdings_sum(self, mgr):
        mgr.portfolio = {
            "005930": {"qty": 5, "buy_price": 100000, "buy_fee": 75},
            "000660": {"qty": 2, "buy_price": 150000, "buy_fee": 45},
        }
        total = mgr.get_total_invested(lambda a: 0)
        assert total == (5 * 100000 + 75) + (2 * 150000 + 45)


# ── P1: sync edge cases ─────────────────────────────────────

class TestSyncEdgeCases:

    def test_sync_with_missing_buy_price_defaults_to_zero(self, mgr, mock_manager):
        mock_manager.set_balance(holdings=[
            {"code": "005930", "name": "삼성전자", "qty": 5,
             "orderable_qty": 5},
        ])
        mgr.sync(mock_manager, whitelist=[])
        assert "005930" in mgr.portfolio
        assert mgr.portfolio["005930"]["buy_price"] == 0.0

    def test_sync_with_missing_orderable_qty_falls_back_to_qty(self, mgr, mock_manager):
        mock_manager.set_balance(holdings=[
            {"code": "005930", "name": "삼성전자", "qty": 7,
             "buy_price": 60000},
        ])
        mgr.sync(mock_manager, whitelist=[])
        assert mgr.portfolio["005930"]["orderable_qty"] == 7

    def test_sync_when_balance_returns_none(self, mgr, mock_manager):
        """get_balance()가 None을 반환하면 기존 포트폴리오 유지."""
        mock_manager._balance = None  # force None response
        mgr.portfolio = {"005930": {"qty": 5, "buy_price": 60000}}
        mgr.sync(mock_manager, whitelist=[])
        assert "005930" in mgr.portfolio


# ── P1: add_target edge cases ───────────────────────────────

class TestAddTargetEdgeCases:

    def test_add_target_empty_name_not_stored(self, mgr):
        mgr.add_target("005930", name="")
        assert "005930" in mgr.target_codes
        assert "005930" not in mgr.stock_names

    def test_update_target_codes_with_empty_list(self, mgr):
        mgr.portfolio = {"005930": {"qty": 5, "buy_price": 60000}}
        mgr.update_target_codes([])
        assert "005930" in mgr.target_codes
