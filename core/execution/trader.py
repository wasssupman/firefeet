import copy
import time
import datetime
import yaml
import os
from core.providers.kis_api import OrderType
from core.trade_logger import TradeLogger

class FirefeetTrader:
    def __init__(self, manager, strategy, discard_client=None, settings_path="config/trading_settings.yaml"):
        self.manager = manager
        self.strategy = strategy
        self.discord = discard_client
        self.settings_path = settings_path
        self.target_codes = [] # List of codes to trade
        self.stock_names = {} # {code: name}
        self.portfolio = {} # {code: {buy_price: 1000, qty: 10}}
        self.trade_logger = TradeLogger(strategy="main")
        self.settings = self._load_settings()
        self.rules_path = "config/trading_rules.yaml"
        self.trading_rules = self._load_trading_rules()
        self.sold_today = {}  # {code: {"time": datetime, "profitable": bool}}
        self.consecutive_sl_count = 0      # 연속 손절 카운터
        self.sl_brake_until = None         # 브레이크 해제 시각
        self.daily_realized_pnl = 0        # 당일 누적 실현손익

        # Load initial portfolio
        self.sync_portfolio()

    def _load_settings(self):
        default_settings = {
            "total_budget": 1000000,
        }
        try:
            if os.path.exists(self.settings_path):
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    loaded = yaml.safe_load(f)
                    if loaded:
                        default_settings.update(loaded)
        except Exception as e:
            print(f"[Trader] Settings load failed: {e}")
        return default_settings

    def _load_trading_rules(self):
        """YAML에서 기본 규칙 로드 후, 현재 온도 레벨의 오버라이드를 shallow merge"""
        default_rules = {
            "no_rebuy_after_sell": {"enabled": True, "allow_if_profitable": False, "cooldown_minutes": 0},
            "scan_interval": {"enabled": True, "default_seconds": 300},
            "loop_interval": {"enabled": True, "default_seconds": 10},
            "max_holdings": {"enabled": False, "default_count": 5},
            "consecutive_sl_brake": {"enabled": True, "max_consecutive": 3, "cooldown_minutes": 30},
            "max_position_amount": {"enabled": True, "default_amount": 150000},
            "daily_loss_limit": {"enabled": True, "max_loss_amount": -50000},
        }
        try:
            if os.path.exists(self.rules_path):
                with open(self.rules_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                base = data.get("rules", {})
                # Merge base rules
                for key in base:
                    if key in default_rules and isinstance(base[key], dict):
                        default_rules[key].update(base[key])
                # Apply temperature overrides
                level = getattr(self.strategy, 'temperature_level', 'NEUTRAL')
                overrides = data.get("temperature_overrides", {}).get(level, {})
                for key, val in overrides.items():
                    if key in default_rules and isinstance(val, dict):
                        default_rules[key].update(val)
        except Exception as e:
            print(f"[Trader] Trading rules load failed: {e}")
        return default_rules

    def _can_buy(self, code):
        """매수 가능 여부 판단 → (bool, reason)"""
        # 0a. 연속SL 브레이크 체크
        if self.sl_brake_until and datetime.datetime.now() < self.sl_brake_until:
            return False, f"연속SL 브레이크 ({self.sl_brake_until.strftime('%H:%M')}까지)"

        # 0b. 일일 손실한도 체크
        dl_rule = self.trading_rules.get("daily_loss_limit", {})
        if dl_rule.get("enabled", False):
            max_loss = dl_rule.get("max_loss_amount", -50000)
            if self.daily_realized_pnl <= max_loss:
                return False, f"일일 손실한도 도달 ({self.daily_realized_pnl:+,.0f}원 / {max_loss:+,.0f}원)"

        # 1. no_rebuy_after_sell 체크
        rule = self.trading_rules.get("no_rebuy_after_sell", {})
        if rule.get("enabled", True) and code in self.sold_today:
            sold = self.sold_today[code]
            cooldown = rule.get("cooldown_minutes", 0)
            allow_profit = rule.get("allow_if_profitable", False)

            if cooldown == 0:
                name = self.stock_names.get(code, code)
                return False, f"당일 재매수 금지 ({name})"

            if allow_profit and sold["profitable"]:
                elapsed = (datetime.datetime.now() - sold["time"]).total_seconds() / 60
                if elapsed < cooldown:
                    remaining = int(cooldown - elapsed)
                    name = self.stock_names.get(code, code)
                    return False, f"쿨다운 대기 ({name}, {remaining}분 남음)"
            else:
                name = self.stock_names.get(code, code)
                return False, f"손실 매도 후 재매수 금지 ({name})"

        # 2. max_holdings 체크
        max_rule = self.trading_rules.get("max_holdings", {})
        if max_rule.get("enabled", False):
            max_count = max_rule.get("default_count", 5)
            if len(self.portfolio) >= max_count:
                return False, f"최대 보유 종목 초과 ({len(self.portfolio)}/{max_count})"

        return True, ""

    def get_scan_interval(self):
        rule = self.trading_rules.get("scan_interval", {})
        return rule.get("default_seconds", 300)

    def get_loop_interval(self):
        rule = self.trading_rules.get("loop_interval", {})
        return rule.get("default_seconds", 10)

    def _get_total_invested(self):
        """현재 포트폴리오 총 투자금액 계산 (수수료 포함)"""
        total = 0
        for p in self.portfolio.values():
            amount = p["qty"] * p["buy_price"]
            fee = p.get("buy_fee", self.trade_logger.calc_buy_fee(amount))
            total += amount + fee
        return total

    def add_target(self, code, name=None):
        if code not in self.target_codes:
            self.target_codes.append(code)
        if name:
            self.stock_names[code] = name

    def update_target_codes(self, new_stocks):
        """
        Updates the target list with new stocks (list of dicts with code and name).
        """
        # Keep currently held stocks
        held_codes = list(self.portfolio.keys())
        
        # New codes from scanned stocks
        new_codes = [s['code'] for s in new_stocks]
        for s in new_stocks:
            self.stock_names[s['code']] = s['name']
        
        # Merge: Unique set of (Held Stocks + New Scanned Stocks)
        updated = sorted(list(set(held_codes + new_codes)))
        
        self.target_codes = updated
        print(f"[Trader] Target list updated. Monitoring {len(self.target_codes)} stocks.")

    def sync_portfolio(self):
        """
        Syncs local portfolio with actual account balance.
        화이트리스트 종목은 봇 관리 대상에서 제외.
        """
        balance = self.manager.get_balance()
        if not balance:
            return

        whitelist = set(self.settings.get("whitelist", []))
        self.portfolio = {}
        skipped = []
        for stock in balance['holdings']:
            code = stock['code']
            if code in whitelist:
                skipped.append(f"{stock.get('name', code)}({code})")
                continue
            self.portfolio[code] = {
                "qty": stock['qty'],
                "orderable_qty": stock.get('orderable_qty', stock['qty']),
                "buy_price": float(stock.get('buy_price', 0))
            }
            self.stock_names[code] = stock.get('name', 'Unknown')
        print(f"[Trader] Portfolio Synced: {len(self.portfolio)} items"
              + (f" (whitelist 제외: {', '.join(skipped)})" if skipped else ""))

    def run_loop(self):
        """
        Main Trading Loop.
        """
        print("[Trader] Starting Main Loop...")
        if self.discord:
            self.discord.send("🔥 **Firefeet Trading Bot Started!**")
            
        try:
            while True:
                # Reload settings periodically to allow on-the-fly budget changes
                self.settings = self._load_settings()
                
                now = datetime.datetime.now()
                time_str = now.strftime("%H%M")
                
                for code in self.target_codes:
                    self.process_stock(code, time_str)
                    time.sleep(1) # Rate limit protection
                
                time.sleep(10) # Loop interval
                
        except KeyboardInterrupt:
            print("[Trader] Stopping...")

    def process_stock(self, code, time_str, data_provider_fn):
        if code in set(self.settings.get("whitelist", [])):
            return
        name = self.stock_names.get(code, "Unknown")

        # 1. Get Current Status
        is_held = code in self.portfolio and self.portfolio[code]['qty'] > 0
        
        # 1.5 Fetch Data via Provider
        try:
            df, current_price = data_provider_fn(code)
            if df is None or current_price is None:
                return
        except Exception as e:
            print(f"[Trader] Data provider failed for {name}({code}): {e}")
            return

        # 2. Strategy Signal
        if not is_held:
            self._process_buy(code, name, time_str, df, current_price)
        else:
            self._process_sell(code, name, time_str, df, current_price)

    def _process_buy(self, code, name, time_str, df, current_price):
        try:
            res = self.strategy.check_buy_signal(code, df, current_price)
        except Exception as e:
            print(f"[Trader] {name}({code}) 시세 조회 실패: {e}")
            return

        if not res or res['signal'] != "BUY":
            return

        # 매수 가능 여부 체크 (재매수 금지, 최대 보유 등)
        can, reason = self._can_buy(code)
        if not can:
            print(f"🚫 BUY BLOCKED: {reason}")
            return

        current_price = res['current_price']
        print(f"🚨 BUY SIGNAL: {name}({code}) Price: {current_price}")

        # Budget check: total_budget만 제약
        total_budget = self.settings.get("total_budget", 1000000)
        invested = self._get_total_invested()
        remaining = total_budget - invested

        if remaining <= current_price:
            print(f"⚠️  Budget exhausted. Remaining: {remaining:,.0f} / {total_budget:,} KRW")
            return

        # 포지션 상한 (온도 기반)
        max_pos_pct = getattr(self.strategy, 'max_position_pct', 0.25)
        max_per_stock = total_budget * max_pos_pct

        # 건당 최대 매수금액 상한 (trading_rules)
        pos_rule = self.trading_rules.get("max_position_amount", {})
        if pos_rule.get("enabled", False):
            max_pos_amount = pos_rule.get("default_amount", total_budget * 0.15)
            max_per_stock = min(max_per_stock, max_pos_amount)

        # 상위 N개 종목에 집중 배분 (실제 돌파 가능 종목에 포지션 집중)
        max_concurrent_targets = self.settings.get("max_concurrent_targets", 3)
        unheld = [c for c in self.target_codes
                  if c not in self.portfolio and c not in self.sold_today]
        per_stock = min(remaining / max(1, min(len(unheld), max_concurrent_targets)), max_per_stock)
        qty = int(per_stock // current_price)

        # 최종 안전장치: 매수금액이 remaining 초과하지 않도록
        buy_amount = qty * current_price
        if buy_amount > remaining:
            qty = int(remaining // current_price)
            buy_amount = qty * current_price

        if qty <= 0:
            print(f"⚠️  Per-stock budget ({per_stock:,.0f}) too small for price ({current_price:,}). Skipping.")
            return

        # Execute Buy
        try:
            order_no = self.manager.place_order(code, qty, 0, OrderType.BUY)
        except Exception as e:
            print(f"[Trader] {name}({code}) 매수 주문 API 실패: {e}")
            return

        if order_no:
            print(f"  -> Order Placed! No: {order_no}")
            buy_info = self.trade_logger.log_buy(code, name, qty, current_price)
            self.portfolio[code] = {
                "qty": qty,
                "orderable_qty": qty,
                "buy_price": current_price,
                "buy_fee": buy_info["fee"],
            }
            if self.discord:
                self.discord.send(
                    f"⚡ **BUY** {name}({code}) {qty}주 @ {current_price:,}원\n"
                    f"총비용: {buy_info['net_amount']:,}원 (수수료 {buy_info['fee']:,}원)"
                )
            time.sleep(1)

    def _process_sell(self, code, name, time_str, df, current_price):
        buy_price = self.portfolio[code]['buy_price']
        if buy_price == 0:
            buy_price = current_price

        signal = self.strategy.should_sell(current_price, buy_price, time_str)
        if not signal:
            return

        held_qty = self.portfolio[code]['qty']
        orderable_qty = self.portfolio[code].get('orderable_qty', held_qty)
        qty = min(held_qty, orderable_qty)
        if qty <= 0:
            print(f"⚠️  {name}({code}) 주문가능수량 0 — 미체결/결제대기 (보유: {held_qty})")
            return
        print(f"🚨 SELL SIGNAL ({signal}): {name}({code}) Current: {current_price}, Buy: {buy_price}, Qty: {qty}")

        # 매도 주문 (최대 3회 재시도)
        order_no = None
        max_retries = 3 if signal == "SELL_EOD" else 1
        for attempt in range(max_retries):
            try:
                order_no = self.manager.place_order(code, qty, 0, OrderType.SELL)
                if order_no:
                    break
            except Exception as e:
                print(f"[Trader] {name}({code}) 매도 주문 실패 (시도 {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
        if not order_no:
            print(f"[Trader] {name}({code}) 매도 주문 최종 실패")
            if self.discord:
                self.discord.send(f"❌ **SELL 주문 실패** {name}({code}) — {max_retries}회 시도 실패, 수동 확인 필요")
            return

        if order_no:
            print(f"  -> Order Placed! No: {order_no}")
            sell_info = self.trade_logger.log_sell(code, name, qty, current_price, buy_price, signal)
            if self.discord:
                self.discord.send(
                    f"⚡ **SELL ({signal})** {name}({code}) {qty}주 @ {current_price:,}원\n"
                    f"실현손익: {sell_info['realized_pnl']:+,}원 ({sell_info['pnl_rate']:+.2f}%) | "
                    f"수수료: {sell_info['sell_fee']:,}원"
                )
            self.sold_today[code] = {
                "time": datetime.datetime.now(),
                "profitable": sell_info["realized_pnl"] > 0,
            }
            # 누적 실현손익 추적
            self.daily_realized_pnl += sell_info['realized_pnl']

            # 연속 손절 카운터 업데이트
            if signal == "SELL_STOP_LOSS":
                self.consecutive_sl_count += 1
                sl_rule = self.trading_rules.get("consecutive_sl_brake", {})
                max_consecutive = sl_rule.get("max_consecutive", 3)
                if sl_rule.get("enabled", False) and self.consecutive_sl_count >= max_consecutive:
                    cooldown = sl_rule.get("cooldown_minutes", 30)
                    self.sl_brake_until = datetime.datetime.now() + datetime.timedelta(minutes=cooldown)
                    print(f"🛑 연속 {max_consecutive}회 손절 — {cooldown}분간 매매 중단 ({self.sl_brake_until.strftime('%H:%M')}까지)")
                    if self.discord:
                        self.discord.send(
                            f"🛑 **연속 {max_consecutive}회 손절 브레이크 발동**\n"
                            f"{cooldown}분간 매매 중단 ({self.sl_brake_until.strftime('%H:%M')}까지)\n"
                            f"당일 누적손익: {self.daily_realized_pnl:+,.0f}원"
                        )
                    self.consecutive_sl_count = 0
            elif signal == "SELL_TAKE_PROFIT":
                self.consecutive_sl_count = 0

            del self.portfolio[code]
