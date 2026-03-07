"""거래 결과 기반 자가 교정. 장마감 후 배치 실행."""

import sqlite3
from datetime import datetime, timedelta


class PostTradeCalibrator:
    """거래 결과 기반 자가 교정. 장마감 후 배치 실행."""

    def __init__(self, db_path="logs/firefeet.db", lookback_days=20, min_samples=30):
        self.db_path = db_path
        self.lookback_days = lookback_days
        self.min_samples = min_samples  # bin당 최소 샘플 수

    def run(self) -> dict:
        """전체 교정 파이프라인 실행. 결과 dict 반환."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        trades = self._load_trades(conn)
        if len(trades) < self.min_samples:
            conn.close()
            return {
                "status": "skipped",
                "reason": f"insufficient data ({len(trades)} < {self.min_samples})",
            }

        conf_curve = self._compute_confidence_curve(trades)
        signal_weights = self._compute_signal_weights(trades)

        # calibration 테이블에 결과 저장
        self._save_results(conn, conf_curve, signal_weights)
        conn.close()

        return {
            "status": "completed",
            "total_trades": len(trades),
            "confidence_curve": conf_curve,
            "signal_weights": signal_weights,
        }

    def _load_trades(self, conn) -> list:
        """lookback_days 내의 FILLED 스캘핑 거래만 로드."""
        cutoff = (datetime.now() - timedelta(days=self.lookback_days)).isoformat()
        cursor = conn.execute(
            """
            SELECT * FROM decisions
            WHERE status = 'FILLED'
            AND bot_type = 'scalp'
            AND action = 'BUY'
            AND timestamp >= ?
            ORDER BY timestamp
        """,
            (cutoff,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def _compute_confidence_curve(self, trades) -> list:
        """conf 구간별 승률 계산.

        구간: [0, 0.3), [0.3, 0.4), [0.4, 0.5), [0.5, 0.6), [0.6, 1.0]
        반환: [{"bin": "0.30-0.40", "win_rate": 0.45, "count": 52, "avg_pnl": -0.12}, ...]
        """
        bins = [(0, 0.3), (0.3, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 1.0)]
        result = []
        for lo, hi in bins:
            bucket = [
                t
                for t in trades
                if t.get("confidence") is not None and lo <= t["confidence"] < hi
            ]
            if len(bucket) < self.min_samples:
                result.append(
                    {
                        "bin": f"{lo:.2f}-{hi:.2f}",
                        "win_rate": None,
                        "count": len(bucket),
                        "avg_pnl": None,
                        "sufficient": False,
                    }
                )
                continue
            wins = sum(1 for t in bucket if (t.get("realized_pnl") or 0) > 0)
            avg_pnl = sum(t.get("pnl_rate") or 0 for t in bucket) / len(bucket)
            result.append(
                {
                    "bin": f"{lo:.2f}-{hi:.2f}",
                    "win_rate": round(wins / len(bucket), 4),
                    "count": len(bucket),
                    "avg_pnl": round(avg_pnl, 4),
                    "sufficient": True,
                }
            )
        return result

    def _compute_signal_weights(self, trades) -> dict:
        """시그널별 예측력 계산.

        각 시그널(sig_vwap, sig_ob, sig_mom, sig_vol, sig_trend)에 대해:
        - 시그널값 > 0인 거래 중 승률 계산
        - min_samples 미달 시 기존 가중치 유지

        과적합 방지:
        - 가중치 조정 범위: baseline +/-20% 클램프
        - 전체 가중치 합 100으로 정규화
        """
        signal_names = ["sig_vwap", "sig_ob", "sig_mom", "sig_vol", "sig_trend"]
        # 현재 기준 가중치 (scalping_strategies.yaml의 adaptive 프로필)
        baseline_weights = {
            "sig_vwap": 30,
            "sig_ob": 25,
            "sig_mom": 20,
            "sig_vol": 15,
            "sig_trend": 10,
        }

        raw_scores = {}
        for sig in signal_names:
            active = [t for t in trades if (t.get(sig) or 0) > 0]
            if len(active) < self.min_samples:
                raw_scores[sig] = {
                    "win_rate": None,
                    "count": len(active),
                    "sufficient": False,
                }
                continue
            wins = sum(1 for t in active if (t.get("realized_pnl") or 0) > 0)
            raw_scores[sig] = {
                "win_rate": round(wins / len(active), 4),
                "count": len(active),
                "sufficient": True,
            }

        # 가중치 계산 (승률 기반, +/-20% 클램프)
        adjusted = {}
        for sig in signal_names:
            base = baseline_weights[sig]
            if not raw_scores[sig]["sufficient"]:
                adjusted[sig] = base
                continue
            wr = raw_scores[sig]["win_rate"]
            # 승률 0.5 = 기준, >0.5 이면 가중치 증가, <0.5이면 감소
            factor = 1.0 + (wr - 0.5) * 2  # 0.3->0.6, 0.5->1.0, 0.7->1.4
            new_weight = base * factor
            # +/-20% 클램프
            clamped = max(base * 0.8, min(base * 1.2, new_weight))
            adjusted[sig] = round(clamped, 1)

        # 합 100 정규화
        total = sum(adjusted.values())
        if total > 0:
            adjusted = {k: round(v / total * 100, 1) for k, v in adjusted.items()}

        return {
            "raw_scores": raw_scores,
            "adjusted_weights": adjusted,
            "baseline_weights": baseline_weights,
        }

    def _save_results(self, conn, conf_curve, signal_weights):
        """calibration 테이블에 결과 저장."""
        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now().isoformat()

        with conn:
            # conf 교정곡선
            for bucket in conf_curve:
                if bucket["sufficient"]:
                    conn.execute(
                        """
                        INSERT INTO calibration (date, metric_type, metric_key, metric_value, sample_count, created_at)
                        VALUES (?, 'conf_winrate', ?, ?, ?, ?)
                    """,
                        (
                            today,
                            bucket["bin"],
                            bucket["win_rate"],
                            bucket["count"],
                            now,
                        ),
                    )

            # 시그널 가중치
            for sig, weight in signal_weights["adjusted_weights"].items():
                conn.execute(
                    """
                    INSERT INTO calibration (date, metric_type, metric_key, metric_value, sample_count, created_at)
                    VALUES (?, 'signal_weight', ?, ?, ?, ?)
                """,
                    (
                        today,
                        sig,
                        weight,
                        signal_weights["raw_scores"]
                        .get(sig, {})
                        .get("count", 0),
                        now,
                    ),
                )

    def get_latest_calibration(self, conn=None) -> dict:
        """가장 최근 교정 결과 조회. StrategySelector에서 사용."""
        should_close = False
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            should_close = True

        try:
            # 가장 최근 날짜
            row = conn.execute(
                "SELECT MAX(date) as latest FROM calibration"
            ).fetchone()
            if not row or not row["latest"]:
                return None

            latest = row["latest"]

            conf = {}
            for r in conn.execute(
                "SELECT * FROM calibration WHERE date=? AND metric_type='conf_winrate'",
                (latest,),
            ):
                conf[r["metric_key"]] = {
                    "win_rate": r["metric_value"],
                    "count": r["sample_count"],
                }

            weights = {}
            for r in conn.execute(
                "SELECT * FROM calibration WHERE date=? AND metric_type='signal_weight'",
                (latest,),
            ):
                weights[r["metric_key"]] = r["metric_value"]

            return {
                "date": latest,
                "confidence_curve": conf,
                "signal_weights": weights,
            }
        finally:
            if should_close:
                conn.close()
