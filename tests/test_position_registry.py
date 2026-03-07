"""tests/test_position_registry.py — PositionRegistry + positions table tests.

15 tests:
  1.  positions table created by schema
  2.  register shows in get_all_positions
  3.  remove clears the row
  4.  remove_all by bot_type
  5.  is_held_by_other same bot returns False
  6.  is_held_by_other different bot returns True
  7.  is_held_by_other no position returns False
  8.  stale PID cleanup on is_held_by_other
  9.  UNIQUE constraint (upsert replaces)
  10. read performance < 1ms
  11. cleanup_stale removes dead PIDs
  12. writer dispatches position_upsert
  13. writer dispatches position_delete
  14. writer dispatches position_delete_all
  15. positions table indexes exist
"""

import os
import sqlite3
import time

import pytest

from core.db.schema import init_schema
from core.db.writer import BackgroundWriter
from core.db.position_registry import PositionRegistry


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_positions.db")


@pytest.fixture
def registry(db_path):
    """PositionRegistry with a test DB."""
    reg = PositionRegistry(db_path=db_path)
    yield reg
    reg._writer.flush()


@pytest.fixture
def conn(db_path, registry):
    """Direct SQLite connection for verification."""
    def _connect():
        c = sqlite3.connect(db_path, timeout=2.0)
        c.row_factory = sqlite3.Row
        return c
    return _connect


def _insert_position(db_path, code, bot_type, pid, qty=10, avg_price=50000):
    """Directly insert a position row for test setup."""
    c = sqlite3.connect(db_path)
    c.execute(
        """INSERT OR REPLACE INTO positions
           (code, bot_type, pid, qty, avg_price, entered_at, updated_at)
           VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
        (code, bot_type, pid, qty, avg_price),
    )
    c.commit()
    c.close()


# ══════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════


class TestPositionsTableCreated:
    """1. positions table created by init_schema."""

    def test_positions_table_exists(self, db_path, registry):
        c = sqlite3.connect(db_path)
        tables = [row[0] for row in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "positions" in tables
        c.close()


class TestRegisterPosition:
    """2. register shows in get_all_positions."""

    def test_register_position(self, registry, conn):
        registry.register("005930", "scalp", 10, 50000)
        registry._writer.flush()

        c = conn()
        row = c.execute(
            "SELECT * FROM positions WHERE code = ? AND bot_type = ?",
            ("005930", "scalp"),
        ).fetchone()
        assert row is not None
        assert row["qty"] == 10
        assert row["avg_price"] == 50000
        assert row["pid"] == os.getpid()
        c.close()


class TestRemovePosition:
    """3. remove clears the row."""

    def test_remove_position(self, registry, conn, db_path):
        _insert_position(db_path, "005930", "scalp", os.getpid())

        registry.remove("005930", "scalp")
        registry._writer.flush()

        c = conn()
        row = c.execute(
            "SELECT * FROM positions WHERE code = '005930' AND bot_type = 'scalp'"
        ).fetchone()
        assert row is None
        c.close()


class TestRemoveAll:
    """4. remove_all by bot_type."""

    def test_remove_all(self, registry, conn, db_path):
        _insert_position(db_path, "005930", "scalp", os.getpid())
        _insert_position(db_path, "000660", "scalp", os.getpid())
        _insert_position(db_path, "035720", "swing", os.getpid())

        registry.remove_all("scalp")
        registry._writer.flush()

        c = conn()
        scalp_count = c.execute(
            "SELECT COUNT(*) FROM positions WHERE bot_type = 'scalp'"
        ).fetchone()[0]
        swing_count = c.execute(
            "SELECT COUNT(*) FROM positions WHERE bot_type = 'swing'"
        ).fetchone()[0]
        assert scalp_count == 0, "scalp positions should be removed"
        assert swing_count == 1, "swing positions should remain"
        c.close()


class TestIsHeldByOtherSameBot:
    """5. same bot_type returns False."""

    def test_same_bot_returns_false(self, registry, db_path):
        _insert_position(db_path, "005930", "scalp", os.getpid())
        assert registry.is_held_by_other("005930", "scalp") is False


class TestIsHeldByOtherDifferentBot:
    """6. different bot_type returns True."""

    def test_different_bot_returns_true(self, registry, db_path):
        _insert_position(db_path, "005930", "swing", os.getpid())
        assert registry.is_held_by_other("005930", "scalp") is True


class TestIsHeldByOtherNoPosition:
    """7. no position returns False."""

    def test_no_position_returns_false(self, registry):
        assert registry.is_held_by_other("005930", "scalp") is False


class TestStalePIDCleanupOnRead:
    """8. dead PID detected and cleaned up on is_held_by_other."""

    def test_stale_pid_cleaned_on_read(self, registry, db_path):
        # Use a PID that definitely doesn't exist
        dead_pid = 99999999
        _insert_position(db_path, "005930", "swing", dead_pid)

        # is_held_by_other should detect dead PID, clean up, return False
        result = registry.is_held_by_other("005930", "scalp")
        assert result is False

        # Verify row was deleted
        c = sqlite3.connect(db_path)
        row = c.execute(
            "SELECT * FROM positions WHERE code = '005930' AND bot_type = 'swing'"
        ).fetchone()
        assert row is None
        c.close()


class TestUniqueConstraintUpsert:
    """9. UNIQUE(code, bot_type) — upsert replaces qty/price."""

    def test_upsert_replaces(self, registry, conn, db_path):
        _insert_position(db_path, "005930", "scalp", os.getpid(), qty=10, avg_price=50000)

        # Register again with different qty/price
        registry.register("005930", "scalp", 20, 51000)
        registry._writer.flush()

        c = conn()
        rows = c.execute(
            "SELECT * FROM positions WHERE code = '005930' AND bot_type = 'scalp'"
        ).fetchall()
        assert len(rows) == 1, "UNIQUE constraint should prevent duplicates"
        assert rows[0]["qty"] == 20
        assert rows[0]["avg_price"] == 51000
        c.close()


class TestReadPerformance:
    """10. is_held_by_other < 1ms average."""

    def test_read_performance(self, registry, db_path):
        # Insert a few positions to make it realistic
        for i in range(5):
            _insert_position(db_path, f"00{i:04d}", "swing", os.getpid())

        start = time.perf_counter()
        n = 100
        for _ in range(n):
            registry.is_held_by_other("005930", "scalp")
        elapsed_ms = (time.perf_counter() - start) / n * 1000

        assert elapsed_ms < 1.0, f"avg {elapsed_ms:.3f}ms — should be < 1ms"


class TestCleanupStale:
    """11. cleanup_stale removes dead PIDs on startup."""

    def test_cleanup_stale(self, registry, db_path):
        dead_pid = 99999998
        _insert_position(db_path, "005930", "scalp", dead_pid)
        _insert_position(db_path, "000660", "swing", os.getpid())  # alive

        registry.cleanup_stale()

        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM positions").fetchall()
        assert len(rows) == 1
        assert rows[0]["code"] == "000660"
        c.close()


class TestWriterDispatchUpsert:
    """12. BackgroundWriter dispatches position_upsert."""

    def test_writer_upsert(self, registry, conn):
        registry.register("005930", "scalp", 15, 52000)
        registry._writer.flush()

        c = conn()
        row = c.execute(
            "SELECT * FROM positions WHERE code = '005930'"
        ).fetchone()
        assert row is not None
        assert row["qty"] == 15
        c.close()


class TestWriterDispatchDelete:
    """13. BackgroundWriter dispatches position_delete."""

    def test_writer_delete(self, registry, conn, db_path):
        _insert_position(db_path, "005930", "scalp", os.getpid())

        registry.remove("005930", "scalp")
        registry._writer.flush()

        c = conn()
        row = c.execute(
            "SELECT * FROM positions WHERE code = '005930'"
        ).fetchone()
        assert row is None
        c.close()


class TestWriterDispatchDeleteAll:
    """14. BackgroundWriter dispatches position_delete_all."""

    def test_writer_delete_all(self, registry, conn, db_path):
        _insert_position(db_path, "005930", "scalp", os.getpid())
        _insert_position(db_path, "000660", "scalp", os.getpid())

        registry.remove_all("scalp")
        registry._writer.flush()

        c = conn()
        count = c.execute(
            "SELECT COUNT(*) FROM positions WHERE bot_type = 'scalp'"
        ).fetchone()[0]
        assert count == 0
        c.close()


class TestPositionIndexesExist:
    """15. positions table indexes exist."""

    def test_position_indexes(self, db_path, registry):
        c = sqlite3.connect(db_path)
        indexes = c.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='positions'"
        ).fetchall()
        index_names = [row[0] for row in indexes]
        assert "idx_positions_code" in index_names
        assert "idx_positions_bot" in index_names
        c.close()
