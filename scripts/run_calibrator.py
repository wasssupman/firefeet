"""장마감 후 거래 데이터 기반 자동 교정."""

from core.calibration.post_trade_calibrator import PostTradeCalibrator


def main():
    calibrator = PostTradeCalibrator()
    result = calibrator.run()

    if result["status"] == "skipped":
        print(f"[Calibrator] 건너뜀: {result['reason']}")
        return

    print(f"[Calibrator] 완료 — {result['total_trades']}건 분석")
    print("\nConfidence 교정곡선:")
    for bucket in result["confidence_curve"]:
        if bucket["sufficient"]:
            print(
                f"  {bucket['bin']}: 승률 {bucket['win_rate']:.1%}"
                f" ({bucket['count']}건, 평균 {bucket['avg_pnl']:+.2%})"
            )
        else:
            print(f"  {bucket['bin']}: 데이터 부족 ({bucket['count']}건 < 30)")

    print("\n시그널 가중치:")
    sw = result["signal_weights"]
    for sig in ["sig_vwap", "sig_ob", "sig_mom", "sig_vol", "sig_trend"]:
        base = sw["baseline_weights"][sig]
        adj = sw["adjusted_weights"][sig]
        raw = sw["raw_scores"].get(sig, {})
        wr_str = (
            f"승률 {raw['win_rate']:.1%}" if raw.get("sufficient") else "부족"
        )
        change = adj - base
        print(f"  {sig}: {base} -> {adj} ({change:+.1f}) [{wr_str}]")


if __name__ == "__main__":
    main()
