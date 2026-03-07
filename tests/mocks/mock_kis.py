"""Mock KIS API classes for testing without real API calls."""

import pandas as pd
from core.providers.kis_api import OrderType


class MockKISAuth:
    """Mock KISAuth that never makes real HTTP calls."""

    def __init__(self, config=None):
        config = config or {
            "APP_KEY": "test_app_key",
            "APP_SECRET": "test_app_secret",
            "URL_BASE": "https://mock.kis.com",
        }
        self.app_key = config["APP_KEY"]
        self.app_secret = config["APP_SECRET"]
        self.url_base = config["URL_BASE"]
        self.token = "mock_access_token"
        self.token_expired = "2099-12-31 23:59:59"
        self._get_token_called = 0
        self._invalidate_called = 0

    def get_access_token(self):
        self._get_token_called += 1
        return self.token

    def invalidate_token(self):
        self._invalidate_called += 1
        self.token = None

    def get_hashkey(self, body):
        return "mock_hashkey"

    def get_approval_key(self):
        return "mock_approval_key"

    def get_headers(self, tr_id=None):
        if not self.token:
            self.get_access_token()
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "custtype": "P",
        }
        if tr_id:
            headers["tr_id"] = tr_id
        return headers


class MockKISManager:
    """Mock KISManager with controllable responses."""

    def __init__(self, auth=None, account_info=None, mode="PAPER"):
        self.auth = auth or MockKISAuth()
        self.cano = (account_info or {}).get("CANO", "00000000")
        self.acnt_prdt_cd = (account_info or {}).get("ACNT_PRDT_CD", "01")
        self.mode = mode
        self.url_base = self.auth.url_base

        # Controllable responses
        self._balance = {
            "total_asset": 10000000,
            "deposit": 5000000,
            "available_cash": 5000000,
            "holdings": [],
        }
        self._current_prices = {}  # {code: price_dict}
        self._ohlc_data = {}  # {code: DataFrame}
        self._order_counter = 1000
        self._orders = []  # list of placed orders for verification
        self._order_fail = False  # Set True to simulate order failure

    def get_balance(self):
        return self._balance

    def set_balance(self, holdings=None, total_asset=10000000, deposit=5000000,
                    available_cash=None):
        """Test helper to set mock balance."""
        self._balance = {
            "total_asset": total_asset,
            "deposit": deposit,
            "available_cash": available_cash if available_cash is not None else deposit,
            "holdings": holdings or [],
        }

    def get_current_price(self, code):
        if code in self._current_prices:
            return self._current_prices[code]
        return {
            "code": code,
            "price": 50000,
            "change": 500,
            "change_rate": 1.0,
            "volume": 1000000,
            "high": 51000,
        }

    def set_current_price(self, code, price, **kwargs):
        """Test helper to set mock price."""
        self._current_prices[code] = {
            "code": code,
            "price": price,
            "change": kwargs.get("change", 0),
            "change_rate": kwargs.get("change_rate", 0.0),
            "volume": kwargs.get("volume", 1000000),
            "high": kwargs.get("high", price),
        }

    def get_daily_ohlc(self, code):
        if code in self._ohlc_data:
            return self._ohlc_data[code]
        return make_ohlc_dataframe()

    def set_ohlc(self, code, df):
        """Test helper to set mock OHLC data."""
        self._ohlc_data[code] = df

    def place_order(self, code, qty, price, order_type):
        if self._order_fail:
            return None
        self._order_counter += 1
        order_no = str(self._order_counter)
        self._orders.append({
            "order_no": order_no,
            "code": code,
            "qty": qty,
            "price": price,
            "order_type": order_type,
        })
        return order_no

    def cancel_order(self, order_no, code, qty):
        return order_no

    def get_order_status(self, order_date=None):
        return []

    def get_investor_trend(self, code):
        return pd.DataFrame([
            {"date": "20260226", "price": 50000, "individual": 1000,
             "foreigner": 500, "institution": 200},
        ])

    def get_top_volume_stocks(self, limit=10, min_price=1000):
        return [
            {"code": "005930", "name": "삼성전자", "price": 70000,
             "volume": 5000000, "change_rate": 1.5},
            {"code": "000660", "name": "SK하이닉스", "price": 150000,
             "volume": 3000000, "change_rate": 2.0},
        ][:limit]

    @staticmethod
    def get_tick_size(price):
        if price < 2000: return 1
        elif price < 5000: return 5
        elif price < 20000: return 10
        elif price < 50000: return 50
        elif price < 200000: return 100
        elif price < 500000: return 500
        else: return 1000

    def round_to_tick(self, price, direction="down"):
        tick = self.get_tick_size(price)
        if direction == "up":
            return ((price + tick - 1) // tick) * tick
        return (price // tick) * tick


def make_ohlc_dataframe(days=30, base_open=50000, base_high=52000,
                         base_low=48000, base_close=51000, base_volume=1000000):
    """Create a mock OHLC DataFrame for testing."""
    import datetime
    today = datetime.date.today()
    rows = []
    for i in range(days):
        dt = today - datetime.timedelta(days=i)
        rows.append({
            "date": dt.strftime("%Y%m%d"),
            "open": base_open + (i * 100),
            "high": base_high + (i * 100),
            "low": base_low + (i * 100),
            "close": base_close + (i * 100),
            "volume": base_volume + (i * 10000),
        })
    return pd.DataFrame(rows)
