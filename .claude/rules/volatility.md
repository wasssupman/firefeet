---
globs:
  - core/execution/trader.py
  - core/execution/risk_guard.py
  - core/execution/portfolio_manager.py
  - run_firefeet.py
  - config/trading_settings.yaml
  - config/trading_rules.yaml
---

# Day-Trading Bot (Larry Williams 변동성 돌파, 당일 15:20 청산)

## 금지 패턴
- 오버나잇 보유 금지 — 모든 포지션 15:20 EOD 청산
- SwingTrader 오버라이드 로직 혼용 금지
- VWAP reversion/orderbook_pressure/tick_buffer: 스캘핑 전용

## 핵심 함수
- check_buy_signal(): 변동성 돌파 진입 (이 봇에서만 사용)
- should_sell(): EOD 15:20 강제 청산 포함 (이 봇에서만 사용)
- trader.py 변경 시 SwingTrader도 상속받으므로 양쪽 테스트 필수
