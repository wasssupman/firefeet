"""Tests for core.config_loader.ConfigLoader."""

import os
import pytest
import yaml
from unittest.mock import patch

from core.config_loader import ConfigLoader, _PROJECT_ROOT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_secrets(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)


# ---------------------------------------------------------------------------
# 1. 절대 경로 해석 (H14 회귀)
# ---------------------------------------------------------------------------

def test_absolute_path_used_exactly(mock_config):
    """ConfigLoader(absolute_path) stores that exact path, not a derived one."""
    loader = ConfigLoader(mock_config)
    assert loader.config_path == mock_config


# ---------------------------------------------------------------------------
# 2. 상대 경로 기본값
# ---------------------------------------------------------------------------

def test_default_path_is_project_root_config(tmp_path):
    """ConfigLoader() without args defaults to PROJECT_ROOT/config/secrets.yaml."""
    loader = ConfigLoader()
    expected = os.path.join(_PROJECT_ROOT, "config", "secrets.yaml")
    assert loader.config_path == expected


# ---------------------------------------------------------------------------
# 3. 캐시 동작 (H10 회귀)
# ---------------------------------------------------------------------------

def test_load_config_cached(mock_config):
    """load_config() called twice returns the same dict (file opened only once)."""
    loader = ConfigLoader(mock_config)
    with patch("builtins.open", wraps=open) as mock_open:
        first = loader.load_config()
        second = loader.load_config()
    # Same object — no second read
    assert first is second
    # open() should have been called at most once (wraps real open for the first call)
    assert mock_open.call_count <= 1


# ---------------------------------------------------------------------------
# 4. 누락 섹션 → ValueError (H15 회귀)
# ---------------------------------------------------------------------------

def test_missing_prod_section_raises(tmp_path):
    """get_kis_config('REAL') raises ValueError when 'PROD' key is absent."""
    secrets_path = str(tmp_path / "config" / "secrets.yaml")
    _write_secrets(secrets_path, {"PAPER": {"APP_KEY": "k"}})
    loader = ConfigLoader(secrets_path)
    with pytest.raises(ValueError, match="PROD"):
        loader.get_kis_config("REAL")


# ---------------------------------------------------------------------------
# 5. REAL 모드: get_kis_config("REAL") → config["PROD"]
# ---------------------------------------------------------------------------

def test_get_kis_config_real_mode(mock_config):
    """get_kis_config('REAL') returns the PROD section."""
    loader = ConfigLoader(mock_config)
    result = loader.get_kis_config("REAL")
    assert result["APP_KEY"] == "test_prod_key"
    assert result["APP_SECRET"] == "test_prod_secret"


# ---------------------------------------------------------------------------
# 6. PAPER 모드: get_kis_config("PAPER") → config["PAPER"]
# ---------------------------------------------------------------------------

def test_get_kis_config_paper_mode(mock_config):
    """get_kis_config('PAPER') returns the PAPER section."""
    loader = ConfigLoader(mock_config)
    result = loader.get_kis_config("PAPER")
    assert result["APP_KEY"] == "test_paper_key"
    assert "openapivts" in result["URL_BASE"]


# ---------------------------------------------------------------------------
# 7. get_account_info(): PAPER_CANO vs CANO 분기
# ---------------------------------------------------------------------------

def test_get_account_info_paper_uses_paper_cano(mock_config):
    """get_account_info('PAPER') uses PAPER_CANO when it is present."""
    loader = ConfigLoader(mock_config)
    info = loader.get_account_info("PAPER")
    assert info["CANO"] == "50000000"
    assert info["ACNT_PRDT_CD"] == "01"


def test_get_account_info_real_uses_cano(mock_config):
    """get_account_info('REAL') falls back to the top-level CANO."""
    loader = ConfigLoader(mock_config)
    info = loader.get_account_info("REAL")
    assert info["CANO"] == "12345678"


def test_get_account_info_paper_without_paper_cano_falls_back(tmp_path):
    """get_account_info('PAPER') falls back to CANO when PAPER_CANO is absent."""
    secrets_path = str(tmp_path / "config" / "secrets.yaml")
    _write_secrets(secrets_path, {
        "PROD": {"APP_KEY": "k"},
        "PAPER": {"APP_KEY": "k2"},
        "CANO": "99999999",
        "ACNT_PRDT_CD": "01",
    })
    loader = ConfigLoader(secrets_path)
    info = loader.get_account_info("PAPER")
    assert info["CANO"] == "99999999"


# ---------------------------------------------------------------------------
# 8. FileNotFoundError: 존재하지 않는 경로
# ---------------------------------------------------------------------------

def test_file_not_found_raises(tmp_path):
    """load_config() raises FileNotFoundError for a non-existent path."""
    loader = ConfigLoader(str(tmp_path / "nonexistent" / "secrets.yaml"))
    with pytest.raises(FileNotFoundError):
        loader.load_config()
