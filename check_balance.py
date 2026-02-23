from core.kis_auth import KISAuth
from core.providers.kis_api import KISManager
from core.config_loader import ConfigLoader
loader = ConfigLoader()
config = loader.get_kis_config(mode="PAPER")
account = loader.get_account_info(mode="PAPER")
auth = KISAuth(config)
manager = KISManager(auth, account, mode="PAPER")
print(manager.get_balance())
