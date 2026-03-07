#!/usr/bin/env python3
"""스캘핑 설정 변경 효과 시뮬레이션 — 과거 CSV 로그 기반 Before/After 비교.

Usage:
    python3 scripts/simulate_scalp_config.py [--csv PATH] [--date YYYY-MM-DD]
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field

# 수수료율
FEE_BUY_PCT = 0.015 / 100   # 매수 0.015%
FEE_SELL_PCT = (0.015 + 0.18) / 100  # 매도 0.015% + 거래세 0.18%


@dataclass
class SimConfig:
    """시뮬레이션 설정"""
    name: str
    conf_threshold: float = 0.35
    max_losses_per_stock: int = 999
    max_entries_per_stock: int = 999
    max_circuit_resets: int = 999
    max_consecutive_losses: int = 5
    max_daily_trades: int = 100
    risk_max_loss_pct: float = 1.0
    risk_max_loss_amount: float = 20000
    sell_cooldown_seconds: float = 300


@dataclass
class SimState:
    """시뮬레이션 런타임 상태"""
    daily_pnl: float = 0
    trade_count: int = 0
    buy_count: int = 0
    consecutive_losses: int = 0
    circuit_broken: bool = False
    circuit_reset_count: int = 0
    per_stock_losses: dict = field(default_factory=dict)
    per_stock_entries: dict = field(default_factory=dict)
    last_sell_time: dict = field(default_factory=dict)  # {code: timestamp}
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0
    gross_loss: float = 0
    filtered_reasons: dict = field(default_factory=lambda: defaultdict(int))


def parse_trades(csv_path, target_date=None):
    """CSV 거래 로그 파싱 → BUY/SELL 페어 리스트 반환."""
    if not os.path.exists(csv_path):
        print(f"[ERROR] CSV 파일 없음: {csv_path}")
        sys.exit(1)

    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if target_date and row.get("date", "") != target_date:
                continue
            rows.append(row)

    # BUY/SELL 페어 매칭
    buys = {}  # {code: [buy_rows]}
    pairs = []

    for row in rows:
        action = row.get("action", "")
        code = row.get("code", "")
        if not code:
            continue

        if "BUY" in action:
            buys.setdefault(code, []).append(row)
        elif "SELL" in action:
            # 가장 오래된 BUY와 매칭
            if code in buys and buys[code]:
                buy_row = buys[code].pop(0)
                pairs.append((buy_row, row))

    return pairs


def extract_confidence(signal_str):
    """SCALP_BUY(conf=0.35) → 0.35"""
    if "conf=" in signal_str:
        try:
            return float(signal_str.split("conf=")[1].rstrip(")"))
        except (ValueError, IndexError):
            pass
    return 0.0


def simulate(pairs, config):
    """설정으로 거래 필터링 후 결과 산출."""
    state = SimState()

    for buy_row, sell_row in pairs:
        code = buy_row.get("code", "")
        timestamp = buy_row.get("timestamp", "")

        # 1. Confidence threshold
        conf = extract_confidence(buy_row.get("signal", ""))
        if conf > 0 and conf < config.conf_threshold:
            state.filtered_reasons["conf_filter"] += 1
            continue

        # 2. 일일 거래 한도
        if max(state.trade_count, state.buy_count) >= config.max_daily_trades:
            state.filtered_reasons["daily_trade_limit"] += 1
            continue

        # 3. 서킷브레이커 (간이 시뮬)
        if state.circuit_broken:
            state.filtered_reasons["circuit_breaker"] += 1
            # 리셋 체크 (실제 쿨다운은 시간 기반이지만 여기선 간소화)
            if state.circuit_reset_count >= config.max_circuit_resets:
                continue
            state.circuit_reset_count += 1
            state.circuit_broken = False
            state.consecutive_losses = 0

        # 4. 종목별 손실 한도
        if state.per_stock_losses.get(code, 0) >= config.max_losses_per_stock:
            state.filtered_reasons["per_stock_loss"] += 1
            continue

        # 5. 종목별 진입 한도
        if state.per_stock_entries.get(code, 0) >= config.max_entries_per_stock:
            state.filtered_reasons["per_stock_entry"] += 1
            continue

        # 6. 매도 쿨다운 (간이: timestamp 기반)
        # CSV에서 시간 파싱 가능하면 체크
        # (생략 — 실제 쿨다운은 엔진 레벨에서 처리)

        # --- 거래 통과 ---
        state.buy_count += 1
        state.per_stock_entries[code] = state.per_stock_entries.get(code, 0) + 1

        # 손익 계산
        buy_price = float(buy_row.get("price", 0) or 0)
        sell_price = float(sell_row.get("price", 0) or 0)
        qty = int(float(sell_row.get("qty", 0) or 0))

        if buy_price <= 0 or sell_price <= 0 or qty <= 0:
            continue

        # RISK 한도 시뮬: 실제 손실률이 RISK 한도 초과하면 RISK 한도에서 잘림
        actual_loss_pct = (sell_price - buy_price) / buy_price * 100
        actual_loss_amount = (sell_price - buy_price) * qty

        # RISK 강제청산 가격 시뮬
        risk_floor_price = buy_price * (1 - config.risk_max_loss_pct / 100)
        risk_floor_amount = buy_price - config.risk_max_loss_amount / qty if qty > 0 else 0
        effective_risk_price = max(risk_floor_price, risk_floor_amount)

        if sell_price < effective_risk_price:
            sell_price = effective_risk_price

        gross_pnl = (sell_price - buy_price) * qty
        buy_fee = buy_price * qty * FEE_BUY_PCT
        sell_fee = sell_price * qty * FEE_SELL_PCT
        net_pnl = gross_pnl - buy_fee - sell_fee

        state.daily_pnl += net_pnl
        state.trade_count += 1

        if net_pnl >= 0:
            state.wins += 1
            state.gross_profit += net_pnl
            state.consecutive_losses = 0
        else:
            state.losses += 1
            state.gross_loss += abs(net_pnl)
            state.consecutive_losses += 1
            state.per_stock_losses[code] = state.per_stock_losses.get(code, 0) + 1

        # 서킷브레이커 체크
        if state.consecutive_losses >= config.max_consecutive_losses:
            state.circuit_broken = True

    return state


def print_result(label, state, config):
    """결과 출력."""
    total = state.wins + state.losses
    win_rate = (state.wins / total * 100) if total > 0 else 0
    pf = (state.gross_profit / state.gross_loss) if state.gross_loss > 0 else float("inf")

    print(f"\n{'='*55}")
    print(f"  {label}")
    print(f"{'='*55}")
    print(f"  설정: conf≥{config.conf_threshold}, "
          f"종목손실≤{config.max_losses_per_stock}, "
          f"종목진입≤{config.max_entries_per_stock}, "
          f"서킷리셋≤{config.max_circuit_resets}")
    print(f"  RISK: max_loss_pct={config.risk_max_loss_pct}%, "
          f"max_loss_amount={config.risk_max_loss_amount:,.0f}원, "
          f"일한도={config.max_daily_trades}")
    print(f"{'-'*55}")
    print(f"  거래수: {total}건 (승 {state.wins} / 패 {state.losses})")
    print(f"  승률: {win_rate:.1f}%")
    print(f"  총 손익: {state.daily_pnl:+,.0f}원")
    print(f"  총 이익: {state.gross_profit:+,.0f}원")
    print(f"  총 손실: -{state.gross_loss:,.0f}원")
    print(f"  PF: {pf:.2f}")
    if state.filtered_reasons:
        print(f"  필터링 내역:")
        for reason, count in sorted(state.filtered_reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {count}건")
    print(f"{'='*55}")


def main():
    parser = argparse.ArgumentParser(description="스캘핑 설정 시뮬레이션")
    parser.add_argument("--csv", default="logs/trades_scalp.csv", help="거래 CSV 경로")
    parser.add_argument("--date", default=None, help="특정 날짜 필터 (YYYY-MM-DD)")
    args = parser.parse_args()

    pairs = parse_trades(args.csv, args.date)
    if not pairs:
        print(f"[WARN] 거래 페어 없음 (csv={args.csv}, date={args.date})")
        return

    print(f"\n총 거래 페어: {len(pairs)}건")
    if args.date:
        print(f"날짜 필터: {args.date}")

    # Before: 기존 설정
    before_config = SimConfig(
        name="Before (기존)",
        conf_threshold=0.35,
        max_losses_per_stock=999,
        max_entries_per_stock=999,
        max_circuit_resets=999,
        max_daily_trades=20,
        risk_max_loss_pct=1.0,
        risk_max_loss_amount=20000,
        sell_cooldown_seconds=300,
    )

    # After: 신규 설정
    after_config = SimConfig(
        name="After (신규)",
        conf_threshold=0.40,
        max_losses_per_stock=2,
        max_entries_per_stock=3,
        max_circuit_resets=1,
        max_daily_trades=20,
        risk_max_loss_pct=0.7,
        risk_max_loss_amount=10000,
        sell_cooldown_seconds=600,
    )

    before_state = simulate(pairs, before_config)
    after_state = simulate(pairs, after_config)

    print_result("BEFORE (기존 설정)", before_state, before_config)
    print_result("AFTER (신규 설정)", after_state, after_config)

    # 개선 요약
    print(f"\n{'='*55}")
    print(f"  개선 요약")
    print(f"{'='*55}")
    before_total = before_state.wins + before_state.losses
    after_total = after_state.wins + after_state.losses
    print(f"  거래수: {before_total} → {after_total} ({after_total - before_total:+d})")
    print(f"  손익: {before_state.daily_pnl:+,.0f} → {after_state.daily_pnl:+,.0f} "
          f"({after_state.daily_pnl - before_state.daily_pnl:+,.0f}원)")
    before_wr = (before_state.wins / before_total * 100) if before_total > 0 else 0
    after_wr = (after_state.wins / after_total * 100) if after_total > 0 else 0
    print(f"  승률: {before_wr:.1f}% → {after_wr:.1f}%")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
