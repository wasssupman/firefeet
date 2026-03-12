---
globs:
  - core/providers/kis_api.py
  - core/trade_logger.py
  - core/technical/**
  - core/kis_websocket.py
  - core/db/**
---

# 공유 모듈 — 변경 시 3봇 전체 영향

- 봇별 분기 로직 삽입 금지 (봇 독립성 유지)
- 변경 후 전체 테스트: pytest tests/ -v
- PositionRegistry (position_registry.py): 봇 간 동일 종목 동시 보유 방지. 우회 금지.
- kis_websocket.py 필드: FIELD_TICK_DIRECTION=21 (체결구분), fields[15]=매도체결건수
