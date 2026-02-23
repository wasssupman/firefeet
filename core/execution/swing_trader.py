import copy
import time
import datetime
import yaml
import os
import logging
from core.providers.kis_api import OrderType
from core.trade_logger import TradeLogger
from core.execution.trader import FirefeetTrader

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
        
        # Override logger format if needed
        self.trade_logger = TradeLogger("trades_swing.csv")

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
            self._process_ai_buy(code, name, time_str, ai_data, current_price)

    def _process_ai_buy(self, code, name, time_str, ai_data, current_price):
        """AI 판단에 따른 매수 처리"""
        # 1. 예산 및 조건 확인 (기준 상속 로직 재사용)
        can_buy, reason = self._can_buy(code)
        if not can_buy:
            return
            
        # 2. AI 판단 요청
        decision = self.ai_agent.analyze_trading_opportunity(code, name, ai_data)
        
        # 3. 매수 조건 필터링
        if decision.get('decision') != 'BUY':
            return
            
        confidence = decision.get('confidence', 0)
        min_confidence = self.trading_rules.get("ai_min_buy_confidence", 80)
        
        if confidence < min_confidence:
            msg = f"[{name}] 매수 보류: AI 확신도({confidence})가 기준치({min_confidence}) 미달"
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
            self.trade_logger.log_trade(
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "BUY_AI", code, name, current_price, qty,
                f"AI_Buy(Conf:{confidence}, Type:{decision.get('strategy_type')})"
            )
            if self.discord:
                self.discord.send_trade_alert(
                    f"🟢 **[AI 스윙 매수] {name} ({code})**\n"
                    f"- **단가**: {current_price:,}원\n"
                    f"- **수량**: {qty}주\n"
                    f"- **전략**: {decision.get('strategy_type')}\n"
                    f"- **목표가/손절가**: {decision.get('target_price', 0):,}원 / {decision.get('stop_loss', 0):,}원\n"
                    f"- **사유**: {decision.get('reasoning')}"
                )

    def _process_ai_sell(self, code, name, time_str, ai_data, current_price, held_qty):
        """AI 판단에 따른 매도 처리"""
        # 포트폴리오에서 평단가 가져오기
        avg_price = self.portfolio.get(code, {}).get('buy_price', 0)
                
        if avg_price <= 0:
            return
            
        # 1. 하드 손절 로직 (AI 판단 전 기계적 보호)
        profit_rate = ((current_price - avg_price) / avg_price) * 100
        hard_stop_loss = self.trading_rules.get("hard_stop_loss_pct", -7.0)
        
        if profit_rate <= hard_stop_loss:
            self.logger.warning(f"[{name}] 하드 손절 도달 ({profit_rate:.2f}%). 전량 매도합니다.")
            self._execute_sell(code, name, held_qty, current_price, "SELL_HARD_STOP", f"수익률: {profit_rate:.2f}%")
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
            self.trade_logger.log_trade(
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                trade_type, code, name, current_price, qty, reason
            )
            if self.discord:
                self.discord.send_trade_alert(
                    f"🔴 **[{trade_type}] {name} ({code})**\n"
                    f"- **단가**: {current_price:,}원\n"
                    f"- **수량**: {qty}주\n"
                    f"- **사유**: {reason}"
                )
