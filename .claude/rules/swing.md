---
globs:
  - core/execution/swing_trader.py
  - core/analysis/ai_swing_agent.py
  - run_ai_swing_bot.py
  - config/temperature_config.yaml
  - tests/test_strategy.py
  - tests/test_trader.py
---

# Swing Bot (기계적 스윙, 3~10일 오버나잇)

## 금지 패턴
- check_buy_signal(): 변동성 돌파 전용, 스윙 진입에 사용 금지
- should_sell() EOD 15:20 청산: 데이트레이딩 전용, 스윙은 오버나잇 보유
- SwingTrader는 FirefeetTrader 상속하나 진입/청산 로직 완전 오버라이드
- ScalpSignals/ScalpEngine/RegimeDetector: 스캘핑 전용
- AI 모드 현재 비활성 (c4c10c7, 2026-03-11). 재활성화 시 명시적 요청 필요

## SwingTrader.strategy
- ATR 계산/TP·SL 파라미터용이지 변동성 돌파 시그널용이 아님
