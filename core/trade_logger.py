import csv
import os
import datetime
from collections import defaultdict


class TradeLogger:
    """매매 로깅 & 수수료 계산 & 일별 P&L 추적"""

    BUY_FEE_RATE = 0.00015      # 매수 수수료 0.015%
    SELL_FEE_RATE = 0.00015     # 매도 수수료 0.015%
    SELL_TAX_RATE = 0.0018      # 거래세 0.18%

    CSV_HEADER = [
        "timestamp", "date", "code", "name", "action", "signal",
        "qty", "price", "amount", "fee", "net_amount",
        "buy_price", "realized_pnl", "pnl_rate",
        # simulation fields
        "strategy", "composite", "threshold", "temperature",
        "sig_vwap", "sig_ob", "sig_mom", "sig_vol", "sig_trend",
        "spread_bps", "penalty", "tp_pct", "sl_pct", "vwap_dist",
        "hold_seconds", "peak_profit_pct",
    ]

    def __init__(self, log_dir="logs", strategy="main"):
        self.log_dir = log_dir
        self.strategy = strategy
        self.csv_path = os.path.join(log_dir, f"trades_{strategy}.csv")
        os.makedirs(log_dir, exist_ok=True)
        self._ensure_csv()

    def _ensure_csv(self):
        if not os.path.exists(self.csv_path) or os.path.getsize(self.csv_path) == 0:
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(self.CSV_HEADER)

    # ── Fee Calculation ──────────────────────────────────────

    def calc_buy_fee(self, amount):
        """매수 수수료 (원 단위, 절사)"""
        return int(amount * self.BUY_FEE_RATE)

    def calc_sell_fee(self, amount):
        """매도 수수료 + 거래세 (원 단위, 절사)"""
        return int(amount * (self.SELL_FEE_RATE + self.SELL_TAX_RATE))

    # ── Logging ──────────────────────────────────────────────

    def log_buy(self, code, name, qty, price):
        """매수 기록. Returns dict with fee info."""
        now = datetime.datetime.now()
        amount = qty * price
        fee = self.calc_buy_fee(amount)
        net_amount = amount + fee  # 총 매수 비용

        row = {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "code": code,
            "name": name,
            "action": "BUY",
            "signal": "BUY",
            "qty": qty,
            "price": price,
            "amount": amount,
            "fee": fee,
            "net_amount": net_amount,
            "buy_price": "",
            "realized_pnl": "",
            "pnl_rate": "",
        }
        self._write_row(row)
        print(f"  [Trade] BUY {name}({code}) {qty}주 @ {price:,}원 | 총비용: {net_amount:,}원 (수수료 {fee:,}원)")
        return {"fee": fee, "net_amount": net_amount}

    def log_sell(self, code, name, qty, price, buy_price, signal="SELL"):
        """매도 기록. Returns dict with realized P&L info."""
        now = datetime.datetime.now()

        sell_amount = qty * price
        sell_fee = self.calc_sell_fee(sell_amount)
        sell_net = sell_amount - sell_fee  # 순 수령액

        buy_amount = qty * buy_price
        buy_fee = self.calc_buy_fee(buy_amount)
        buy_net = buy_amount + buy_fee  # 총 매수 비용

        realized_pnl = sell_net - buy_net
        pnl_rate = (realized_pnl / buy_net * 100) if buy_net else 0.0

        row = {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "code": code,
            "name": name,
            "action": "SELL",
            "signal": signal,
            "qty": qty,
            "price": price,
            "amount": sell_amount,
            "fee": sell_fee,
            "net_amount": sell_net,
            "buy_price": buy_price,
            "realized_pnl": realized_pnl,
            "pnl_rate": round(pnl_rate, 2),
        }
        self._write_row(row)
        print(f"  [Trade] SELL({signal}) {name}({code}) {qty}주 @ {price:,}원 | "
              f"실현손익: {realized_pnl:+,}원 ({pnl_rate:+.2f}%) | 수수료: {sell_fee:,}원")
        return {
            "sell_fee": sell_fee,
            "sell_net": sell_net,
            "buy_fee": buy_fee,
            "buy_net": buy_net,
            "realized_pnl": realized_pnl,
            "pnl_rate": pnl_rate,
        }

    # ── Scalping Logging ─────────────────────────────────

    def log_scalp_buy(self, code, name, qty, price, signal_confidence=0, **kwargs):
        """스캘핑 매수 기록"""
        now = datetime.datetime.now()
        amount = qty * price
        fee = self.calc_buy_fee(amount)
        net_amount = amount + fee

        row = {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "code": code,
            "name": name,
            "action": "SCALP_BUY",
            "signal": f"SCALP_BUY(conf={signal_confidence:.2f})",
            "qty": qty,
            "price": price,
            "amount": amount,
            "fee": fee,
            "net_amount": net_amount,
            "buy_price": "",
            "realized_pnl": "",
            "pnl_rate": "",
            "strategy": kwargs.get("strategy", ""),
            "composite": kwargs.get("composite", ""),
            "threshold": kwargs.get("threshold", ""),
            "temperature": kwargs.get("temperature", ""),
            "sig_vwap": kwargs.get("sig_vwap", ""),
            "sig_ob": kwargs.get("sig_ob", ""),
            "sig_mom": kwargs.get("sig_mom", ""),
            "sig_vol": kwargs.get("sig_vol", ""),
            "sig_trend": kwargs.get("sig_trend", ""),
            "spread_bps": kwargs.get("spread_bps", ""),
            "penalty": kwargs.get("penalty", ""),
            "tp_pct": kwargs.get("tp_pct", ""),
            "sl_pct": kwargs.get("sl_pct", ""),
            "vwap_dist": kwargs.get("vwap_dist", ""),
            "hold_seconds": "",
            "peak_profit_pct": "",
        }
        self._write_row(row)
        print(f"  [Scalp] BUY {name}({code}) {qty}주 @ {price:,}원 | "
              f"총비용: {net_amount:,}원 (conf={signal_confidence:.2f})")
        return {"fee": fee, "net_amount": net_amount}

    def log_scalp_sell(self, code, name, qty, price, buy_price, signal="SCALP_SELL", **kwargs):
        """스캘핑 매도 기록"""
        now = datetime.datetime.now()

        sell_amount = qty * price
        sell_fee = self.calc_sell_fee(sell_amount)
        sell_net = sell_amount - sell_fee

        buy_amount = qty * buy_price
        buy_fee = self.calc_buy_fee(buy_amount)
        buy_net = buy_amount + buy_fee

        realized_pnl = sell_net - buy_net
        pnl_rate = (realized_pnl / buy_net * 100) if buy_net else 0.0

        row = {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "code": code,
            "name": name,
            "action": "SCALP_SELL",
            "signal": signal,
            "qty": qty,
            "price": price,
            "amount": sell_amount,
            "fee": sell_fee,
            "net_amount": sell_net,
            "buy_price": buy_price,
            "realized_pnl": realized_pnl,
            "pnl_rate": round(pnl_rate, 2),
            "strategy": kwargs.get("strategy", ""),
            "composite": kwargs.get("composite", ""),
            "threshold": kwargs.get("threshold", ""),
            "temperature": kwargs.get("temperature", ""),
            "sig_vwap": kwargs.get("sig_vwap", ""),
            "sig_ob": kwargs.get("sig_ob", ""),
            "sig_mom": kwargs.get("sig_mom", ""),
            "sig_vol": kwargs.get("sig_vol", ""),
            "sig_trend": kwargs.get("sig_trend", ""),
            "spread_bps": kwargs.get("spread_bps", ""),
            "penalty": kwargs.get("penalty", ""),
            "tp_pct": kwargs.get("tp_pct", ""),
            "sl_pct": kwargs.get("sl_pct", ""),
            "vwap_dist": kwargs.get("vwap_dist", ""),
            "hold_seconds": kwargs.get("hold_seconds", ""),
            "peak_profit_pct": kwargs.get("peak_profit_pct", ""),
        }
        self._write_row(row)
        print(f"  [Scalp] SELL({signal}) {name}({code}) {qty}주 @ {price:,}원 | "
              f"실현손익: {realized_pnl:+,}원 ({pnl_rate:+.2f}%)")
        return {
            "sell_fee": sell_fee,
            "sell_net": sell_net,
            "buy_fee": buy_fee,
            "buy_net": buy_net,
            "realized_pnl": realized_pnl,
            "pnl_rate": pnl_rate,
        }

    def _write_row(self, row_dict):
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_HEADER)
            writer.writerow(row_dict)

    # ── Summaries ────────────────────────────────────────────

    def _read_rows(self):
        rows = []
        if not os.path.exists(self.csv_path):
            return rows
        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
        return rows

    def get_daily_summary(self, date=None):
        """특정 날짜 거래 요약. date는 'YYYY-MM-DD' 문자열."""
        if date is None:
            date = datetime.date.today().isoformat()
        rows = [r for r in self._read_rows() if r["date"] == date]
        return self._summarize(rows, date)

    def get_all_summaries(self):
        """전체 기간 날짜별 요약 리스트"""
        rows = self._read_rows()
        by_date = defaultdict(list)
        for r in rows:
            by_date[r["date"]].append(r)
        summaries = []
        for d in sorted(by_date):
            summaries.append(self._summarize(by_date[d], d))
        return summaries

    def _summarize(self, rows, date):
        buys = [r for r in rows if "BUY" in r["action"]]
        sells = [r for r in rows if "SELL" in r["action"]]
        total_buy_amount = sum(int(float(r["net_amount"])) for r in buys)
        total_sell_amount = sum(int(float(r["net_amount"])) for r in sells)
        total_fee = sum(int(float(r["fee"])) for r in rows)
        realized_pnl = sum(int(float(r["realized_pnl"])) for r in sells if r["realized_pnl"])
        return {
            "date": date,
            "buy_count": len(buys),
            "sell_count": len(sells),
            "total_buy_amount": total_buy_amount,
            "total_sell_amount": total_sell_amount,
            "total_fee": total_fee,
            "realized_pnl": realized_pnl,
        }

    def print_daily_summary(self, date=None):
        """오늘(또는 특정 날짜) 거래 요약 출력"""
        s = self.get_daily_summary(date)
        label = self.strategy.upper()
        if s["buy_count"] == 0 and s["sell_count"] == 0:
            print(f"\n📊 [{label}] [{s['date']}] 거래 없음")
            return
        print(f"\n{'='*50}")
        print(f"📊 [{label}] 일별 거래 요약 [{s['date']}]")
        print(f"{'='*50}")
        print(f"  매수: {s['buy_count']}건 | 총 매수비용: {s['total_buy_amount']:,}원")
        print(f"  매도: {s['sell_count']}건 | 총 수령액:   {s['total_sell_amount']:,}원")
        print(f"  수수료 합계: {s['total_fee']:,}원")
        print(f"  실현손익:    {s['realized_pnl']:+,}원")
        print(f"{'='*50}")

    def print_all_summaries(self):
        """누적 P&L 테이블 출력"""
        summaries = self.get_all_summaries()
        label = self.strategy.upper()
        if not summaries:
            print(f"\n📊 [{label}] 거래 기록 없음")
            return
        print(f"\n{'='*70}")
        print(f"📊 [{label}] 누적 P&L 요약")
        print(f"{'='*70}")
        print(f"{'날짜':<12} {'매수':>4} {'매도':>4} {'수수료':>10} {'실현손익':>12}")
        print(f"{'-'*70}")
        cumulative = 0
        total_fee = 0
        for s in summaries:
            cumulative += s["realized_pnl"]
            total_fee += s["total_fee"]
            print(f"{s['date']:<12} {s['buy_count']:>4} {s['sell_count']:>4} "
                  f"{s['total_fee']:>10,} {s['realized_pnl']:>+12,}")
        print(f"{'-'*70}")
        print(f"{'합계':<12} {'':>4} {'':>4} {total_fee:>10,} {cumulative:>+12,}")
        print(f"{'='*70}")


if __name__ == "__main__":
    strategies = ["main", "scalp"]
    all_summaries = []

    for strat in strategies:
        logger = TradeLogger(strategy=strat)
        logger.print_all_summaries()
        print()
        logger.print_daily_summary()
        all_summaries.extend(logger.get_all_summaries())

    # 통합 요약
    if all_summaries:
        by_date = defaultdict(lambda: {"buy_count": 0, "sell_count": 0,
                                       "total_fee": 0, "realized_pnl": 0})
        for s in all_summaries:
            d = by_date[s["date"]]
            d["buy_count"] += s["buy_count"]
            d["sell_count"] += s["sell_count"]
            d["total_fee"] += s["total_fee"]
            d["realized_pnl"] += s["realized_pnl"]

        print(f"\n{'='*70}")
        print(f"📊 [통합] 누적 P&L 요약")
        print(f"{'='*70}")
        print(f"{'날짜':<12} {'매수':>4} {'매도':>4} {'수수료':>10} {'실현손익':>12}")
        print(f"{'-'*70}")
        cumulative = 0
        total_fee = 0
        for date in sorted(by_date):
            s = by_date[date]
            cumulative += s["realized_pnl"]
            total_fee += s["total_fee"]
            print(f"{date:<12} {s['buy_count']:>4} {s['sell_count']:>4} "
                  f"{s['total_fee']:>10,} {s['realized_pnl']:>+12,}")
        print(f"{'-'*70}")
        print(f"{'합계':<12} {'':>4} {'':>4} {total_fee:>10,} {cumulative:>+12,}")
        print(f"{'='*70}")
