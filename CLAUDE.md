# Firefeet - 한국 주식 자동매매 시스템

KIS(한국투자증권) API로 실매매하는 한국 주식 자동매매 봇. 3개의 독립 봇이 각각 별도 프로세스로 실행된다.

## 봇 구조 (반드시 구분할 것)

| 봇 | 실행 | 클래스 | 전략 | 보유기간 |
|---|---|---|---|---|
| **데이트레이딩** | `run_firefeet.py` | `FirefeetTrader` (trader.py) | 변동성 돌파 (Larry Williams) | 당일 (15:20 EOD 청산) |
| **스윙 매매** | `run_ai_swing_bot.py` | `SwingTrader` (swing_trader.py) | 기계적 스윙 (스크리너+ATR) | 3~10일 오버나잇 |
| **스캘핑** | `run_scalper.py` | `ScalpEngine` (scalp_engine.py) | VWAP Deviation Reversion | 초~분 단위 |

**핵심 원칙**: 각 봇의 전략을 혼동하지 말 것.
- `check_buy_signal()` (변동성 돌파) → **데이트레이딩 전용**. 스윙에서 사용 금지.
- `should_sell()` (EOD 15:20 청산) → **데이트레이딩 전용**. 스윙은 오버나잇 보유.
- `SwingTrader`는 `FirefeetTrader`를 상속하지만 **진입/청산 로직을 완전 오버라이드**.
- `SwingTrader`의 `strategy` 객체는 ATR 계산/TP·SL 파라미터용이지 변동성 돌파용이 아님.

## 실행 방법

```bash
python3 run_ai_swing_bot.py           # 스윙 매매 (메인, 기계적 모드)
python3 run_ai_swing_bot.py --paper   # 페이퍼 트레이딩
python3 run_firefeet.py               # 데이트레이딩 (변동성 돌파)
python3 run_scalper.py                # 스캘핑 (PAPER)
python3 run_scalper.py --mode REAL    # 스캘핑 (REAL)
python3 run_deep_analysis.py          # AI 심층 분석
python3 run_report_bot.py             # 정기 리포트 (08:00~15:40)
python3 run_export.py macro|watchlist|all  # CLI 리포트
```

## 설계 제약 조건

이 시스템은 실제 돈이 오가는 트레이딩 봇이다. 구조 변경 시 반드시 검증할 것:

- **스캘핑 레이턴시**: 1.5초 루프에 추상화 레이어(이벤트 버스, 메시지 큐) 삽입 금지. 시그널→판단→주문은 최소 hop 직결.
- **다중 프로세스 현실**: 스윙/스캘핑은 별도 PID. in-memory 싱글턴 공유 불가. 프로세스 간 상태 공유 시 Redis 또는 파일 락.
- **주문 실패 시 롤백**: 부분 체결, API 타임아웃, 증거금 부족은 일상. 상태 불일치 복구 경로 필수 설계.
- **용어 규율**: "Agent"는 자율적 의사결정 컴포넌트(AISwingAgent)에만 사용. 캐시/타이머/데이터 제공은 Service 또는 Manager.
- **범용 패턴 경계**: 이벤트 버스, MSA, 액터 모델 등을 트레이딩 맥락 없이 적용하지 말 것. "이게 스캘핑 루프에 몇 ms 추가하나?" 먼저 질문.

## 개발 컨벤션

- **언어**: 코드는 영문, 주석/로그/리포트는 한국어
- **종목 코드**: 6자리 문자열 (`"005930"`)
- **시간**: KST 기준, `"%H%M"` 포맷 (예: `"1520"`)
- **에러 처리**: 모듈별 try/except로 독립 실행. 하나 실패해도 나머지 계속 동작
- **설정 변경**: YAML 파일만 수정하면 런타임에 반영 (trader는 매 루프 reload)
- **세션 핸드오프**: 봇 코드 수정 세션 종료 시, MEMORY.md의 해당 봇 섹션을 업데이트할 것. 이전 세션 결정을 뒤집는 변경은 데이터 근거 없이 금지.

## 테스트

```bash
pytest tests/ -v                                    # 전체 (316 cases)
pytest tests/test_strategy.py tests/test_trader.py -v   # 스윙 전략 (62 cases)
pytest tests/test_scalp_*.py -v                     # 스캘핑
pytest tests/test_web_api.py -v                     # 웹 API (17 cases)
```

소스→테스트 매핑:
`technical.py` → `test_strategy.py`, `trader.py` → `test_trader.py`, `ai_swing_agent.py` → `test_ai_swing_agent.py`,
`scalp_strategy.py` → `test_scalp_strategy.py`, `strategy_selector.py` → `test_scalp_strategy_selector.py`,
`risk_manager.py` → `test_scalp_risk_manager.py`, `trade_logger.py` → `test_scalp_trade_logger.py`,
`scalp_engine.py` → `integration/test_scalp_engine_flow.py`, `config/scalping_*.yaml` → `test_scalp_config_validation.py`,
`web/backend/main.py` → `test_web_api.py`

## 커스텀 에이전트 & 스킬

에이전트 (`.claude/agents/` — 자율 판단):
- `/agents/param-tune` — 전략 파라미터 튜닝 (데이터 기반 제안, 3중 충돌 방지)
- `/agents/market-brief` — 장전 시황 브리핑 (온도 + 매크로 + 전략 프로필)
- `/agents/incident` — 이상 거래 원인 추적 (파이프라인 타임라인 재구성)
- `/agents/scalping-analyzer` — 스캘핑 로그 분석 (tick-level, regime 분포, 시그널 적중률)
- `/agents/scalping-strategist` — 스캘핑 전략 튜닝 (VWAP Reversion 파라미터, 3중 충돌 검증)
- `/agents/swing-analyzer` — 스윙 거래 로그 분석 (보유기간, 스크리너 정확도)
- `/agents/swing-strategist` — 스윙 전략 분석 (ATR, 온도 프로필)
- `/agents/volatility-analyzer` — 변동성 돌파 로그 분석 (k값별 성공률, EOD 타이밍)
- `/agents/volatility-strategist` — 변동성 돌파 전략 분석 (k값, 리스크 한도)

스킬 (`.claude/skills/` — 스크립트 기반 정형 작업):
- `trade-review` — 거래 성과 분석 (`scripts/analyze_trades.py`)
- `config-check` — 설정 정합성 검증 (`scripts/validate_config.py`)
- `scalping-context` / `swing-context` / `volatility-context` — 봇별 세션 컨텍스트 로딩
- `scalping-review` / `swing-review` / `volatility-review` — 봇별 거래 리뷰
- `scalping-strategy` / `swing-strategy` / `volatility-strategy` — 봇별 전략 분석

## 알려진 이슈

- MarketWatch 스크래핑이 간헐적으로 403 반환 → Google News RSS fallback 사용
- Reddit API 현재 미연동 (credentials 문제)
- econ_module의 `parse_number()` — 일부 경제 지표 서프라이즈 계산이 부정확할 수 있음
