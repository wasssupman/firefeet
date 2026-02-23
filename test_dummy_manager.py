from core.kis_auth import KISAuth
from core.providers.kis_api import KISManager
from core.config_loader import ConfigLoader

loader = ConfigLoader()
config = loader.get_kis_config(mode="PAPER")
account = loader.get_account_info(mode="PAPER")

auth = KISAuth(config)

class DummyManager(KISManager):
    def __init__(self, auth, account_info):
        super().__init__(auth, account_info, mode="PAPER")
        self._virtual_odno = 1000
        
    def place_order(self, code, qty, price, order_type):
        print(f"[DummyManager] Place Order: {code} {qty}주 @ {price} (Type: {order_type})")
        self._virtual_odno += 1
        return str(self._virtual_odno)
        
manager = DummyManager(auth, account)
print(manager.place_order("005930", 10, 80000, "BUY"))
