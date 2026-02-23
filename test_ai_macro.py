from core.analysis.market_temperature import MarketTemperature
import time

def test_ai_macro():
    print("Initializing MarketTemperature (which configures AIMacroModule)...")
    mt = MarketTemperature()
    
    print("\nCalculating Market Temperature...")
    start_time = time.time()
    result = mt.calculate()
    end_time = time.time()
    
    print("\n--- Market Temperature Result ---")
    print(f"Final Score: {result.get('temperature')} ({result.get('level')})")
    print(f"Time Taken: {end_time - start_time:.2f} seconds")
    
    if "ai_macro" in result.get("details", {}):
        print("\n--- AI Macro Sentinel Override Info ---")
        ai_info = result["details"]["ai_macro"]
        print(f"Multiplier Applied: {ai_info.get('multiplier')}")
        print(f"AI Reasoning: {ai_info.get('reasoning')}")
    else:
        print("\nAI Macro Sentinel was disabled or failed.")

if __name__ == "__main__":
    test_ai_macro()
