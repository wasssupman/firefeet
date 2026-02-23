from core.config_loader import ConfigLoader
from core.kis_auth import KISAuth
from core.providers.kis_api import KISManager, OrderType
import sys
import time

def test_manager():
    print("=== Testing KIS Manager Features ===")
    
    # 1. Setup
    loader = ConfigLoader()
    mode = "REAL" # Changed to REAL for verification
    config = loader.get_kis_config(mode=mode)
    account_info = loader.get_account_info()
    
    print(f"Loaded Config Mode: {mode}")
    print(f"APP_KEY: {config['APP_KEY'][:5]}...")
    
    auth = KISAuth(config)
    
    # Authenticate explicitly first
    try:
        token = auth.get_access_token()
        print(f"Token acquired: {token[:10]}...")
    except Exception as e:
        print(f"Failed to acquire token explicitly: {e}")
        return # Stop if auth fails

    manager = KISManager(auth, account_info, mode=mode)
    
    # 2. Test Current Price (Samsung Electronics: 005930)
    try:
        print("\n[Test 1] Fetching Current Price for Samsung Electronics (005930)...")
        price_info = manager.get_current_price("005930")
        print(f"Current Price: {price_info['price']} KRW")
        print(f"Volume: {price_info['volume']}")
    except Exception as e:
        print(f"Failed to fetch price: {e}")

    # 3. Test Balance
    try:
        print("\n[Test 2] Fetching Account Balance...")
        balance = manager.get_balance()
        print(f"Total Asset: {balance['total_asset']} KRW")
        print(f"Holdings: {len(balance['holdings'])} stocks")
        for stock in balance['holdings']:
            print(f" - {stock['name']}: {stock['qty']} shares ({stock['profit_rate']}%)")
    except Exception as e:
        print(f"Failed to fetch balance: {e}")

if __name__ == "__main__":
    test_manager()
