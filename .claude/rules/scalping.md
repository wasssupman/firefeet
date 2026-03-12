---
globs:
  - core/scalping/**
  - config/scalping_*
  - run_scalper.py
  - tests/*scalp*
---

# Scalping Bot (VWAP Deviation Reversion, 1.5초 루프)

## 금지 패턴 (386건 분석 검증, 2026-02-26)
- momentum_burst/micro_trend/volume_surge 시그널: 엣지 없음 → 폐기됨
- RegimeDetector momentum 레짐: no_trade 처리 (regime_detector.py:50)
- 재활성화 금지 — 50건+ 통계적 증명 없이 부활 불가
- check_buy_signal()/should_sell(): 변동성 돌파 전용, 스캘핑에서 사용 금지
- 추상화 레이어(이벤트 버스, 메시지 큐) 삽입 금지 (레이턴시)

## 활성 전략
- VWAP Deviation Reversion 단독
- 시그널: vwap_reversion(80w) + orderbook_pressure(20w)

## 설정 규칙
- Threshold 3곳 충돌: 전략 프로필 > 온도 오버라이드 > 글로벌 기본값
- TP ≤ 0.4% 금지 (수수료 0.21%)
