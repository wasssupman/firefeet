from core.config_loader import ConfigLoader
from core.kis_auth import KISAuth
from core.analysis.supply import SupplyAnalyzer

def test_supply_analysis():
    print("=== Testing Supply/Demand Analyzer ===")
    
    # 1. Setup
    loader = ConfigLoader()
    mode = "REAL" # Investor data works best in Real mode (Paper often has no data)
    config = loader.get_kis_config(mode=mode)
    from core.providers.kis_api import KISManager
    
    print(f"Connecting in {mode} mode...")
    auth = KISAuth(config)
    
    account_info = loader.get_account_info(mode=mode)
    
    # Manager is required to fetch investor_trend because we moved the logic
    manager = KISManager(auth, account_info, mode=mode)
    analyzer = SupplyAnalyzer()
    
    # 2. Analyze Target Stocks
    targets = [
        {"code": "005930", "name": "Samsung Electronics"},
        {"code": "000660", "name": "SK Hynix"},
        {"code": "005380", "name": "Hyundai Motor"}
    ]
    
    for target in targets:
        print(f"\nEvaluating {target['name']} ({target['code']})...")
        investor_trend = manager.get_investor_trend(target['code'])
        result = analyzer.analyze_supply(investor_trend)
        
        if isinstance(result, str):
            print(f"Result: {result}")
            continue
            
        print(f"Sentiment: {result['sentiment']}")
        print(f"Foreigner (3D): {result['foreign_3d']:,} shares")
        print(f"Institution (3D): {result['institution_3d']:,} shares") 
        print("Recent 3 Days Details:")
        for day in result['recent_data']:
            print(f"  [{day['date']}] Foreign: {day['foreigner']:,}, Inst: {day['institution']:,}, Indiv: {day['individual']:,}")

if __name__ == "__main__":
    test_supply_analysis()
