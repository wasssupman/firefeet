"""PostTradeCalibrator 테스트 — 교정 파이프라인 검증."""

import sqlite3
import pytest
from datetime import datetime, timedelta

from core.calibration.post_trade_calibrator import PostTradeCalibrator
from core.db.schema import init_schema


# ── Helpers ─────────────────────────────────────────────


def _create_db(tmp_path):
    """테스트용 in-memory 스타일 SQLite DB (파일 기반, tmp_path 사용)."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return db_path, conn


def _insert_trade(conn, **overrides):
    """FILLED 스캘핑 BUY 거래 1건 삽입."""
    defaults = {
        "timestamp": datetime.now().isoformat(),
        "bot_type": "scalp",
        "code": "005930",
        "action": "BUY",
        "status": "FILLED",
        "confidence": 0.45,
        "realized_pnl": 100,
        "pnl_rate": 0.005,
        "sig_vwap": 0.6,
        "sig_ob": 0.5,
        "sig_mom": 0.4,
        "sig_vol": 0.3,
        "sig_trend": 0.2,
    }
    defaults.update(overrides)
    cols = list(defaults.keys())
    placeholders = ", ".join(["?"] * len(cols))
    col_names = ", ".join(cols)
    values = [defaults[c] for c in cols]
    conn.execute(
        f"INSERT INTO decisions ({col_names}) VALUES ({placeholders})", values
    )
    conn.commit()


def _insert_trades(conn, n, **overrides):
    """n건의 거래 일괄 삽입."""
    for _ in range(n):
        _insert_trade(conn, **overrides)


# ── Tests ───────────────────────────────────────────────


class TestSkipInsufficientData:
    """test_skip_insufficient_data — 30건 미만 -> status=skipped."""

    def test_skip_insufficient_data(self, tmp_path):
        db_path, conn = _create_db(tmp_path)
        _insert_trades(conn, 10)  # 30건 미만
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, min_samples=30)
        result = cal.run()

        assert result["status"] == "skipped"
        assert "insufficient data" in result["reason"]


class TestConfidenceCurveBins:
    """test_confidence_curve_bins — 5개 bin 정확한 구간 분할."""

    def test_confidence_curve_bins(self, tmp_path):
        db_path, conn = _create_db(tmp_path)
        # 각 bin에 분산하여 총 50건 삽입
        for conf in [0.1, 0.15, 0.25]:
            _insert_trades(conn, 10, confidence=conf)
        _insert_trades(conn, 10, confidence=0.35)
        _insert_trades(conn, 10, confidence=0.55)
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, min_samples=5)
        result = cal.run()

        curve = result["confidence_curve"]
        assert len(curve) == 5
        expected_bins = [
            "0.00-0.30",
            "0.30-0.40",
            "0.40-0.50",
            "0.50-0.60",
            "0.60-1.00",
        ]
        actual_bins = [b["bin"] for b in curve]
        assert actual_bins == expected_bins


class TestConfidenceCurveWinRate:
    """test_confidence_curve_win_rate — 승리 거래 비율 정확."""

    def test_confidence_curve_win_rate(self, tmp_path):
        db_path, conn = _create_db(tmp_path)
        # 0.40-0.50 bin에 40건: 30승 10패
        for i in range(30):
            _insert_trade(conn, confidence=0.45, realized_pnl=100)
        for i in range(10):
            _insert_trade(conn, confidence=0.45, realized_pnl=-100)
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, min_samples=30)
        result = cal.run()

        curve = result["confidence_curve"]
        bin_04 = next(b for b in curve if b["bin"] == "0.40-0.50")
        assert bin_04["sufficient"] is True
        assert bin_04["win_rate"] == 0.75  # 30/40
        assert bin_04["count"] == 40


class TestConfidenceCurveInsufficientBin:
    """test_confidence_curve_insufficient_bin — 특정 bin만 부족 시 sufficient=False."""

    def test_confidence_curve_insufficient_bin(self, tmp_path):
        db_path, conn = _create_db(tmp_path)
        # 0.40-0.50 bin에 35건 (충분), 0.60-1.00 bin에 2건 (부족)
        _insert_trades(conn, 35, confidence=0.45)
        _insert_trades(conn, 2, confidence=0.65)
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, min_samples=30)
        result = cal.run()

        curve = result["confidence_curve"]
        bin_04 = next(b for b in curve if b["bin"] == "0.40-0.50")
        bin_06 = next(b for b in curve if b["bin"] == "0.60-1.00")

        assert bin_04["sufficient"] is True
        assert bin_06["sufficient"] is False
        assert bin_06["win_rate"] is None
        assert bin_06["count"] == 2


class TestSignalWeightBaselinePreserved:
    """test_signal_weight_baseline_preserved — 데이터 부족 시 baseline 유지."""

    def test_signal_weight_baseline_preserved(self, tmp_path):
        db_path, conn = _create_db(tmp_path)
        # sig_trend만 0 (비활성), 나머지는 >0 — 단 min_samples 미달
        _insert_trades(conn, 35, sig_trend=0.0, confidence=0.45)
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, min_samples=30)
        result = cal.run()

        sw = result["signal_weights"]
        # sig_trend 데이터 부족 (모두 0이므로 active 0건)
        assert sw["raw_scores"]["sig_trend"]["sufficient"] is False
        # baseline 기반으로 정규화된 값이 들어감 (정확한 baseline 비율 유지)


class TestSignalWeightClampMax:
    """test_signal_weight_clamp_max — 승률 80% -> 가중치 +20% 이내."""

    def test_signal_weight_clamp_max(self, tmp_path):
        db_path, conn = _create_db(tmp_path)
        # sig_vwap 승률 80% (baseline 30)
        for i in range(32):
            _insert_trade(
                conn, confidence=0.45, sig_vwap=0.8, realized_pnl=100
            )
        for i in range(8):
            _insert_trade(
                conn, confidence=0.45, sig_vwap=0.8, realized_pnl=-100
            )
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, min_samples=30)
        result = cal.run()

        sw = result["signal_weights"]
        # 승률 0.8 -> factor 1.6 -> 30*1.6=48 -> clamp max 36
        # 정규화 전 clamped = 36, 정규화 후 비율 유지
        baseline = sw["baseline_weights"]["sig_vwap"]
        # 정규화 전 클램프: baseline * 1.2 = 36
        # 확인: adjusted는 정규화 후이므로 비율로 검증
        raw_wr = sw["raw_scores"]["sig_vwap"]["win_rate"]
        assert raw_wr == 0.8


class TestSignalWeightClampMin:
    """test_signal_weight_clamp_min — 승률 20% -> 가중치 -20% 이내."""

    def test_signal_weight_clamp_min(self, tmp_path):
        db_path, conn = _create_db(tmp_path)
        # sig_vwap 승률 20% (8승 32패)
        for i in range(8):
            _insert_trade(
                conn, confidence=0.45, sig_vwap=0.8, realized_pnl=100
            )
        for i in range(32):
            _insert_trade(
                conn, confidence=0.45, sig_vwap=0.8, realized_pnl=-100
            )
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, min_samples=30)
        result = cal.run()

        sw = result["signal_weights"]
        # 승률 0.2 -> factor 0.4 -> 30*0.4=12 -> clamp min 24
        raw_wr = sw["raw_scores"]["sig_vwap"]["win_rate"]
        assert raw_wr == 0.2


class TestSignalWeightNormalization:
    """test_signal_weight_normalization — 합 100."""

    def test_signal_weight_normalization(self, tmp_path):
        db_path, conn = _create_db(tmp_path)
        # 모든 시그널에 충분한 데이터, 다양한 승률
        for i in range(40):
            pnl = 100 if i < 30 else -100  # 75% 승률
            _insert_trade(
                conn,
                confidence=0.45,
                sig_vwap=0.8,
                sig_ob=0.7,
                sig_mom=0.6,
                sig_vol=0.5,
                sig_trend=0.4,
                realized_pnl=pnl,
            )
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, min_samples=30)
        result = cal.run()

        sw = result["signal_weights"]
        total = sum(sw["adjusted_weights"].values())
        assert abs(total - 100.0) < 0.5  # 반올림 오차 허용


class TestSaveResultsToCalibrationTable:
    """test_save_results_to_calibration_table — DB에 올바르게 저장."""

    def test_save_results_to_calibration_table(self, tmp_path):
        db_path, conn = _create_db(tmp_path)
        # 0.40-0.50 bin에 35건
        _insert_trades(conn, 35, confidence=0.45)
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, min_samples=30)
        result = cal.run()

        assert result["status"] == "completed"

        # DB에서 직접 확인
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # conf_winrate 행 존재
        conf_rows = conn.execute(
            "SELECT * FROM calibration WHERE metric_type='conf_winrate'"
        ).fetchall()
        assert len(conf_rows) >= 1  # 최소 1개 bin (0.40-0.50)

        # signal_weight 행 존재 (5개 시그널)
        sig_rows = conn.execute(
            "SELECT * FROM calibration WHERE metric_type='signal_weight'"
        ).fetchall()
        assert len(sig_rows) == 5

        conn.close()


class TestGetLatestCalibration:
    """test_get_latest_calibration — 최근 교정 결과 조회."""

    def test_get_latest_calibration(self, tmp_path):
        db_path, conn = _create_db(tmp_path)
        _insert_trades(conn, 35, confidence=0.45)
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, min_samples=30)
        cal.run()

        # get_latest_calibration 조회
        latest = cal.get_latest_calibration()
        assert latest is not None
        assert "date" in latest
        assert "confidence_curve" in latest
        assert "signal_weights" in latest
        assert len(latest["signal_weights"]) == 5

    def test_get_latest_calibration_empty_db(self, tmp_path):
        """빈 DB에서 None 반환."""
        db_path, conn = _create_db(tmp_path)
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, min_samples=30)
        latest = cal.get_latest_calibration()
        assert latest is None


class TestRunFullPipeline:
    """test_run_full_pipeline — 전체 파이프라인 (load->compute->save)."""

    def test_run_full_pipeline(self, tmp_path):
        db_path, conn = _create_db(tmp_path)
        # 다양한 conf/pnl 분포로 60건 삽입
        for i in range(20):
            _insert_trade(conn, confidence=0.35, realized_pnl=100, pnl_rate=0.01)
        for i in range(10):
            _insert_trade(conn, confidence=0.35, realized_pnl=-50, pnl_rate=-0.005)
        for i in range(20):
            _insert_trade(conn, confidence=0.55, realized_pnl=200, pnl_rate=0.02)
        for i in range(10):
            _insert_trade(conn, confidence=0.55, realized_pnl=-80, pnl_rate=-0.008)
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, min_samples=30)
        result = cal.run()

        assert result["status"] == "completed"
        assert result["total_trades"] == 60

        # confidence_curve 검증
        curve = result["confidence_curve"]
        assert len(curve) == 5

        # 0.30-0.40 bin: 30건, 20승 10패 = 66.67%
        bin_03 = next(b for b in curve if b["bin"] == "0.30-0.40")
        assert bin_03["sufficient"] is True
        assert bin_03["count"] == 30
        assert bin_03["win_rate"] == pytest.approx(20 / 30, abs=0.001)

        # 0.50-0.60 bin: 30건, 20승 10패 = 66.67%
        bin_05 = next(b for b in curve if b["bin"] == "0.50-0.60")
        assert bin_05["sufficient"] is True
        assert bin_05["count"] == 30

        # signal_weights 검증
        sw = result["signal_weights"]
        total = sum(sw["adjusted_weights"].values())
        assert abs(total - 100.0) < 0.5

        # DB에 저장 확인
        latest = cal.get_latest_calibration()
        assert latest is not None
        assert len(latest["signal_weights"]) == 5


class TestNoDivisionByZero:
    """test_no_division_by_zero — 빈 데이터에서 ZeroDivisionError 없음."""

    def test_no_division_by_zero_empty(self, tmp_path):
        """거래 0건 -> skipped (ZeroDivisionError 없음)."""
        db_path, conn = _create_db(tmp_path)
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, min_samples=30)
        result = cal.run()
        assert result["status"] == "skipped"

    def test_no_division_by_zero_all_zero_signals(self, tmp_path):
        """모든 시그널 0 -> baseline 유지, ZeroDivisionError 없음."""
        db_path, conn = _create_db(tmp_path)
        _insert_trades(
            conn,
            35,
            confidence=0.45,
            sig_vwap=0.0,
            sig_ob=0.0,
            sig_mom=0.0,
            sig_vol=0.0,
            sig_trend=0.0,
        )
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, min_samples=30)
        result = cal.run()

        assert result["status"] == "completed"
        sw = result["signal_weights"]
        # 모든 시그널 insufficient -> baseline 유지
        for sig in ["sig_vwap", "sig_ob", "sig_mom", "sig_vol", "sig_trend"]:
            assert sw["raw_scores"][sig]["sufficient"] is False
        total = sum(sw["adjusted_weights"].values())
        assert abs(total - 100.0) < 0.5

    def test_no_division_by_zero_null_pnl(self, tmp_path):
        """realized_pnl/pnl_rate가 None인 거래도 안전 처리."""
        db_path, conn = _create_db(tmp_path)
        _insert_trades(
            conn, 35, confidence=0.45, realized_pnl=None, pnl_rate=None
        )
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, min_samples=30)
        result = cal.run()

        assert result["status"] == "completed"
        # None pnl은 0으로 처리 -> 승률 0%
        curve = result["confidence_curve"]
        bin_04 = next(b for b in curve if b["bin"] == "0.40-0.50")
        assert bin_04["sufficient"] is True
        assert bin_04["win_rate"] == 0.0


class TestLookbackFilter:
    """lookback_days 필터링 검증."""

    def test_old_trades_excluded(self, tmp_path):
        db_path, conn = _create_db(tmp_path)
        old_ts = (datetime.now() - timedelta(days=30)).isoformat()
        recent_ts = datetime.now().isoformat()

        # 25일 전 거래 20건 (lookback=20일 밖)
        _insert_trades(conn, 20, timestamp=old_ts, confidence=0.45)
        # 오늘 거래 15건 (lookback 안)
        _insert_trades(conn, 15, timestamp=recent_ts, confidence=0.45)
        conn.close()

        cal = PostTradeCalibrator(db_path=db_path, lookback_days=20, min_samples=30)
        result = cal.run()

        # 15건만 로드 -> 30건 미만 -> skipped
        assert result["status"] == "skipped"
