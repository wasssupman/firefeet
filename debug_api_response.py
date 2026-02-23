import requests
import json
import yaml
from core.config_loader import ConfigLoader
from core.kis_auth import KISAuth

def test_raw_scan(tr_id, iscd):
    loader = ConfigLoader()
    config = loader.get_kis_config(mode="REAL")
    account_info = loader.get_account_info()
    auth = KISAuth(config)
    
    path = "uapi/domestic-stock/v1/quotations/volume-rank"
    url = f"{auth.url_base}/{path}"
    
    headers = auth.get_headers(tr_id=tr_id)
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_cond_scr_div_code": "20171",
        "fid_input_iscd": iscd,
        "fid_div_cls_code": "0",
        "fid_blng_cls_code": "0",
        "fid_trgt_cls_code": "0",
        "fid_trgt_excl_cls_code": "0",
        "fid_input_price_1": "",
        "fid_input_price_2": "",
        "fid_vol_cnt": "",
        "fid_input_iscd_2": "0000"
    }
    
    print(f"\n--- Requesting {tr_id} with ISCD {iscd} (POST) ---")
    try:
        # Some KIS APIs are picky about GET vs POST
        res = requests.post(url, headers=headers, data=json.dumps(params), timeout=10)
        print(f"Status: {res.status_code}")
        print(f"Raw: {res.text}")
        
    except Exception as e:
        print(f"Error: {e}")

def test_current_price(code="005930"):
    loader = ConfigLoader()
    config = loader.get_kis_config(mode="REAL")
    auth = KISAuth(config)
    
    path = "uapi/domestic-stock/v1/quotations/inquire-price"
    url = f"{auth.url_base}/{path}"
    
    headers = auth.get_headers(tr_id="FHKST01010100")
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": code
    }
    
    print(f"\n--- Requesting Current Price for {code} ---")
    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        print(f"Status: {res.status_code}")
        print(f"Raw: {res.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Test Current Price first to verify connectivity
    test_current_price()
    
    # Test Volume Rank (KOSPI)
    test_raw_scan("FHPST01710000", "0001")
