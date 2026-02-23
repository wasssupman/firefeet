from core.config_loader import ConfigLoader
from core.kis_auth import KISAuth
import sys

def test_authentication():
    print("=== Testing KIS API Authentication ===")
    
    # 1. Load Configuration
    try:
        loader = ConfigLoader()
        config = loader.get_kis_config(mode="PAPER") # Default to PAPER for safety
        print("Configuration loaded successfully.")
    except Exception as e:
        print(f"Error loading configuration: {e}")
        return

    # 2. Initialize Auth
    try:
        auth = KISAuth(config)
        token = auth.get_access_token()
        
        if token:
            print(f"Authentication Successful! Token: {token[:10]}...")
        else:
            print("Authentication Failed: No token received.")
            
    except Exception as e:
        print(f"Authentication Failed: {e}")

if __name__ == "__main__":
    test_authentication()
