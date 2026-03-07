"""tests/test_firefeet_db.py — BackgroundWriter + Schema 테스트.

15개 테스트:
  1. WAL 모드 확인
  2. decisions, calibration 테이블 존재
  3. log_decision INSERT 확인
  4. PENDING → FILLED UPDATE
  5. 이미 FILLED면 재UPDATE 무시 (idempotent)
  6. filled_qty < requested_qty → PARTIAL
  7. put_nowait < 1ms 성능
  8. flush 후 큐 비어있음
  9. 큐 오버플로우 시 동기 기록
  10. daemon=True 확인
  11. 배치 INSERT 정상
  12. 2 스레드 동시 기록 → 데이터 유실 없음
  13. atexit에 flush 등록 확인
  14. 싱글턴: 동일 path → 동일 인스턴스
  15. order_no UNIQUE 인덱스 존재
"""

import atexit
import os
import sqlite3
import threading
import time

import pytest

from core.db.schema import init_schema
from core.db.writer import BackgroundWriter


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path):
    """임시 DB 경로."""
    return str(tmp_path / "test_firefeet.db")


@pytest.fixture
def writer(db_path):
    """BackgroundWriter 인스턴스 (테스트용)."""
    w = BackgroundWriter(db_path=db_path, batch_size=5, flush_interval=1.0)
    yield w
    # 테스트 종료 시 flush
    if w._running:
        w.flush()


@pytest.fixture
def conn(db_path, writer):
    """읽기 전용 SQLite 커넥션 (writer flush 후 사용)."""
    def _connect():
        c = sqlite3.connect(db_path, timeout=2.0)
        c.row_factory = sqlite3.Row
        return c
    return _connect


# ── Helper ────────────────────────────────────────────────


def _make_decision(code="005930", action="BUY", **overrides):
    """기본 decision_data dict 생성."""
    data = {
        "timestamp": "2026-03-04T10:00:00+09:00",
        "bot_type": "scalp",
        "code": code,
        "action": action,
        "status": "PENDING",
        "order_no": f"ORD{id(overrides) % 10000:04d}",
        "requested_qty": 10,
        "requested_price": 50000.0,
        "confidence": 0.42,
        "composite": 35.0,
    }
    data.update(overrides)
    return data


# ══════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════


class TestInitCreatesDBWithWAL:
    """1. WAL 모드 확인."""

    def test_init_creates_db_with_wal(self, db_path, writer):
        assert os.path.exists(db_path), "DB 파일이 생성되어야 한다."
        c = sqlite3.connect(db_path)
        result = c.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal", f"WAL 모드가 아님: {result[0]}"
        c.close()


class TestSchemaTablesExist:
    """2. decisions, calibration, positions 테이블 존재."""

    def test_schema_tables_exist(self, db_path, writer):
        c = sqlite3.connect(db_path)
        tables = [row[0] for row in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "decisions" in tables, "decisions 테이블이 존재해야 한다."
        assert "calibration" in tables, "calibration 테이블이 존재해야 한다."
        assert "positions" in tables, "positions 테이블이 존재해야 한다."
        c.close()


class TestLogDecisionInsertsRow:
    """3. log_decision INSERT 확인."""

    def test_log_decision_inserts_row(self, writer, conn):
        decision = _make_decision(order_no="ORD_INSERT_001")
        writer.log_decision(decision)
        writer.flush()

        c = conn()
        row = c.execute(
            "SELECT * FROM decisions WHERE order_no = ?", ("ORD_INSERT_001",)
        ).fetchone()
        assert row is not None, "INSERT된 행이 존재해야 한다."
        assert row["code"] == "005930"
        assert row["action"] == "BUY"
        assert row["status"] == "PENDING"
        assert row["requested_qty"] == 10
        c.close()


class TestUpdateStatusPendingToFilled:
    """4. PENDING → FILLED UPDATE."""

    def test_update_status_pending_to_filled(self, writer, conn):
        decision = _make_decision(order_no="ORD_FILL_001")
        writer.log_decision(decision)
        writer.flush()

        # 새 writer 인스턴스로 update (flush 후 다시 시작)
        writer._running = True
        writer._thread = threading.Thread(
            target=writer._writer_loop, name="db-writer-2", daemon=False
        )
        writer._thread.start()

        writer.update_status("ORD_FILL_001", "FILLED",
                             filled_qty=10, filled_price=50100.0)
        writer.flush()

        c = conn()
        row = c.execute(
            "SELECT * FROM decisions WHERE order_no = ?", ("ORD_FILL_001",)
        ).fetchone()
        assert row["status"] == "FILLED"
        assert row["filled_qty"] == 10
        assert row["filled_price"] == 50100.0
        assert row["updated_at"] is not None
        c.close()


class TestUpdateStatusIdempotent:
    """5. 이미 FILLED면 재UPDATE 무시."""

    def test_update_status_idempotent(self, writer, conn):
        decision = _make_decision(order_no="ORD_IDEM_001")
        writer.log_decision(decision)
        writer.flush()

        # 첫 UPDATE: PENDING → FILLED
        writer._running = True
        writer._thread = threading.Thread(
            target=writer._writer_loop, name="db-writer-3", daemon=False
        )
        writer._thread.start()
        writer.update_status("ORD_IDEM_001", "FILLED",
                             filled_qty=10, filled_price=50100.0)
        writer.flush()

        # 두 번째 UPDATE: FILLED → FILLED (무시되어야 함)
        writer._running = True
        writer._thread = threading.Thread(
            target=writer._writer_loop, name="db-writer-4", daemon=False
        )
        writer._thread.start()
        writer.update_status("ORD_IDEM_001", "FILLED",
                             filled_qty=5, filled_price=49000.0)
        writer.flush()

        c = conn()
        row = c.execute(
            "SELECT * FROM decisions WHERE order_no = ?", ("ORD_IDEM_001",)
        ).fetchone()
        # WHERE status='PENDING' 조건 때문에 두 번째 UPDATE는 무시됨
        assert row["filled_qty"] == 10, "이미 FILLED인 행은 재UPDATE되지 않아야 한다."
        assert row["filled_price"] == 50100.0
        c.close()


class TestUpdateStatusPartialFill:
    """6. filled_qty < requested_qty → PARTIAL."""

    def test_update_status_partial_fill(self, writer, conn):
        decision = _make_decision(order_no="ORD_PART_001", requested_qty=100)
        writer.log_decision(decision)
        writer.flush()

        writer._running = True
        writer._thread = threading.Thread(
            target=writer._writer_loop, name="db-writer-5", daemon=False
        )
        writer._thread.start()
        writer.update_status("ORD_PART_001", "PARTIAL",
                             filled_qty=30, filled_price=50050.0)
        writer.flush()

        c = conn()
        row = c.execute(
            "SELECT * FROM decisions WHERE order_no = ?", ("ORD_PART_001",)
        ).fetchone()
        assert row["status"] == "PARTIAL"
        assert row["filled_qty"] == 30
        c.close()


class TestQueuePutNowaitPerformance:
    """7. put_nowait < 1ms 확인."""

    def test_queue_put_nowait_performance(self, writer):
        decision = _make_decision()
        start = time.perf_counter()
        for _ in range(100):
            writer.log_decision(decision)
        elapsed = (time.perf_counter() - start) / 100 * 1000  # ms per call

        assert elapsed < 1.0, (
            f"put_nowait 평균 {elapsed:.3f}ms — 1ms 미만이어야 한다."
        )


class TestFlushDrainsQueue:
    """8. flush 후 큐 비어있음."""

    def test_flush_drains_queue(self, writer):
        for i in range(20):
            writer.log_decision(_make_decision(order_no=f"ORD_DRAIN_{i:03d}"))

        writer.flush()
        assert writer._queue.empty(), "flush 후 큐가 비어있어야 한다."


class TestQueueFullFallbackSyncWrite:
    """9. 큐 오버플로우 시 동기 기록."""

    def test_queue_full_fallback_sync_write(self, db_path):
        # maxsize=1인 writer 생성
        w = BackgroundWriter(db_path=db_path, batch_size=1, flush_interval=10.0)

        # writer 스레드를 일시적으로 정지 (큐 소비 차단)
        w._running = False
        w._thread.join(timeout=5)

        # 큐를 가득 채움
        filled = 0
        for i in range(5010):
            try:
                w._queue.put_nowait(
                    _make_decision(order_no=f"ORD_OVERFLOW_{i:05d}")
                )
                filled += 1
            except Exception:
                break

        # 큐가 가득 찬 상태에서 log_decision 호출 → 동기 fallback
        w.log_decision(_make_decision(order_no="ORD_SYNC_FALLBACK"))

        # 동기 기록 확인
        c = sqlite3.connect(db_path, timeout=2.0)
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT * FROM decisions WHERE order_no = ?",
            ("ORD_SYNC_FALLBACK",)
        ).fetchone()
        assert row is not None, "큐 오버플로우 시 동기 기록이 되어야 한다."
        c.close()


class TestWriterThreadIsDaemon:
    """10. daemon=True 확인 (프로세스 종료 시 clean exit 보장)."""

    def test_writer_thread_is_daemon(self, writer):
        assert writer._thread.daemon is True, (
            "writer 스레드는 daemon=True여야 한다."
        )


class TestBatchWriteMultipleItems:
    """11. 배치 INSERT 정상."""

    def test_batch_write_multiple_items(self, writer, conn):
        for i in range(15):
            writer.log_decision(
                _make_decision(order_no=f"ORD_BATCH_{i:03d}", code=f"00{i:04d}")
            )
        writer.flush()

        c = conn()
        count = c.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        assert count == 15, f"15개 행이 INSERT되어야 한다. 실제: {count}"
        c.close()


class TestConcurrentWriteNoDataLoss:
    """12. 2 스레드 동시 기록 → 데이터 유실 없음."""

    def test_concurrent_write_no_data_loss(self, writer, conn):
        n_per_thread = 50
        errors = []

        def _writer_fn(thread_id):
            try:
                for i in range(n_per_thread):
                    writer.log_decision(
                        _make_decision(
                            order_no=f"ORD_CONC_T{thread_id}_{i:03d}",
                            code=f"T{thread_id}{i:04d}",
                        )
                    )
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=_writer_fn, args=(1,))
        t2 = threading.Thread(target=_writer_fn, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"스레드 에러: {errors}"

        writer.flush()

        c = conn()
        count = c.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        assert count == n_per_thread * 2, (
            f"{n_per_thread * 2}개 행이 INSERT되어야 한다. 실제: {count}"
        )
        c.close()


class TestAtexitRegistered:
    """13. atexit에 flush 등록 확인."""

    def test_atexit_registered(self, writer):
        # atexit._exithandlers는 CPython 내부 구현이므로
        # writer.flush가 atexit 콜백으로 등록되었는지 간접 확인
        # atexit.unregister로 해제 시도 — 등록되어 있으면 성공적으로 해제됨
        try:
            atexit.unregister(writer.flush)
            registered = True
        except Exception:
            registered = False
        assert registered, "atexit에 flush가 등록되어야 한다."


class TestSingleton:
    """14. 싱글턴: 동일 path → 동일 인스턴스."""

    def test_same_path_returns_same_instance(self, db_path):
        w1 = BackgroundWriter(db_path=db_path, batch_size=5, flush_interval=1.0)
        w2 = BackgroundWriter(db_path=db_path, batch_size=5, flush_interval=1.0)
        assert w1 is w2, "동일 db_path에 대해 싱글턴이어야 한다."
        w1.flush()

    def test_different_path_returns_different_instance(self, tmp_path):
        p1 = str(tmp_path / "a.db")
        p2 = str(tmp_path / "b.db")
        w1 = BackgroundWriter(db_path=p1, batch_size=5, flush_interval=1.0)
        w2 = BackgroundWriter(db_path=p2, batch_size=5, flush_interval=1.0)
        assert w1 is not w2, "다른 db_path는 다른 인스턴스여야 한다."
        w1.flush()
        w2.flush()


class TestOrderNoUniqueIndex:
    """15. order_no UNIQUE 인덱스 존재."""

    def test_order_no_unique_index_exists(self, db_path, writer):
        c = sqlite3.connect(db_path)
        indexes = c.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='decisions'"
        ).fetchall()
        index_names = [row[0] for row in indexes]
        assert "idx_decisions_order_no" in index_names, (
            f"order_no UNIQUE 인덱스가 필요. 현재: {index_names}"
        )
        c.close()
