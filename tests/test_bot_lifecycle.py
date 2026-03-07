"""Tests for core/bot_lifecycle.py — BotLifecycle class."""

import os
import signal
import pytest
from unittest.mock import patch, MagicMock

from core.bot_lifecycle import BotLifecycle


# ── Helpers ─────────────────────────────────────────────────

def _make_lifecycle(tmp_path, pid_name="test_bot", close_time="1530"):
    """Create a BotLifecycle whose pid_file lives in tmp_path."""
    lc = BotLifecycle(pid_name, close_time=close_time)
    lc.pid_file = str(tmp_path / f"{pid_name}.pid")
    return lc


# ── PID Lock Tests ───────────────────────────────────────────

def test_acquire_lock_creates_pid_file(tmp_path):
    """acquire_lock() should write the current PID to the pid file."""
    lc = _make_lifecycle(tmp_path)
    assert not os.path.exists(lc.pid_file)

    lc.acquire_lock()

    assert os.path.exists(lc.pid_file)
    with open(lc.pid_file) as f:
        assert int(f.read().strip()) == os.getpid()


def test_acquire_lock_fails_on_running_process(tmp_path):
    """acquire_lock() should sys.exit(1) when a live process holds the lock."""
    lc = _make_lifecycle(tmp_path)
    # Write our own PID — os.kill(pid, 0) will succeed for a live process
    with open(lc.pid_file, "w") as f:
        f.write(str(os.getpid()))

    with pytest.raises(SystemExit) as exc:
        lc.acquire_lock()

    assert exc.value.code == 1


def test_acquire_lock_removes_stale_pid(tmp_path):
    """acquire_lock() should succeed when the PID file points to a dead process."""
    lc = _make_lifecycle(tmp_path)
    # PID 99999999 is virtually guaranteed not to exist
    with open(lc.pid_file, "w") as f:
        f.write("99999999")

    # Should not raise — stale file is silently skipped
    lc.acquire_lock()

    assert os.path.exists(lc.pid_file)
    with open(lc.pid_file) as f:
        assert int(f.read().strip()) == os.getpid()


def test_release_lock_removes_pid_file(tmp_path):
    """release_lock() should remove the pid file."""
    lc = _make_lifecycle(tmp_path)
    lc.acquire_lock()
    assert os.path.exists(lc.pid_file)

    lc.release_lock()

    assert not os.path.exists(lc.pid_file)


def test_release_lock_is_idempotent(tmp_path):
    """release_lock() should not raise when called with no pid file present."""
    lc = _make_lifecycle(tmp_path)
    # No file was ever created — should not raise
    lc.release_lock()


# ── is_market_hours Tests ────────────────────────────────────

def test_is_market_hours_within_range(tmp_path):
    """'0930' is within 09:00–15:30 → True."""
    lc = _make_lifecycle(tmp_path)
    assert lc.is_market_hours("0930") is True


def test_is_market_hours_before_open(tmp_path):
    """'0859' is before 09:00 → False."""
    lc = _make_lifecycle(tmp_path)
    assert lc.is_market_hours("0859") is False


def test_is_market_hours_after_close(tmp_path):
    """'1531' is after default close_time 15:30 → False."""
    lc = _make_lifecycle(tmp_path, close_time="1530")
    assert lc.is_market_hours("1531") is False


def test_is_market_hours_custom_close(tmp_path):
    """With close_time='1520', '1521' should be False."""
    lc = _make_lifecycle(tmp_path, close_time="1520")
    assert lc.is_market_hours("1521") is False
    assert lc.is_market_hours("1520") is True


# ── Signal Handler Test ──────────────────────────────────────

def test_signal_handler_raises_system_exit(tmp_path):
    """setup_signal_handler() should make SIGTERM raise SystemExit(0)."""
    lc = _make_lifecycle(tmp_path)
    lc.setup_signal_handler()

    with pytest.raises(SystemExit) as exc:
        # Simulate SIGTERM delivery by calling the installed handler directly
        signal.raise_signal(signal.SIGTERM)

    assert exc.value.code == 0


# ── atexit Registration Test ─────────────────────────────────

def test_atexit_releases_lock(tmp_path):
    """acquire_lock() should register release_lock with atexit."""
    import atexit as _atexit

    lc = _make_lifecycle(tmp_path)

    with patch.object(_atexit, "register") as mock_register:
        lc.acquire_lock()
        mock_register.assert_called_once_with(lc.release_lock)
