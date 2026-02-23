from core.config_loader import ConfigLoader
from core.kis_auth import KISAuth
from core.providers.kis_api import KISManager
from core.analysis.technical import VolatilityBreakoutStrategy
import pandas as pd

import time

def test_strategy():
    print("=== Testing Volatility Breakout Strategy ===")
    
    # 1. Setup
    loader = ConfigLoader()
    mode = "REAL" 
    config = loader.get_kis_config(mode=mode)
    auth = KISAuth(config) # Assuming auth works from previous tests
    
    # Generate token first to avoid issues
    try:
        auth.get_access_token()
    except Exception as e:
        print(f"Auth failed: {e}")
        return

    manager = KISManager(auth, loader.get_account_info(), mode=mode)
    strategy = VolatilityBreakoutStrategy(k=0.5)
    
    # 2. Test Targets
    targets = [
        {"code": "005930", "name": "Samsung Electronics"},
        {"code": "000660", "name": "SK Hynix"},
        {"code": "005380", "name": "Hyundai Motor"}
    ]
    
    for target in targets:
        print(f"\nAnalyzing {target['name']} ({target['code']})...")
        
        # Fetch data first
        df = manager.get_daily_ohlc(target['code'])
        current_data = manager.get_current_price(target['code'])
        
        if df is None or current_data is None:
            print("  Failed to fetch data via API.")
            continue
            
        current_price = current_data['price']
        
        # Check Buy Signal (Pass data to strategy)
        result = strategy.check_buy_signal(target['code'], df, current_price)
        
        if result:
            print(f"  Current Price: {result['current_price']:,} KRW")
            print(f"  Target Price:  {result['target_price']:,} KRW (Range * K)")
            
            if result['signal'] == "BUY":
                print(f"  🚨 SIGNAL: BUY! (Price >= Target)")
            else:
                diff = result['target_price'] - result['current_price']
                print(f"  Status: WAITING (Need +{diff:,} KRW to breakthrough)")
        else:
            print("  Failed to calculate target (Not enough data?)")

if __name__ == "__main__":
    test_strategy()
