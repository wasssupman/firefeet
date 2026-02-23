import yaml
import os
import time
import datetime

class RiskManager:
    """스캘핑 리스크 관리 + 서킷브레이커"""

    def __init__(self, settings_path="config/scalping_settings.yaml",
                 rules_path="config/scalping_rules.yaml", mode="PAPER"):
        self.settings = self._load_yaml(settings_path)
        self.mode = mode
        self.rules_path = rules_path
        self.rules = self._load_and_resolve(rules_path)

        # 일일 추적
        self.daily_pnl = 0           # 일일 실현손익
        self.daily_trade_count = 0   # 일일 거래 횟수
        self.consecutive_losses = 0  # 연속 손실 횟수
        self.last_trade_time = 0     # 마지막 거래 시각

        # 서킷브레이커
        self.circuit_broken = False
        self.circuit_break_time = 0

        # 현재 온도
        self.temperature_level = "NEUTRAL"
        self._temp_overrides = {}

    def _load_yaml(self, path):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[RiskManager] Config load failed ({path}): {e}")
        return {}

    def _load_and_resolve(self, path):
        """YAML 로드 후 mode 섹션을 최상위로 머지"""
        raw = self._load_yaml(path)
        mode_rules = raw.get("mode", {}).get(self.mode.lower(), {})
        resolved = {}
        for key in ("per_trade", "daily_limits", "time_restrictions"):
            resolved[key] = mode_rules.get(key, raw.get(key, {}))
        # 공통 섹션 유지
        resolved["temperature_overrides"] = raw.get("temperature_overrides", {})
        resolved["unfilled_order"] = raw.get("unfilled_order", {})
        return resolved

    def reload_rules(self):
        """규칙 리로드"""
        self.rules = self._load_and_resolve(self.rules_path)

    # ── Pre-trade Checks ──────────────────────────

    def can_enter(self, code, position_value, current_positions):
        """
        신규 진입 가능 여부 체크.
        Returns: (allowed: bool, reason: str)
        """
        # 1. 서킷브레이커 체크
        if self.circuit_broken:
            cooldown = self.rules.get("daily_limits", {}).get("cooldown_after_circuit", 600)
            elapsed = time.time() - self.circuit_break_time
            if elapsed < cooldown:
                remaining = int(cooldown - elapsed)
                return False, f"서킷브레이커 쿨다운 ({remaining}초 남음)"
            else:
                self.circuit_broken = False
                print("[RiskManager] 서킷브레이커 쿨다운 해제")

        # 2. 시간 제한 체크
        time_ok, time_reason = self._check_time_restrictions()
        if not time_ok:
            return False, time_reason

        # 3. 일일 손실 한도 체크
        daily = self.rules.get("daily_limits", {})
        budget = self.settings.get("scalping_budget", 500000)

        max_daily_loss = daily.get("max_daily_loss", 30000)
        if self.daily_pnl <= -max_daily_loss:
            return False, f"일일 손실 한도 초과 ({self.daily_pnl:+,}원 / -{max_daily_loss:,}원)"

        max_daily_pct = daily.get("max_daily_loss_pct", 3.0)
        if budget > 0 and (abs(self.daily_pnl) / budget * 100) >= max_daily_pct and self.daily_pnl < 0:
            return False, f"일일 손실률 한도 ({abs(self.daily_pnl)/budget*100:.1f}% / {max_daily_pct}%)"

        # 4. 일일 거래 횟수 체크
        max_trades = daily.get("max_daily_trades", 50)
        if self.daily_trade_count >= max_trades:
            return False, f"일일 거래 횟수 한도 ({self.daily_trade_count}/{max_trades})"

        # 5. 포지션 수 제한
        max_positions = self._get_max_positions()
        if len(current_positions) >= max_positions:
            return False, f"최대 포지션 초과 ({len(current_positions)}/{max_positions})"

        # 6. 건당 포지션 한도
        per_trade = self.rules.get("per_trade", {})
        max_pos_val = per_trade.get("max_position_value", 200000)
        if position_value > max_pos_val:
            return False, f"건당 포지션 한도 초과 ({position_value:,} / {max_pos_val:,}원)"

        return True, ""

    def _check_time_restrictions(self):
        """시간 제한 체크"""
        time_rules = self.rules.get("time_restrictions", {})
        now = datetime.datetime.now()
        current_time = now.strftime("%H%M")

        no_before = time_rules.get("no_entry_before", "0910")
        no_after = time_rules.get("no_entry_after", "1510")

        if current_time < no_before:
            return False, f"장 초반 제한 ({no_before} 이전)"
        if current_time >= no_after:
            return False, f"마감 전 진입 금지 ({no_after} 이후)"

        return True, ""

    def should_force_exit(self):
        """전체 청산 필요 여부"""
        time_rules = self.rules.get("time_restrictions", {})
        force_exit_by = time_rules.get("force_exit_by", "1515")
        now = datetime.datetime.now().strftime("%H%M")
        return now >= force_exit_by

    def _get_max_positions(self):
        """온도 기반 최대 포지션 수"""
        overrides = self.rules.get("temperature_overrides", {}).get(self.temperature_level, {})
        return overrides.get("max_positions",
                             self.settings.get("max_simultaneous_positions", 3))

    # ── Post-trade Updates ──────────────────────────

    def record_trade(self, pnl):
        """거래 결과 기록"""
        self.daily_pnl += pnl
        self.daily_trade_count += 1
        self.last_trade_time = time.time()

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        # 연속 손실 서킷브레이커
        max_consec = self.rules.get("daily_limits", {}).get("max_consecutive_losses", 5)
        if self.consecutive_losses >= max_consec:
            self._trigger_circuit_breaker(f"연속 {self.consecutive_losses}회 손실")

    def _trigger_circuit_breaker(self, reason):
        """서킷브레이커 발동"""
        self.circuit_broken = True
        self.circuit_break_time = time.time()
        cooldown = self.rules.get("daily_limits", {}).get("cooldown_after_circuit", 600)
        print(f"🚨 [RiskManager] 서킷브레이커 발동: {reason} | 쿨다운 {cooldown}초")

    # ── Position Risk ──────────────────────────

    def check_position_risk(self, buy_price, current_price, qty):
        """포지션 리스크 체크 — 건당 최대 손실 초과 시 강제 청산 신호"""
        per_trade = self.rules.get("per_trade", {})

        # 금액 기준 손실 체크
        unrealized_pnl = (current_price - buy_price) * qty
        max_loss_amount = per_trade.get("max_loss_amount", 5000)
        if unrealized_pnl <= -max_loss_amount:
            return True, f"건당 손실한도({unrealized_pnl:+,}원 / -{max_loss_amount:,}원)"

        # 비율 기준 손실 체크
        if buy_price > 0:
            loss_pct = (current_price - buy_price) / buy_price * 100
            max_loss_pct = per_trade.get("max_loss_pct", 0.3)
            if loss_pct <= -max_loss_pct:
                return True, f"건당 손실률({loss_pct:+.2f}% / -{max_loss_pct}%)"

        return False, ""

    # ── Temperature ──────────────────────────

    def apply_temperature(self, temp_result):
        """온도 결과 적용"""
        self.temperature_level = temp_result.get("level", "NEUTRAL")
        print(f"[RiskManager] 온도 적용: {self.temperature_level}")

    # ── Session Management ──────────────────────────

    def reset_daily(self):
        """일일 카운터 리셋"""
        self.daily_pnl = 0
        self.daily_trade_count = 0
        self.consecutive_losses = 0
        self.circuit_broken = False
        self.circuit_break_time = 0
        print("[RiskManager] 일일 리스크 카운터 리셋")

    def get_daily_summary(self):
        """일일 리스크 요약"""
        return {
            "daily_pnl": self.daily_pnl,
            "trade_count": self.daily_trade_count,
            "consecutive_losses": self.consecutive_losses,
            "circuit_broken": self.circuit_broken,
            "temperature": self.temperature_level,
            "max_positions": self._get_max_positions(),
        }
