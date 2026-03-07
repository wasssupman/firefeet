import requests
import json
import time
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class KISAuth:
    def __init__(self, config):
        self.app_key = config["APP_KEY"]
        self.app_secret = config["APP_SECRET"]
        self.url_base = config["URL_BASE"]
        self.token = None
        self.token_expired = None
        self._cache_path = os.path.join(_PROJECT_ROOT, ".token_cache.json")

    def get_access_token(self):
        """
        Issues an OAuth access token or reuse from cache.
        """
        cache_path = self._cache_path
        
        # 1. Try Cache
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                    
                # Check expiration (buffer of 60 seconds)
                if cache.get("expiry") and int(cache["expiry"]) > time.time() + 60:
                    self.token = cache["token"]
                    self.token_expired = cache["token_expired_at"]
                    # print(f"[KISAuth] Using cached token. Expires: {self.token_expired}")
                    return self.token
            except (json.JSONDecodeError, KeyError, ValueError):
                pass

        # 2. Issue New Token
        headers = {"content-type": "application/json"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        
        path = "oauth2/tokenP"
        url = f"{self.url_base}/{path}"
        
        try:
            res = requests.post(url, headers=headers, data=json.dumps(body))
            res.raise_for_status()
            data = res.json()
            
            self.token = data["access_token"]
            self.token_expired = data["access_token_token_expired"]
            
            # Save to Cache
            # KIS returns expires_in in seconds usually, but data['access_token_token_expired'] is readable string
            # Let's calculate epoch expiry based on expires_in (usually 86400)
            expires_in = int(data.get("expires_in", 86400))
            expiry_epoch = int(time.time()) + expires_in
            
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "token": self.token,
                    "token_expired_at": self.token_expired,
                    "expiry": expiry_epoch
                }, f)
            
            print(f"[KISAuth] New Access Token Issued. Expires: {self.token_expired}")
            return self.token
            
        except Exception as e:
            if hasattr(e, 'response') and e.response is not None:
                print(f"[KISAuth] Error: {e.response.status_code} - {e.response.text}")
            else:
                print(f"[KISAuth] Error issuing token: {e}")
            raise

    def invalidate_token(self):
        """토큰 캐시 무효화 — 다음 요청 시 신규 발급"""
        self.token = None
        cache_path = self._cache_path
        if os.path.exists(cache_path):
            os.remove(cache_path)
        print("[KISAuth] 토큰 캐시 무효화 — 재발급 예정")

    def get_hashkey(self, body):
        """POST 요청용 hashkey 생성 (KIS /uapi/hashkey 엔드포인트)"""
        url = f"{self.url_base}/uapi/hashkey"
        headers = {
            "content-type": "application/json",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        res = requests.post(url, headers=headers, data=json.dumps(body))
        res.raise_for_status()
        return res.json()["HASH"]

    def get_approval_key(self):
        """WebSocket 접속용 approval key 발급 (/oauth2/Approval)"""
        url = f"{self.url_base}/oauth2/Approval"
        headers = {"content-type": "application/json"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.app_secret,
        }
        try:
            res = requests.post(url, headers=headers, data=json.dumps(body))
            res.raise_for_status()
            data = res.json()
            approval_key = data.get("approval_key")
            if approval_key:
                print("[KISAuth] WebSocket Approval Key 발급 완료")
                return approval_key
            else:
                print(f"[KISAuth] Approval Key 없음: {data}")
                return None
        except Exception as e:
            print(f"[KISAuth] Approval Key 발급 실패: {e}")
            return None

    def get_headers(self, tr_id=None):
        """
        Returns standard headers for API requests.
        tr_id: Transaction ID (required for specific API calls)
        """
        if not self.token:
            self.get_access_token()
            
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "custtype": "P"  # P: Personal, B: Business
        }
        
        if tr_id:
            headers["tr_id"] = tr_id
            
        return headers
