"""Firefeet Trade Review — CSV 기반 거래 성과 분석 스크립트."""

import argparse
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "logs")

# 수수료율
BUY_FEE_RATE = 0.00015
SELL_FEE_RATE = 0.00015 + 0.0018  # 매도 수수료 + 거래세
ROUND_TRIP_PCT = (BUY_FEE_RATE + SELL_FEE_RATE) * 100  # ~0.21%


FULL_HEADER = [
    "timestamp", "date", "code", "name", "action", "signal",
    "qty", "price", "amount", "fee", "net_amount",
    "buy_price", "realized_pnl", "pnl_rate",
    "strategy", "composite", "threshold", "temperature",
    "sig_vwap", "sig_ob", "sig_mom", "sig_vol", "sig_trend",
    "spread_bps", "penalty", "tp_pct", "sl_pct", "vwap_dist",
    "hold_seconds", "peak_profit_pct",
]


def load_trades(strategy: str, days: int) -> pd.DataFrame:
    csv_path = os.path.join(LOGS_DIR, f"trades_{strategy}.csv")
    if not os.path.exists(csv_path):
        print(f"파일 없음: {csv_path}")
        sys.exit(1)

    # CSV 컬럼 수가 중간에 14→30으로 바뀔 수 있음 (확장 로깅 적용 전후)
    # 헤더 행의 컬럼 수를 먼저 확인
    with open(csv_path, "r") as f:
        header_line = f.readline().strip()
    n_cols = len(header_line.split(","))
    names = FULL_HEADER[:n_cols] if n_cols <= len(FULL_HEADER) else FULL_HEADER

    # 컬럼 수가 다른 행은 스킵
    df = pd.read_csv(csv_path, names=names, header=0, on_bad_lines="skip")
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    if days > 0:
        cutoff = datetime.now() - timedelta(days=days)
        df = df[df["timestamp"] >= cutoff]

    return df


def analyze(df: pd.DataFrame):
    # action: SELL (main/swing) 또는 SCALP_SELL (scalp)
    sell_mask = df["action"].str.contains("SELL", na=False)
    buy_mask = df["action"].str.contains("BUY", na=False)
    sells = df[sell_mask].copy()
    buys = df[buy_mask]

    if sells.empty:
        print("분석할 매도 거래 없음")
        return

    # 기본 지표
    total_trades = len(sells)
    wins = sells[sells["realized_pnl"] > 0]
    losses = sells[sells["realized_pnl"] <= 0]
    win_rate = len(wins) / total_trades * 100

    total_profit = wins["realized_pnl"].sum() if not wins.empty else 0
    total_loss = abs(losses["realized_pnl"].sum()) if not losses.empty else 0
    pf = total_profit / total_loss if total_loss > 0 else float("inf")
    net_pnl = sells["realized_pnl"].sum()

    total_fees = df["fee"].sum()

    # 세전 손익 (수수료 미포함 추정)
    gross_pnl = net_pnl + total_fees

    print("=" * 60)
    print("📊 거래 성과 요약")
    print("=" * 60)
    print(f"총 거래수:     {total_trades}건")
    print(f"승률:          {win_rate:.1f}% ({len(wins)}승 / {len(losses)}패)")
    print(f"Profit Factor: {pf:.2f}")
    print(f"세전 손익:     {gross_pnl:+,.0f}원")
    print(f"수수료 합계:   {total_fees:,.0f}원")
    print(f"세후 순손익:   {net_pnl:+,.0f}원")
    print(f"평균 수익:     {wins['realized_pnl'].mean():+,.0f}원" if not wins.empty else "")
    print(f"평균 손실:     {losses['realized_pnl'].mean():+,.0f}원" if not losses.empty else "")

    # 청산 패턴 — 세분화된 시그널을 기본 유형으로 그룹핑
    if "signal" in sells.columns:
        def normalize_signal(s):
            s = str(s)
            for base in ["TP", "TAKE_PROFIT", "SL", "STOP_LOSS", "TRAILING",
                          "SIGNAL", "RISK", "CIRCUIT", "EOD", "TIMEOUT",
                          "WALL", "BB", "RESISTANCE"]:
                if base in s.upper():
                    return base.replace("TAKE_PROFIT", "TP").replace("STOP_LOSS", "SL")
            return s

        sells["sig_type"] = sells["signal"].apply(normalize_signal)
        print("\n" + "=" * 60)
        print("📋 청산 시그널별 분석")
        print("=" * 60)
        print(f"{'시그널':<14} {'건수':>6} {'승률':>8} {'평균손익':>12} {'누적손익':>14}")
        print("-" * 58)
        for sig, grp in sells.groupby("sig_type"):
            sig_wins = grp[grp["realized_pnl"] > 0]
            sig_wr = len(sig_wins) / len(grp) * 100
            print(f"{str(sig):<14} {len(grp):>6} {sig_wr:>7.1f}% {grp['realized_pnl'].mean():>+12,.0f} {grp['realized_pnl'].sum():>+14,.0f}")

    # conf 구간별 분석
    if "composite" in sells.columns:
        sells["conf_bin"] = pd.cut(
            pd.to_numeric(sells["composite"], errors="coerce"),
            bins=[0, 0.2, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
            labels=["0~0.2", "0.2~0.3", "0.3~0.35", "0.35~0.4", "0.4~0.5",
                    "0.5~0.6", "0.6~0.7", "0.7~0.8", "0.8~1.0"],
        )
        print("\n" + "=" * 60)
        print("🎯 Confidence 구간별 분석")
        print("=" * 60)
        print(f"{'구간':<12} {'건수':>6} {'승률':>8} {'평균손익':>12} {'누적손익':>14}")
        print("-" * 56)
        for bin_label, grp in sells.groupby("conf_bin", observed=True):
            if grp.empty:
                continue
            sig_wins = grp[grp["realized_pnl"] > 0]
            sig_wr = len(sig_wins) / len(grp) * 100
            print(f"{str(bin_label):<12} {len(grp):>6} {sig_wr:>7.1f}% {grp['realized_pnl'].mean():>+12,.0f} {grp['realized_pnl'].sum():>+14,.0f}")

    # 시간대별 분석
    if "timestamp" in sells.columns:
        sells["hour"] = sells["timestamp"].dt.hour
        print("\n" + "=" * 60)
        print("⏰ 시간대별 분석")
        print("=" * 60)
        print(f"{'시간':<8} {'건수':>6} {'승률':>8} {'누적손익':>14}")
        print("-" * 40)
        for hour, grp in sells.groupby("hour"):
            sig_wins = grp[grp["realized_pnl"] > 0]
            sig_wr = len(sig_wins) / len(grp) * 100
            print(f"{int(hour):>2}시     {len(grp):>6} {sig_wr:>7.1f}% {grp['realized_pnl'].sum():>+14,.0f}")

    print("\n" + "=" * 60)
    print(f"💰 수수료 영향: 세전 {gross_pnl:+,.0f}원 → 세후 {net_pnl:+,.0f}원 (수수료 {total_fees:,.0f}원, 총 손익의 {total_fees / max(abs(net_pnl), 1) * 100:.0f}%)")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Firefeet 거래 성과 분석")
    parser.add_argument("--days", type=int, default=7, help="분석 기간 (일, 0=전체)")
    parser.add_argument("--strategy", default="scalp", choices=["scalp", "swing", "main"], help="전략 타입")
    args = parser.parse_args()

    df = load_trades(args.strategy, args.days)
    if df.empty:
        print(f"최근 {args.days}일 거래 데이터 없음")
        sys.exit(0)

    print(f"\n📅 분석 기간: 최근 {args.days}일 | 전략: {args.strategy}")
    print(f"📁 데이터: {len(df)}행 로드됨\n")
    analyze(df)


if __name__ == "__main__":
    main()
