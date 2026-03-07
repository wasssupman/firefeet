"""Trading risk guard — daily resets, sell tracking, SL brakes, loss limits."""

import datetime


class RiskGuard:
    """
    Encapsulates trading risk state and checking logic.

    Extracted from FirefeetTrader to isolate risk management concerns.
    FirefeetTrader delegates to this class via __getattr__/__setattr__.
    """

    def __init__(self):
        self.sold_today = {}          # {code: {"time": datetime, "profitable": bool}}
        self.consecutive_sl_count = 0
        self.sl_brake_until = None
        self.daily_realized_pnl = 0
        self._last_reset_date = None

    def reset_daily(self):
        """일일 상태 리셋 (날짜 변경 시에만 실행)."""
        today = datetime.date.today()
        if self._last_reset_date == today:
            return
        self.sold_today = {}
        self.daily_realized_pnl = 0
        self.consecutive_sl_count = 0
        self.sl_brake_until = None
        self._last_reset_date = today
        print(f"[Trader] 일일 리셋 완료 ({today})")

    def can_buy(self, code, trading_rules, portfolio_size, stock_names):
        """매수 가능 여부 판단 -> (bool, reason)."""
        # 0a. 연속SL 브레이크 체크
        if self.sl_brake_until and datetime.datetime.now() < self.sl_brake_until:
            return False, f"연속SL 브레이크 ({self.sl_brake_until.strftime('%H:%M')}까지)"

        # 0b. 일일 손실한도 체크
        dl_rule = trading_rules.get("daily_loss_limit", {})
        if dl_rule.get("enabled", False):
            max_loss = dl_rule.get("max_loss_amount", -50000)
            if self.daily_realized_pnl <= max_loss:
                return False, f"일일 손실한도 도달 ({self.daily_realized_pnl:+,.0f}원 / {max_loss:+,.0f}원)"

        # 1. no_rebuy_after_sell 체크
        rule = trading_rules.get("no_rebuy_after_sell", {})
        if rule.get("enabled", True) and code in self.sold_today:
            sold = self.sold_today[code]
            cooldown = rule.get("cooldown_minutes", 0)
            allow_profit = rule.get("allow_if_profitable", False)

            if cooldown == 0:
                name = stock_names.get(code, code)
                return False, f"당일 재매수 금지 ({name})"

            if allow_profit and sold["profitable"]:
                elapsed = (datetime.datetime.now() - sold["time"]).total_seconds() / 60
                if elapsed < cooldown:
                    remaining = int(cooldown - elapsed)
                    name = stock_names.get(code, code)
                    return False, f"쿨다운 대기 ({name}, {remaining}분 남음)"
            else:
                name = stock_names.get(code, code)
                return False, f"손실 매도 후 재매수 금지 ({name})"

        # 2. max_holdings 체크
        max_rule = trading_rules.get("max_holdings", {})
        if max_rule.get("enabled", False):
            max_count = max_rule.get("default_count", 5)
            if portfolio_size >= max_count:
                return False, f"최대 보유 종목 초과 ({portfolio_size}/{max_count})"

        return True, ""

    def record_sell(self, code, signal, realized_pnl, trading_rules, discord=None):
        """매도 후 리스크 상태 업데이트. 브레이크 발동 시 True 반환."""
        self.sold_today[code] = {
            "time": datetime.datetime.now(),
            "profitable": realized_pnl > 0,
        }
        self.daily_realized_pnl += realized_pnl

        if signal in ("SELL_STOP_LOSS", "SELL_HARD_STOP"):
            self.consecutive_sl_count += 1
            sl_rule = trading_rules.get("consecutive_sl_brake", {})
            max_consecutive = sl_rule.get("max_consecutive", 3)
            if sl_rule.get("enabled", False) and self.consecutive_sl_count >= max_consecutive:
                cooldown = sl_rule.get("cooldown_minutes", 30)
                self.sl_brake_until = datetime.datetime.now() + datetime.timedelta(minutes=cooldown)
                print(f"🛑 연속 {max_consecutive}회 손절 — {cooldown}분간 매매 중단 ({self.sl_brake_until.strftime('%H:%M')}까지)")
                if discord:
                    discord.send(
                        f"🛑 **연속 {max_consecutive}회 손절 브레이크 발동**\n"
                        f"{cooldown}분간 매매 중단 ({self.sl_brake_until.strftime('%H:%M')}까지)\n"
                        f"당일 누적손익: {self.daily_realized_pnl:+,.0f}원"
                    )
                self.consecutive_sl_count = 0
                return True
        elif signal == "SELL_TAKE_PROFIT":
            # 수익 실현만 연속SL 카운터 리셋 (SELL_AI, SELL_EOD는 유지)
            self.consecutive_sl_count = 0

        return False
