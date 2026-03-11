"""Portfolio state management — holdings, target codes, stock names."""


class PortfolioManager:
    """
    Manages portfolio holdings, target stock codes, and stock name mapping.

    Extracted from FirefeetTrader to isolate portfolio concerns.
    FirefeetTrader delegates to this class via __getattr__/__setattr__.
    """

    def __init__(self):
        self.portfolio = {}      # {code: {buy_price, qty, orderable_qty}}
        self.stock_names = {}    # {code: name}
        self.target_codes = []   # [code, ...]

    def add_target(self, code, name=None):
        if code not in self.target_codes:
            self.target_codes.append(code)
        if name:
            self.stock_names[code] = name

    def update_target_codes(self, new_stocks):
        """Update target list with new stocks (preserves held stocks)."""
        held_codes = list(self.portfolio.keys())
        new_codes = [s['code'] for s in new_stocks]
        for s in new_stocks:
            self.stock_names[s['code']] = s['name']
        updated = sorted(list(set(held_codes + new_codes)))
        self.target_codes = updated
        print(f"[Trader] Target list updated. Monitoring {len(self.target_codes)} stocks.")

    # sync 시 보존할 커스텀 필드 (broker API에 없는 로컬 상태)
    _PRESERVE_KEYS = frozenset({'buy_timestamp', 'high_price', 'unconfirmed'})

    def sync(self, manager, whitelist):
        """Sync local portfolio with account balance. Preserves local-only fields."""
        balance = manager.get_balance()
        if not balance:
            return

        old_portfolio = self.portfolio
        whitelist_set = set(whitelist)
        self.portfolio = {}
        skipped = []
        for stock in balance['holdings']:
            code = stock['code']
            if code in whitelist_set:
                skipped.append(f"{stock.get('name', code)}({code})")
                continue
            entry = {
                "qty": stock['qty'],
                "orderable_qty": stock.get('orderable_qty', stock['qty']),
                "buy_price": float(stock.get('buy_price', 0))
            }
            # 로컬 전용 필드 복원 (buy_timestamp, high_price 등)
            old_entry = old_portfolio.get(code, {})
            for key in self._PRESERVE_KEYS:
                if key in old_entry:
                    entry[key] = old_entry[key]
            self.portfolio[code] = entry
            self.stock_names[code] = stock.get('name', 'Unknown')
        print(f"[Trader] Portfolio Synced: {len(self.portfolio)} items"
              + (f" (whitelist 제외: {', '.join(skipped)})" if skipped else ""))

    def get_total_invested(self, calc_buy_fee_fn):
        """현재 포트폴리오 총 투자금액 계산 (수수료 포함)."""
        total = 0
        for p in self.portfolio.values():
            amount = p["qty"] * p["buy_price"]
            fee = p.get("buy_fee", calc_buy_fee_fn(amount))
            total += amount + fee
        return total
