import time
import datetime
import yaml
import os
from core.providers.kis_api import OrderType
from core.trade_logger import TradeLogger
from core.execution.risk_guard import RiskGuard
from core.execution.portfolio_manager import PortfolioManager

# Attributes delegated to composed services
_RISK_ATTRS = frozenset({
    'sold_today', 'consecutive_sl_count', 'sl_brake_until',
    'daily_realized_pnl', '_last_reset_date',
})
_PORTFOLIO_ATTRS = frozenset({
    'portfolio', 'stock_names', 'target_codes',
})


class FirefeetTrader:
    def __init__(self, manager, strategy, discord_client=None,
                 settings_path="config/trading_settings.yaml", data_provider_fn=None):
        # Initialize composed services FIRST (before any delegated attribute access)
        object.__setattr__(self, '_risk_guard', RiskGuard())
        object.__setattr__(self, '_portfolio_mgr', PortfolioManager())

        self.manager = manager
        self.strategy = strategy
        self.discord = discord_client
        self.settings_path = settings_path
        self.data_provider_fn = data_provider_fn
        self.trade_logger = TradeLogger(strategy="main")
        self.settings = self._load_settings()
        self.rules_path = "config/trading_rules.yaml"
        self.trading_rules = self._load_trading_rules()

        # Load initial portfolio
        self.sync_portfolio()

    # ── Attribute delegation (backward compatibility) ─────────

    def __getattr__(self, name):
        if name in _RISK_ATTRS:
            return getattr(self._risk_guard, name)
        if name in _PORTFOLIO_ATTRS:
            return getattr(self._portfolio_mgr, name)
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    def __setattr__(self, name, value):
        if name in _RISK_ATTRS:
            setattr(self._risk_guard, name, value)
        elif name in _PORTFOLIO_ATTRS:
            setattr(self._portfolio_mgr, name, value)
        else:
            object.__setattr__(self, name, value)

    # ── Config ────────────────────────────────────────────────

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

    # ── Risk delegation ───────────────────────────────────────

    def reset_daily(self):
        """일일 상태 리셋 (날짜 변경 시에만 실행)."""
        self._risk_guard.reset_daily()

    def _can_buy(self, code):
        """매수 가능 여부 판단 -> (bool, reason)."""
        return self._risk_guard.can_buy(
            code, self.trading_rules, len(self.portfolio), self.stock_names
        )

    # ── Portfolio delegation ──────────────────────────────────

    def add_target(self, code, name=None):
        self._portfolio_mgr.add_target(code, name)

    def update_target_codes(self, new_stocks):
        self._portfolio_mgr.update_target_codes(new_stocks)

    def sync_portfolio(self):
        self._portfolio_mgr.sync(self.manager, self.settings.get("whitelist", []))

    def _get_total_invested(self):
        return self._portfolio_mgr.get_total_invested(self.trade_logger.calc_buy_fee)

    # ── Intervals ─────────────────────────────────────────────

    def get_scan_interval(self):
        rule = self.trading_rules.get("scan_interval", {})
        return rule.get("default_seconds", 300)

    def get_loop_interval(self):
        rule = self.trading_rules.get("loop_interval", {})
        return rule.get("default_seconds", 10)

    # ── Main Loop ─────────────────────────────────────────────

    def run_loop(self):
        """Main Trading Loop."""
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
                    self.process_stock(code, time_str, self.data_provider_fn)
                    time.sleep(1) # Rate limit protection

                time.sleep(10) # Loop interval

        except KeyboardInterrupt:
            print("[Trader] Stopping...")

    def process_stock(self, code, time_str, data_provider_fn=None):
        if code in set(self.settings.get("whitelist", [])):
            return
        name = self.stock_names.get(code, "Unknown")

        # 1. Get Current Status
        is_held = code in self.portfolio and self.portfolio[code]['qty'] > 0

        # 1.5 Fetch Data via Provider
        provider = data_provider_fn or self.data_provider_fn
        if provider is None:
            print(f"[Trader] {name}({code}) data_provider_fn 미설정 — 스킵")
            return
        try:
            df, current_price = provider(code)
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

        if not res:
            return

        target = res.get('target_price', 0)

        if res['signal'] != "BUY":
            if target > 0:
                gap_pct = (target - current_price) / target * 100
                if gap_pct <= 0.3:
                    # 목표가 0.3% 이내 근접: 스크리닝 통과 종목이므로 매수 허용
                    print(f"🔶 [Trader] {name}({code}) 근접 돌파 매수: 현재가={current_price:,} 목표가={target:,} (차이: {gap_pct:.2f}%)")
                else:
                    print(f"[Trader] {name}({code}) 돌파 대기: 현재가={current_price:,} 목표가={target:,} (차이: {gap_pct:+.2f}%)")
                    return
            else:
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

        # 리스크 기반 포지션 사이징
        # qty = risk_amount / stop_distance (손절 시 항상 동일 금액 손실)
        risk_pct = self.settings.get("risk_per_trade_pct", 1.0)
        risk_amount = total_budget * (risk_pct / 100)

        atr14 = res.get('atr14')
        if atr14 and atr14 > 0:
            stop_distance = atr14 * self.strategy.atr_sl_multiplier
        else:
            stop_distance = current_price * abs(self.strategy.stop_loss) / 100

        if stop_distance <= 0:
            stop_distance = current_price * 0.02  # fallback 2%

        qty = int(risk_amount / stop_distance)

        # 포지션 상한 (온도 기반 + 건당 최대 매수금액)
        max_pos_pct = getattr(self.strategy, 'max_position_pct', 0.25)
        max_per_stock = total_budget * max_pos_pct

        pos_rule = self.trading_rules.get("max_position_amount", {})
        if pos_rule.get("enabled", False):
            max_pos_amount = pos_rule.get("default_amount", total_budget * 0.15)
            max_per_stock = min(max_per_stock, max_pos_amount)

        buy_amount = qty * current_price
        if buy_amount > max_per_stock:
            qty = int(max_per_stock // current_price)
            buy_amount = qty * current_price

        # 잔여 예산 초과 방지
        if buy_amount > remaining:
            qty = int(remaining // current_price)
            buy_amount = qty * current_price

        if qty <= 0:
            print(f"⚠️  Risk-based qty=0 (risk={risk_amount:,.0f}, stop_dist={stop_distance:,.0f}, price={current_price:,}). Skipping.")
            return

        print(f"📐 사이징: risk={risk_amount:,.0f}원, SL거리={stop_distance:,.0f}원, 수량={qty}주, 금액={buy_amount:,.0f}원")

        # Execute Buy
        try:
            order_no = self.manager.place_order(code, qty, 0, OrderType.BUY)
        except Exception as e:
            print(f"[Trader] {name}({code}) 매수 주문 API 실패: {e}")
            return

        if order_no:
            print(f"  -> Order Placed! No: {order_no}")
            buy_info = self.trade_logger.log_buy(code, name, qty, current_price)
            # 주문 접수 후 체결 반영을 위해 잔고 동기화
            time.sleep(2)
            self.sync_portfolio()
            if code not in self.portfolio:
                print(f"  ⚠️ {name}({code}) 체결 미확인 — 임시 포트폴리오 기록")
                self.portfolio[code] = {
                    "qty": qty,
                    "orderable_qty": 0,
                    "buy_price": current_price,
                    "buy_fee": buy_info["fee"],
                    "unconfirmed": True,
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

        # ATR 전달: should_sell의 ATR 기반 구조적 SL/TP 활성화
        atr14 = self.strategy.calculate_atr(df, period=14)
        signal = self.strategy.should_sell(current_price, buy_price, time_str, atr=atr14)
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
            self._risk_guard.record_sell(
                code, signal, sell_info['realized_pnl'],
                self.trading_rules, self.discord
            )
            del self.portfolio[code]
