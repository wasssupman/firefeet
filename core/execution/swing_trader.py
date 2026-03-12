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
    def __init__(self, manager, ai_agent=None, strategy=None, discord_client=None,
                 settings_path="config/trading_settings.yaml", use_ai=True):
        super().__init__(manager, strategy, discord_client, settings_path)
        self.ai_agent = ai_agent
        self.use_ai = use_ai and (ai_agent is not None)
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

    def _effective_tp(self, atr14, avg_price):
        """ATR 기반 실효 TP% 계산 (고정 % = floor)."""
        if self.strategy is None:
            return 4.0
        base_tp = self.strategy.take_profit
        if atr14 and atr14 > 0 and avg_price > 0:
            atr_tp_pct = (atr14 * self.strategy.atr_tp_multiplier) / avg_price * 100
            return max(base_tp, atr_tp_pct)
        return base_tp

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
            if not ai_data:
                return
            current_price = (ai_data.get('current_data') or {}).get('price', 0)
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
            # 동적 TTL: 장 초반(09:00~10:00) 15분, 이후 30분
            effective_ttl = 900 if "090000" <= time_str < "100000" else self._ai_cache_ttl
            cached = self._ai_decision_cache.get(code)
            if cached and (time.time() - cached["timestamp"] < effective_ttl):
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

        # 1-1. 수축비율(contraction_ratio) 게이트: 이미 확장 중이면 과열 판단
        if self.strategy is not None:
            ohlc = ai_data.get('ohlc')
            if ohlc is not None:
                contraction_ratio = self.strategy.get_contraction_ratio(ohlc)
                if contraction_ratio is not None and contraction_ratio > 1.2:
                    self.logger.info(
                        f"[{name}({code})] 수축비율 과열({contraction_ratio:.2f} > 1.2) — 매수 생략"
                    )
                    return

        # 2. 매수 판단: AI 모드 vs 기계적 모드
        if self.use_ai:
            decision = self.ai_agent.analyze_trading_opportunity(code, name, ai_data)

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
        else:
            # 기계적 모드: strategy 게이트를 이미 통과했으므로 (돌파+수축 OK) 매수 진행
            # screener_score가 min_screen_score 이상인지 확인
            screener_score = ai_data.get('screener_score', 0)
            min_score = getattr(self.strategy, 'min_screen_score', 30) if self.strategy else 30
            if screener_score < min_score:
                self.logger.debug(f"[{name}({code})] 스크리너 점수 미달 ({screener_score} < {min_score})")
                return
            decision = {
                "decision": "MECHANICAL_BUY",
                "stop_loss": 0,  # ATR fallback 사용
                "target_price": 0,
                "strategy_type": "MECHANICAL_SWING",
                "reasoning": f"기계적 매수 (screener={screener_score}, 돌파+수축 통과)",
                "confidence": screener_score,
            }
            self.logger.info(f"[{name}({code})] 기계적 매수 결정 (스크리너: {screener_score})")

        # 4. 리스크 기반 수량 계산 (공통 메서드 사용)
        # Stop distance: AI 제시 stop_loss 또는 ATR 기반
        ai_stop = float(decision.get('stop_loss', 0))
        if ai_stop > 0 and ai_stop < current_price:
            stop_distance = current_price - ai_stop
        else:
            ohlc = ai_data.get('ohlc')
            atr14 = self.strategy.calculate_atr(ohlc, period=14) if (self.strategy and ohlc is not None) else None
            if atr14 and atr14 > 0:
                atr_multiplier = self.trading_rules.get("hard_sl_atr_multiplier", 3.0)
                stop_distance = atr14 * atr_multiplier
            else:
                hard_sl_pct = abs(self.trading_rules.get("hard_stop_loss_pct", -7.0))
                stop_distance = current_price * hard_sl_pct / 100
        if stop_distance <= 0:
            stop_distance = current_price * 0.07  # fallback 7%

        available_cash = self.manager.get_balance().get('deposit', 0)
        qty = self._size_position(current_price, stop_distance, available_cash, risk_pct_default=2.0)

        if qty <= 0:
            return

        total_capital = self.settings.get("total_budget", 1000000)
        risk_amount = total_capital * (self.settings.get("risk_per_trade_pct", 2.0) / 100)
        self.logger.info(
            f"[{name}] 사이징: risk={risk_amount:,.0f}원, SL거리={stop_distance:,.0f}원, "
            f"수량={qty}주, 금액={qty * current_price:,.0f}원"
        )
            
        # 5. 주문 실행
        confidence = decision.get('confidence', 0)
        self.logger.info(f"[{name}] 매수 결정 (확신도: {confidence}): {decision.get('reasoning')}")
        result = self.manager.place_order(code, qty, 0, OrderType.BUY)

        if result and (not isinstance(result, dict) or result.get('rt_cd') == '0'):
            order_no = result if isinstance(result, str) else result.get('odno', '')

            # TODO: 체결 확인 로직 — get_order_status()는 일자별 전체 조회만 지원.
            #       건별 체결 확인 API(get_order_detail(order_no)) 추가 후
            #       filled_qty/filled_price를 실제 값으로 대체 필요.
            filled_qty = qty
            filled_price = current_price

            buy_info = self.trade_logger.log_buy(code, name, filled_qty, filled_price)
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
                filled_qty=filled_qty, filled_price=filled_price)
            self.position_registry.register(code, "swing", filled_qty, filled_price)
            # 즉시 portfolio에 기록 (다음 루프 중복 매수 방지)
            self.portfolio[code] = {
                "qty": filled_qty,
                "orderable_qty": 0,
                "buy_price": filled_price,
                "buy_timestamp": time.time(),
                "unconfirmed": True,
            }
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
        atr14 = None
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

        # 1-1. ATR 기반 기계적 익절 게이트 (AI 호출 전 온도 연동)
        if self.strategy is not None:
            effective_tp = self._effective_tp(atr14, avg_price)
            if profit_rate >= effective_tp:
                tp_info = f"수익률: {profit_rate:.2f}% (목표: {effective_tp:.1f}%)"
                self.logger.info(f"[{name}] 기계적 익절 도달 ({profit_rate:.2f}%). 전량 매도합니다.")
                self._execute_sell(code, name, held_qty, current_price, "SELL_TAKE_PROFIT", tp_info)
                return

        # 1-2. 장 시작 수익률 체크 (오버나잇 갭 대응, 09:00~09:30)
        # 장 시작에는 TP의 60%만으로 익절 (갭업 수익 반납 방지)
        time_hhmm = time_str[:4]
        if "0900" <= time_hhmm <= "0930":
            if self.strategy is not None:
                base_tp = self._effective_tp(atr14, avg_price)
                opening_tp = base_tp * 0.6  # 장 시작 할인: 정규 TP의 60%
                if profit_rate >= opening_tp:
                    tp_info = f"장 시작 익절: {profit_rate:.2f}% (조기목표: {opening_tp:.1f}%, 정규: {base_tp:.1f}%)"
                    self.logger.info(f"[{name}] 장 시작 갭업 익절 ({profit_rate:.2f}%). 전량 매도합니다.")
                    self._execute_sell(code, name, held_qty, current_price, "SELL_OPENING_TP", tp_info)
                    return

        # 2. 매도 판단: AI 모드 vs 기계적 모드
        if self.use_ai:
            decision = self.ai_agent.analyze_trading_opportunity(code, name, ai_data)
            if decision.get('decision') == 'SELL':
                reason = decision.get('reasoning', 'AI 매도 시그널')
                self._execute_sell(code, name, held_qty, current_price, "SELL_AI", reason)
        else:
            # 기계적 모드: Trailing Stop 기반 매도
            # 포지션별 고점 추적 (portfolio에 저장)
            pos = self.portfolio.get(code, {})
            high_price = pos.get('high_price', avg_price)
            if current_price > high_price:
                high_price = current_price
                self.portfolio[code]['high_price'] = high_price

            # ATR trailing 또는 고정 % trailing fallback
            if atr14 and atr14 > 0:
                trailing_distance = atr14 * 1.5
            else:
                # ATR 없을 때 고정 3% trailing (fallback)
                trailing_distance = avg_price * 0.03

            trailing_sl = high_price - trailing_distance

            # trailing SL은 최소한 본전 이상일 때만 작동 (수익 보호 목적)
            if high_price > avg_price * 1.02 and current_price <= trailing_sl:
                reason = (f"Trailing Stop: 고점 {high_price:,}원 → 현재 {current_price:,}원 "
                          f"(거리={trailing_distance:,.0f}원, 수익률 {profit_rate:+.2f}%)")
                self.logger.info(f"[{name}] {reason}")
                self._execute_sell(code, name, held_qty, current_price, "SELL_TRAILING_STOP", reason)
                return

            # 보유기간 기반 청산: 7일 경과 + 수익률 < 1%
            buy_timestamp = self.portfolio.get(code, {}).get('buy_timestamp')
            if buy_timestamp:
                days_held = (time.time() - buy_timestamp) / 86400
                if days_held >= 7 and profit_rate < 1.0:
                    reason = f"보유기간 초과: {days_held:.1f}일 보유, 수익률 {profit_rate:+.2f}% (기준: 7일, +1%)"
                    self.logger.info(f"[{name}] {reason}")
                    self._execute_sell(code, name, held_qty, current_price, "SELL_TIME_EXIT", reason)
            
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
