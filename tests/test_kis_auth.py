"""Tests for KISAuth — token caching, header generation, and approval key."""

import json
import time
import pytest
from unittest.mock import patch, MagicMock

from core.kis_auth import KISAuth


# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def auth_config():
    return {
        "APP_KEY": "test_app_key",
        "APP_SECRET": "test_app_secret",
        "URL_BASE": "https://mock.kis.com",
    }


@pytest.fixture
def auth(auth_config, tmp_path, monkeypatch):
    """KISAuth instance with cache path redirected to tmp_path."""
    instance = KISAuth(auth_config)
    cache_file = str(tmp_path / ".token_cache.json")
    monkeypatch.setattr(instance, "_cache_path", cache_file)
    return instance


# ── Helpers ─────────────────────────────────────────────────

def _write_cache(path, token="cached_token", expires_in=86400, expired_at="2099-12-31 23:59:59"):
    """Write a valid token cache file."""
    expiry_epoch = int(time.time()) + expires_in
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "token": token,
            "token_expired_at": expired_at,
            "expiry": expiry_epoch,
        }, f)


def _write_expired_cache(path):
    """Write a token cache that is already expired."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "token": "old_token",
            "token_expired_at": "2020-01-01 00:00:00",
            "expiry": int(time.time()) - 3600,  # 1 hour in the past
        }, f)


def _make_token_response(token="new_token", expires_in=86400):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "access_token": token,
        "access_token_token_expired": "2099-12-31 23:59:59",
        "expires_in": expires_in,
    }
    mock_resp.raise_for_status.return_value = None
    return mock_resp


# ── Token Cache Tests ────────────────────────────────────────

def test_cache_hit_returns_token_without_api_call(auth):
    """유효한 캐시가 있으면 requests.post 호출 없이 토큰 반환."""
    _write_cache(auth._cache_path, token="cached_token")

    with patch("requests.post") as mock_post:
        token = auth.get_access_token()

    assert token == "cached_token"
    mock_post.assert_not_called()


def test_cache_hit_sets_token_on_instance(auth):
    """캐시 히트 시 self.token과 self.token_expired가 설정된다."""
    _write_cache(auth._cache_path, token="cached_token", expired_at="2099-01-01 00:00:00")

    auth.get_access_token()

    assert auth.token == "cached_token"
    assert auth.token_expired == "2099-01-01 00:00:00"


def test_expired_cache_triggers_new_token_request(auth):
    """만료된 캐시 → requests.post로 신규 토큰 발급."""
    _write_expired_cache(auth._cache_path)

    with patch("requests.post", return_value=_make_token_response("new_token")) as mock_post:
        token = auth.get_access_token()

    assert token == "new_token"
    mock_post.assert_called_once()
    # URL이 oauth2/tokenP 포함
    called_url = mock_post.call_args[0][0]
    assert "oauth2/tokenP" in called_url


def test_no_cache_file_triggers_new_token_request(auth):
    """캐시 파일 없음 → 신규 토큰 발급."""
    import os
    if os.path.exists(auth._cache_path):
        os.remove(auth._cache_path)

    with patch("requests.post", return_value=_make_token_response("brand_new")) as mock_post:
        token = auth.get_access_token()

    assert token == "brand_new"
    mock_post.assert_called_once()


# ── get_headers() Security Tests ─────────────────────────────

def test_get_headers_contains_appsecret(auth):
    """KIS API는 get_headers()에 appsecret이 필수."""
    auth.token = "some_token"

    headers = auth.get_headers()

    assert "appsecret" in headers, "appsecret is required by KIS API"


def test_get_headers_contains_appkey(auth):
    """get_headers()에 appkey가 포함되어야 한다."""
    auth.token = "some_token"

    headers = auth.get_headers()

    assert "appkey" in headers
    assert headers["appkey"] == "test_app_key"


def test_get_headers_with_tr_id(auth):
    """tr_id 전달 시 헤더에 포함된다."""
    auth.token = "some_token"

    headers = auth.get_headers(tr_id="TEST123")

    assert headers.get("tr_id") == "TEST123"


def test_get_headers_without_tr_id_omits_key(auth):
    """tr_id 미전달 시 헤더에 tr_id 키가 없어야 한다."""
    auth.token = "some_token"

    headers = auth.get_headers()

    assert "tr_id" not in headers


# ── invalidate_token() ───────────────────────────────────────

def test_invalidate_token_clears_token_and_cache(auth, tmp_path):
    """invalidate_token() → self.token=None + 캐시 파일 삭제."""
    import os
    _write_cache(auth._cache_path, token="to_invalidate")
    auth.token = "to_invalidate"

    auth.invalidate_token()

    assert auth.token is None
    assert not os.path.exists(auth._cache_path)


def test_invalidate_token_no_cache_file_does_not_raise(auth):
    """캐시 파일이 없어도 invalidate_token()이 예외 없이 실행된다."""
    import os
    if os.path.exists(auth._cache_path):
        os.remove(auth._cache_path)
    auth.token = "some_token"

    auth.invalidate_token()  # Must not raise

    assert auth.token is None


# ── get_approval_key() ───────────────────────────────────────

def test_get_approval_key_returns_key_on_success(auth):
    """정상 응답 시 approval_key 반환."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"approval_key": "ws_approval_key_abc"}
    mock_resp.raise_for_status.return_value = None

    with patch("requests.post", return_value=mock_resp):
        key = auth.get_approval_key()

    assert key == "ws_approval_key_abc"


def test_get_approval_key_returns_none_on_failure(auth):
    """requests.post가 예외를 던지면 None 반환."""
    with patch("requests.post", side_effect=Exception("connection refused")):
        key = auth.get_approval_key()

    assert key is None


def test_get_approval_key_returns_none_when_key_missing(auth):
    """응답에 approval_key 키가 없으면 None 반환."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"error": "unauthorized"}
    mock_resp.raise_for_status.return_value = None

    with patch("requests.post", return_value=mock_resp):
        key = auth.get_approval_key()

    assert key is None
