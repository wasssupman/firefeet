import time
import datetime
import os
import logging
from core.providers.kis_api import OrderType
from core.trade_logger import TradeLogger
from core.execution.trader import FirefeetTrader
from core.db.writer import BackgroundWriter

class SwingTrader(FirefeetTrader):
    """
    AI 결정을 반영하여 당일 자동 청산 없이 중단기 스윙 포지션을 관리하는 트레이더.
    - AI Agent의 BUY/SELL/HOLD 결정을 포지션 진입/청산에 반영
    - 오버나잇 (Overnight) 포지션 유지
    """
    def __init__(self, manager, ai_agent, strategy=None, discord_client=None, settings_path="config/trading_settings.yaml"):
        super().__init__(manager, strategy, discord_client, settings_path)
        self.ai_agent = ai_agent
        self.logger = logging.getLogger("SwingTrader")

        # AI 결정 캐시: WAIT/HOLD 판단 시 재호출 방지
        self._ai_decision_cache = {}  # {code: {"decision": str, "timestamp": float}}
        self._ai_cache_ttl = 1800  # 30분 (초)

        # Override trade logger for swing strategy
        self.trade_logger = TradeLogger(strategy="swing")
        self.db_writer = BackgroundWriter()

        # Cross-bot position lock
        from core.db.position_registry import PositionRegistry
        self.position_registry = PositionRegistry()

    def process_stock_with_ai(self, code, time_str, data_provider_fn):
        """
        AI 판단을 받아 특정 종목의 매수/매도를 처리합니다.
        
        Args:
            code: 종목코드
            time_str: "HHMMSS"
            data_provider_fn: data dict 반환 콜백 (ohlc, supply, news, temp 등 포함)
        """
        name = self.stock_names.get(code, "Unknown")
        held_qty = 0
        if code in self.portfolio:
            held_qty = self.portfolio[code].get('qty', 0)
        try:
            ai_data = data_provider_fn(code)
            current_price = ai_data.get('current_data', {}).get('price', 0)
        except Exception as e:
            self.logger.error(f"[{code}] 데이터 수집 실패: {e}")
            return
            
        if current_price <= 0:
            return
            
        # 보유 중인 종목 매도 로직 (AI 판단)
        if held_qty > 0:
            self._process_ai_sell(code, name, time_str, ai_data, current_price, held_qty)
        # 미보유 종목 매수 로직 (AI 판단)
        else:
            # AI 결정 캐시: WAIT/HOLD가 TTL 내면 재호출 스킵
            cached = self._ai_decision_cache.get(code)
            if cached and (time.time() - cached["timestamp"] < self._ai_cache_ttl):
                self.logger.debug(
                    f"[{name}({code})] AI 캐시 히트: {cached['decision']} "
                    f"({int((time.time() - cached['timestamp']) / 60)}분 전)"
                )
                return
            self._process_ai_buy(code, name, time_str, ai_data, current_price)

    def _process_ai_buy(self, code, name, time_str, ai_data, current_price):
        """AI 판단에 따른 매수 처리"""
        # 1. 예산 및 조건 확인 (기준 상속 로직 재사용)
        can_buy, reason = self._can_buy(code)
        if not can_buy:
            self.logger.debug(f"[{name}({code})] 매수 차단: {reason}")
            return

        # Cross-bot position lock
        if self.position_registry.is_held_by_other(code, "swing"):
            self.logger.debug(f"[{name}({code})] 다른 봇이 보유 중 — 매수 스킵")
            return

        # 1-1. EXPANSION 게이트: 변동성 돌파 미충족 시 AI 호출 생략
        if self.strategy is not None:
            ohlc = ai_data.get('ohlc')
            if ohlc is not None:
                signal = self.strategy.check_buy_signal(code, ohlc, current_price)
                if not signal or signal.get('signal') != 'BUY':
                    self.logger.debug(f"[{name}({code})] 변동성 돌파 미충족 — AI 호출 생략")
                    return

        # 2. AI 판단 요청
        decision = self.ai_agent.analyze_trading_opportunity(code, name, ai_data)

        # 3. 매수 조건 필터링
        ai_decision = decision.get('decision', 'N/A')
        if ai_decision != 'BUY':
            self._ai_decision_cache[code] = {"decision": ai_decision, "timestamp": time.time()}
            self.logger.info(
                f"[{name}({code})] AI 판단: {ai_decision} "
                f"(확신도: {decision.get('confidence', 0)}) — "
                f"{decision.get('reasoning', 'no reason')[:120]} [캐시 {self._ai_cache_ttl // 60}분]"
            )
            return

        confidence = decision.get('confidence', 0)
        min_confidence = self.trading_rules.get("ai_min_buy_confidence", 80)

        if confidence < min_confidence:
            self._ai_decision_cache[code] = {"decision": f"LOW_CONF({confidence})", "timestamp": time.time()}
            msg = f"[{name}] 매수 보류: AI 확신도({confidence})가 기준치({min_confidence}) 미달 [캐시 {self._ai_cache_ttl // 60}분]"
            self.logger.info(msg)
            return
            
        # 4. 수량 계산 (분할 매수 고려)
        target_allocation = self.trading_rules.get("target_allocation_per_stock", 1000000)
        budget = min(self.manager.get_balance()['available_cash'], target_allocation)
        qty = int(budget // current_price)
        
        if qty <= 0:
            return
            
        # 5. 주문 실행
        self.logger.info(f"[{name}] AI 매수 결정 (확신도: {confidence}): {decision.get('reasoning')}")
        result = self.manager.place_order(code, qty, 0, OrderType.BUY)

        if result and (not isinstance(result, dict) or result.get('rt_cd') == '0'):
            order_no = result if isinstance(result, str) else result.get('odno', '')
            buy_info = self.trade_logger.log_buy(code, name, qty, current_price)
            self.db_writer.log_decision({
                "timestamp": datetime.datetime.now().isoformat(),
                "bot_type": "swing",
                "code": code,
                "action": "BUY",
                "status": "PENDING",
                "order_no": order_no,
                "requested_qty": qty,
                "requested_price": current_price,
                "ai_decision": decision.get("decision"),
                "ai_confidence": confidence,
                "ai_reasoning": decision.get("reasoning", "")[:500],
                "strategy_profile": decision.get("strategy_type"),
            })
            self.db_writer.update_status(order_no, "FILLED",
                filled_qty=qty, filled_price=current_price)
            self.position_registry.register(code, "swing", qty, current_price)
            if self.discord:
                self.discord.send(
                    f"🟢 **[AI 스윙 매수] {name} ({code})**\n"
                    f"- **단가**: {current_price:,}원\n"
                    f"- **수량**: {qty}주\n"
                    f"- **전략**: {decision.get('strategy_type')}\n"
                    f"- **목표가/손절가**: {decision.get('target_price', 0):,}원 / {decision.get('stop_loss', 0):,}원\n"
                    f"- **사유**: {decision.get('reasoning')}\n"
                    f"- **총비용**: {buy_info['net_amount']:,}원 (수수료 {buy_info['fee']:,}원)"
                )

    def _process_ai_sell(self, code, name, time_str, ai_data, current_price, held_qty):
        """AI 판단에 따른 매도 처리"""
        # 포트폴리오에서 평단가 가져오기
        avg_price = self.portfolio.get(code, {}).get('buy_price', 0)
                
        if avg_price <= 0:
            self.logger.warning(f"[{name}({code})] avg_price={avg_price}, 포지션 데이터 이상. 수동 확인 필요.")
            return
            
        # 1. 하드 손절 로직 (AI 판단 전 기계적 보호, ATR 기반)
        profit_rate = ((current_price - avg_price) / avg_price) * 100
        hard_stop_loss = self.trading_rules.get("hard_stop_loss_pct", -7.0)

        # ATR 기반 구조적 손절 (고정 % = floor, ATR이 더 넓으면 ATR 사용)
        effective_hard_sl = hard_stop_loss
        ohlc = ai_data.get('ohlc')
        if ohlc is not None and hasattr(ohlc, 'iloc') and len(ohlc) >= 15:
            from core.analysis.technical import VolatilityBreakoutStrategy
            atr14 = VolatilityBreakoutStrategy.calculate_atr(ohlc, period=14)
            if atr14 and atr14 > 0 and avg_price > 0:
                atr_multiplier = self.trading_rules.get("hard_sl_atr_multiplier", 3.0)
                atr_sl_pct = -(atr14 * atr_multiplier) / avg_price * 100
                effective_hard_sl = min(hard_stop_loss, atr_sl_pct)  # 더 넓은 쪽 사용

        if profit_rate <= effective_hard_sl:
            sl_info = f"수익률: {profit_rate:.2f}% (한도: {effective_hard_sl:.1f}%)"
            self.logger.warning(f"[{name}] 하드 손절 도달 ({profit_rate:.2f}%). 전량 매도합니다.")
            self._execute_sell(code, name, held_qty, current_price, "SELL_HARD_STOP", sl_info)
            return

        # 2. AI 판단 요청
        decision = self.ai_agent.analyze_trading_opportunity(code, name, ai_data)
        
        if decision.get('decision') == 'SELL':
            reason = decision.get('reasoning', 'AI 매도 시그널')
            self._execute_sell(code, name, held_qty, current_price, "SELL_AI", reason)
            
    def _execute_sell(self, code, name, qty, current_price, trade_type, reason):
        """실제 매도 API 호출 및 로깅"""
        result = self.manager.place_order(code, qty, 0, OrderType.SELL)

        if result and (not isinstance(result, dict) or result.get('rt_cd') == '0'):
            order_no = result if isinstance(result, str) else result.get('odno', '')
            buy_price = self.portfolio.get(code, {}).get('buy_price', current_price)
            sell_info = self.trade_logger.log_sell(code, name, qty, current_price, buy_price, trade_type)
            self.db_writer.log_decision({
                "timestamp": datetime.datetime.now().isoformat(),
                "bot_type": "swing",
                "code": code,
                "action": "SELL",
                "status": "PENDING",
                "order_no": order_no,
                "requested_qty": qty,
                "requested_price": current_price,
                "exit_reason": trade_type,
                "ai_reasoning": reason[:500] if reason else "",
            })
            self.db_writer.update_status(order_no, "FILLED",
                filled_qty=qty, filled_price=current_price,
                realized_pnl=sell_info["realized_pnl"],
                pnl_rate=sell_info["pnl_rate"])
            if self.discord:
                self.discord.send(
                    f"🔴 **[{trade_type}] {name} ({code})**\n"
                    f"- **단가**: {current_price:,}원\n"
                    f"- **수량**: {qty}주\n"
                    f"- **실현손익**: {sell_info['realized_pnl']:+,}원 ({sell_info['pnl_rate']:+.2f}%)\n"
                    f"- **사유**: {reason}"
                )
            # 매도 후 상태 추적 (RiskGuard 위임)
            self._risk_guard.record_sell(
                code, trade_type, sell_info['realized_pnl'],
                self.trading_rules, self.discord
            )
            self.position_registry.remove(code, "swing")
            del self.portfolio[code]
