"""Tests for KISManager — order placement, price queries, balance, and tick size."""

import json
import pytest
from unittest.mock import patch, MagicMock

from core.providers.kis_api import KISManager, OrderType
from tests.mocks.mock_kis import MockKISAuth


# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def account_info():
    return {
        "CANO": "12345678",
        "ACNT_PRDT_CD": "01",
    }


@pytest.fixture
def manager(account_info):
    """KISManager backed by MockKISAuth in PAPER mode."""
    auth = MockKISAuth()
    return KISManager(auth=auth, account_info=account_info, mode="PAPER")


def _mock_response(payload):
    """Build a MagicMock response that returns payload from .json()."""
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    resp.status_code = 200
    resp.text = ""
    return resp


# ── place_order (BUY) ────────────────────────────────────────

def test_place_order_buy_sends_correct_body(manager):
    """place_order(BUY): 요청 body에 PDNO, ORD_QTY, CANO 포함."""
    success_resp = _mock_response({
        "rt_cd": "0",
        "msg1": "OK",
        "output": {"ODNO": "0000001", "KRX_FWDG_ORD_ORGNO": "00950"},
    })

    captured_body = {}

    def fake_request(method, url, headers=None, data=None, **kwargs):
        if data:
            captured_body.update(json.loads(data))
        return success_resp

    with patch("requests.request", side_effect=fake_request):
        with patch.object(manager.auth, "get_hashkey", return_value="hk"):
            order_no = manager.place_order("005930", 10, 70000, OrderType.BUY)

    assert order_no == "0000001"
    assert captured_body["PDNO"] == "005930"
    assert captured_body["ORD_QTY"] == "10"
    assert captured_body["CANO"] == "12345678"


def test_place_order_buy_uses_buy_tr_id(manager):
    """PAPER + BUY → tr_id = VTTC0802U."""
    success_resp = _mock_response({
        "rt_cd": "0",
        "msg1": "OK",
        "output": {"ODNO": "0000002", "KRX_FWDG_ORD_ORGNO": "00950"},
    })

    captured_headers = {}

    def fake_request(method, url, headers=None, data=None, **kwargs):
        if headers:
            captured_headers.update(headers)
        return success_resp

    with patch("requests.request", side_effect=fake_request):
        with patch.object(manager.auth, "get_hashkey", return_value="hk"):
            manager.place_order("005930", 5, 70000, OrderType.BUY)

    assert captured_headers.get("tr_id") == "VTTC0802U"


# ── place_order (SELL) ───────────────────────────────────────

def test_place_order_sell_returns_order_number(manager):
    """place_order(SELL): 정상 응답 → 주문번호 반환."""
    success_resp = _mock_response({
        "rt_cd": "0",
        "msg1": "OK",
        "output": {"ODNO": "0000003", "KRX_FWDG_ORD_ORGNO": "00950"},
    })

    with patch("requests.request", return_value=success_resp):
        with patch.object(manager.auth, "get_hashkey", return_value="hk"):
            order_no = manager.place_order("005930", 5, 69000, OrderType.SELL)

    assert order_no == "0000003"


def test_place_order_sell_uses_sell_tr_id(manager):
    """PAPER + SELL → tr_id = VTTC0801U."""
    success_resp = _mock_response({
        "rt_cd": "0",
        "msg1": "OK",
        "output": {"ODNO": "0000004", "KRX_FWDG_ORD_ORGNO": "00950"},
    })

    captured_headers = {}

    def fake_request(method, url, headers=None, data=None, **kwargs):
        if headers:
            captured_headers.update(headers)
        return success_resp

    with patch("requests.request", side_effect=fake_request):
        with patch.object(manager.auth, "get_hashkey", return_value="hk"):
            manager.place_order("005930", 3, 68000, OrderType.SELL)

    assert captured_headers.get("tr_id") == "VTTC0801U"


def test_place_order_returns_none_on_api_error(manager):
    """rt_cd != '0' → None 반환."""
    error_resp = _mock_response({
        "rt_cd": "1",
        "msg1": "주문 실패",
        "output": {},
    })

    with patch("requests.request", return_value=error_resp):
        with patch.object(manager.auth, "get_hashkey", return_value="hk"):
            result = manager.place_order("005930", 1, 70000, OrderType.BUY)

    assert result is None


def test_place_order_market_price_sets_ord_dvsn_01(manager):
    """price=0 → ORD_DVSN='01' (시장가) body 확인."""
    success_resp = _mock_response({
        "rt_cd": "0",
        "msg1": "OK",
        "output": {"ODNO": "0000005", "KRX_FWDG_ORD_ORGNO": "00950"},
    })

    captured_body = {}

    def fake_request(method, url, headers=None, data=None, **kwargs):
        if data:
            captured_body.update(json.loads(data))
        return success_resp

    with patch("requests.request", side_effect=fake_request):
        with patch.object(manager.auth, "get_hashkey", return_value="hk"):
            manager.place_order("005930", 1, 0, OrderType.BUY)

    assert captured_body["ORD_DVSN"] == "01"
    assert captured_body["ORD_UNPR"] == "0"


# ── get_current_price() ──────────────────────────────────────

def test_get_current_price_returns_dict_with_price(manager):
    """정상 응답 → price, change, volume 포함 dict 반환."""
    resp = _mock_response({
        "output": {
            "stck_prpr": "70000",
            "prdy_vrss": "500",
            "prdy_ctrt": "0.72",
            "acml_vol": "5000000",
            "stck_hgpr": "71000",
        }
    })

    with patch.object(manager, "_request", return_value=resp.json()):
        result = manager.get_current_price("005930")

    assert result is not None
    assert result["code"] == "005930"
    assert result["price"] == 70000
    assert result["change"] == 500
    assert result["volume"] == 5000000


def test_get_current_price_returns_none_on_exception(manager):
    """_request 예외 → None 반환."""
    with patch.object(manager, "_request", side_effect=Exception("network error")):
        result = manager.get_current_price("005930")

    assert result is None


# ── get_daily_ohlc() ─────────────────────────────────────────

def test_get_daily_ohlc_returns_dataframe_with_columns(manager):
    """정상 응답 → date, open, high, low, close, volume 컬럼 포함 DataFrame."""
    payload = {
        "rt_cd": "0",
        "msg1": "OK",
        "output": [
            {
                "stck_bsop_date": "20260226",
                "stck_oprc": "69000",
                "stck_hgpr": "71000",
                "stck_lwpr": "68000",
                "stck_clpr": "70000",
                "acml_vol": "5000000",
            }
        ],
    }

    with patch.object(manager, "_request", return_value=payload):
        df = manager.get_daily_ohlc("005930")

    assert df is not None
    assert not df.empty
    expected_cols = {"date", "open", "high", "low", "close", "volume"}
    assert expected_cols.issubset(set(df.columns))
    assert df.iloc[0]["close"] == 70000


def test_get_daily_ohlc_returns_none_on_api_error(manager):
    """rt_cd != '0' → None 반환."""
    payload = {"rt_cd": "1", "msg1": "조회 실패", "output": []}

    with patch.object(manager, "_request", return_value=payload):
        result = manager.get_daily_ohlc("005930")

    assert result is None


def test_get_daily_ohlc_returns_none_on_exception(manager):
    """_request 예외 → None 반환."""
    with patch.object(manager, "_request", side_effect=Exception("timeout")):
        result = manager.get_daily_ohlc("005930")

    assert result is None


# ── get_balance() ────────────────────────────────────────────

def test_get_balance_returns_expected_structure(manager):
    """정상 응답 → total_asset, deposit, holdings 포함 dict."""
    payload = {
        "output1": [
            {
                "pdno": "005930",
                "prdt_name": "삼성전자",
                "hldg_qty": "10",
                "ord_psbl_qty": "10",
                "pchs_avg_pric": "68000.0",
                "evlu_pfls_rt": "2.94",
            }
        ],
        "output2": [
            {
                "tot_evlu_amt": "10700000",
                "dnca_tot_amt": "5000000",
            }
        ],
    }

    with patch.object(manager, "_request", return_value=payload):
        balance = manager.get_balance()

    assert balance is not None
    assert balance["total_asset"] == 10700000
    assert balance["deposit"] == 5000000
    assert len(balance["holdings"]) == 1
    assert balance["holdings"][0]["code"] == "005930"
    assert balance["holdings"][0]["qty"] == 10


def test_get_balance_returns_none_on_exception(manager):
    """_request 예외 → None 반환."""
    with patch.object(manager, "_request", side_effect=Exception("api down")):
        result = manager.get_balance()

    assert result is None


# ── cancel_order() ───────────────────────────────────────────

def test_cancel_order_sends_correct_params(manager):
    """cancel_order(): ORGN_ODNO, ORD_QTY 파라미터가 body에 전달되는지 확인."""
    success_resp = _mock_response({
        "rt_cd": "0",
        "msg1": "OK",
        "output": {"KRX_FWDG_ORD_ORGNO": "00950"},
    })

    captured_body = {}

    def fake_request(method, url, headers=None, data=None, **kwargs):
        if data:
            captured_body.update(json.loads(data))
        return success_resp

    with patch("requests.request", side_effect=fake_request):
        with patch.object(manager.auth, "get_hashkey", return_value="hk"):
            manager.cancel_order("0001234", "005930", 5)

    assert captured_body["ORGN_ODNO"] == "0001234"
    assert captured_body["ORD_QTY"] == "5"
    assert captured_body["RVSE_CNCL_DVSN_CD"] == "02"


# ── get_tick_size() ──────────────────────────────────────────

@pytest.mark.parametrize("price,expected_tick", [
    (999, 1),
    (1999, 1),
    (2000, 5),
    (4999, 5),
    (5000, 10),
    (19999, 10),
    (20000, 50),
    (49999, 50),
    (50000, 100),
    (199999, 100),
    (200000, 500),
    (499999, 500),
    (500000, 1000),
    (1000000, 1000),
])
def test_get_tick_size(price, expected_tick):
    """가격대별 호가단위 KRX 규정 확인."""
    assert KISManager.get_tick_size(price) == expected_tick
