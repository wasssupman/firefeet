"""Tests for the web backend FastAPI endpoints."""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

# Ensure project root is importable
backend_dir = os.path.join(os.path.dirname(__file__), "..", "web", "backend")
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


@pytest.fixture
def client():
    """Create a FastAPI TestClient with BotManager mocked."""
    with patch("bot_manager.BotManager") as MockBM:
        mock_bm = MockBM.return_value
        mock_bm.get_status.return_value = "STOPPED"
        # Re-import to pick up the mock
        if "web.backend.main" in sys.modules:
            del sys.modules["web.backend.main"]
        if "main" in sys.modules:
            del sys.modules["main"]

        from main import app
        from fastapi.testclient import TestClient
        yield TestClient(app)


# ── 3-1. Portfolio endpoint ─────────────────────────────────

def test_portfolio_returns_real_and_paper(client):
    """Normal response returns both real and paper balances."""
    mock_real = MagicMock()
    mock_real.get_balance.return_value = {"total_asset": 10000000, "deposit": 5000000, "holdings": []}
    mock_paper = MagicMock()
    mock_paper.get_balance.return_value = {"total_asset": 5000000, "deposit": 3000000, "holdings": []}

    def fake_get_kis(mode):
        return mock_real if mode == "REAL" else mock_paper

    with patch("main._get_kis_manager", side_effect=fake_get_kis):
        resp = client.get("/api/portfolio")

    assert resp.status_code == 200
    data = resp.json()
    assert "real" in data
    assert "paper" in data
    assert data["real"]["total_asset"] == 10000000
    assert data["paper"]["total_asset"] == 5000000


def test_portfolio_kis_error_returns_500(client):
    """KIS API failure returns 500 with detail."""
    with patch("main._get_kis_manager", side_effect=Exception("connection refused")):
        resp = client.get("/api/portfolio")

    assert resp.status_code == 500
    assert "detail" in resp.json()


def test_portfolio_empty_holdings(client):
    """Empty holdings list is returned as empty array."""
    mock_mgr = MagicMock()
    mock_mgr.get_balance.return_value = {"total_asset": 1000000, "deposit": 1000000, "holdings": []}

    with patch("main._get_kis_manager", return_value=mock_mgr):
        resp = client.get("/api/portfolio")

    assert resp.status_code == 200
    data = resp.json()
    assert data["real"]["holdings"] == []
    assert data["paper"]["holdings"] == []


# ── 3-2. Bot control endpoints ──────────────────────────────

def test_get_bot_statuses(client):
    """All bot statuses are returned."""
    resp = client.get("/api/bots/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "scalping" in data
    assert "swing" in data
    assert "ai_swing" in data
    assert "batch_reports" in data


def test_start_bot_invalid_id(client):
    """Non-existent bot_id returns 404."""
    resp = client.post("/api/bots/nonexistent/start")
    assert resp.status_code == 404


def test_stop_bot_not_running(client):
    """Stopping a bot that isn't running returns 400."""
    from unittest.mock import AsyncMock
    with patch("main.manager") as mock_mgr:
        mock_mgr.stop_bot = AsyncMock(return_value=(False, "Bot is not running"))
        resp = client.post("/api/bots/scalping/stop")
    assert resp.status_code == 400


# ── 3-3. Market endpoints ───────────────────────────────────

def test_market_temperature_cached(client):
    """Cached temperature is returned when within TTL."""
    import time
    cached = {"score": 42, "level": "WARM", "details": {"macro": {"score": 50}}}
    with patch("main.MARKET_CACHE", {"temperature": {"data": cached, "timestamp": time.time()},
                                      "summary": {"data": None, "timestamp": 0},
                                      "prediction": {"data": None, "timestamp": 0}}):
        resp = client.get("/api/market/temperature")
    assert resp.status_code == 200
    assert resp.json()["score"] == 42


def test_market_summary_cached(client):
    """Cached summary is returned when within TTL."""
    import time
    cached = {"narrative": "Test narrative", "sentiment": "Bullish"}
    with patch("main.MARKET_CACHE", {"temperature": {"data": None, "timestamp": 0},
                                      "summary": {"data": cached, "timestamp": time.time()},
                                      "prediction": {"data": None, "timestamp": 0}}):
        resp = client.get("/api/market/summary")
    assert resp.status_code == 200
    assert resp.json()["sentiment"] == "Bullish"


# ── 3-4. Config endpoints ───────────────────────────────────

def test_get_ai_settings(client, tmp_path):
    """AI settings returns compact_prompt boolean."""
    import yaml
    config = {"orchestrator": {"compact_prompt": True}}
    cfg_path = tmp_path / "deep_analysis.yaml"
    with open(cfg_path, "w") as f:
        yaml.dump(config, f)

    with patch("main.project_root", str(tmp_path)), \
         patch("main.os.path.join", side_effect=lambda *args: str(tmp_path / "deep_analysis.yaml")
               if "deep_analysis" in str(args) else os.path.join(*args)):
        # Simpler: just patch the path
        pass

    # Direct approach: patch open
    import builtins
    original_open = builtins.open

    def mock_open_fn(path, *a, **kw):
        if "deep_analysis" in str(path):
            return original_open(str(cfg_path), *a, **kw)
        return original_open(path, *a, **kw)

    with patch("builtins.open", side_effect=mock_open_fn):
        resp = client.get("/api/config/ai-settings")

    assert resp.status_code == 200
    assert resp.json()["compact_prompt"] is True


def test_update_ai_settings(client, tmp_path):
    """POST updates compact_prompt value."""
    import yaml
    config = {"orchestrator": {"compact_prompt": False}}
    cfg_path = tmp_path / "deep_analysis.yaml"
    with open(cfg_path, "w") as f:
        yaml.dump(config, f)

    import builtins
    original_open = builtins.open

    def mock_open_fn(path, *a, **kw):
        if "deep_analysis" in str(path):
            return original_open(str(cfg_path), *a, **kw)
        return original_open(path, *a, **kw)

    with patch("builtins.open", side_effect=mock_open_fn):
        resp = client.post("/api/config/ai-settings", json={"compact_prompt": True})

    assert resp.status_code == 200
    assert resp.json()["compact_prompt"] is True


# ── 3-5. Reports/Logs endpoints ─────────────────────────────

def test_list_reports(client, tmp_path):
    """Reports endpoint returns file list."""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report1.md").write_text("# Report 1")
    (reports_dir / "report2.md").write_text("# Report 2")

    with patch("main.project_root", str(tmp_path)):
        resp = client.get("/api/reports")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    filenames = {r["filename"] for r in data}
    assert "report1.md" in filenames
    assert "report2.md" in filenames


def test_get_report_path_traversal(client):
    """Path traversal attempts return 400."""
    resp = client.get("/api/reports/..secret.yaml")
    assert resp.status_code == 400
    assert "Invalid" in resp.json()["detail"]


def test_get_logs_invalid_type(client):
    """Invalid log_type returns 400."""
    resp = client.get("/api/logs/invalid")
    assert resp.status_code == 400
    assert "Invalid log type" in resp.json()["detail"]


def test_get_logs_scalp(client, tmp_path):
    """Scalp logs CSV is parsed and returned as array."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    csv_path = logs_dir / "trades_scalp.csv"
    csv_path.write_text("date,code,pnl\n2026-03-01,005930,1000\n2026-03-02,000660,-500\n")

    with patch("main.project_root", str(tmp_path)):
        resp = client.get("/api/logs/scalp")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert str(data[0]["code"]) == "5930" or data[0]["code"] == "005930"


def test_get_logs_missing_file(client, tmp_path):
    """Missing log file returns empty array."""
    with patch("main.project_root", str(tmp_path)):
        resp = client.get("/api/logs/swing")

    assert resp.status_code == 200
    assert resp.json() == []


# ── 3-6. Calibration endpoint ───────────────────────────────

def test_calibration_no_db(client, tmp_path):
    """No DB file returns empty arrays."""
    with patch("main.project_root", str(tmp_path)):
        resp = client.get("/api/calibration/latest")

    assert resp.status_code == 200
    data = resp.json()
    assert data["confidence_curve"] == []
    assert data["signal_weights"] == []


def test_calibration_latest(client, tmp_path):
    """Calibration with data returns structured response."""
    import sqlite3
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    db_path = logs_dir / "firefeet.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE calibration (
            date TEXT, metric_type TEXT, metric_key TEXT,
            metric_value REAL, sample_count INTEGER
        )
    """)
    conn.execute("INSERT INTO calibration VALUES ('2026-03-01', 'confidence', '0.3~0.4', 0.45, 20)")
    conn.execute("INSERT INTO calibration VALUES ('2026-03-01', 'weight', 'vwap', 0.25, 100)")
    conn.commit()
    conn.close()

    with patch("main.project_root", str(tmp_path)):
        resp = client.get("/api/calibration/latest")

    assert resp.status_code == 200
    data = resp.json()
    assert data["date"] == "2026-03-01"
    assert len(data["confidence_curve"]) == 1
    assert data["confidence_curve"][0]["bin"] == "0.3~0.4"
    assert len(data["signal_weights"]) == 1
    assert data["signal_weights"][0]["signal"] == "vwap"
