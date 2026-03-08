# Firefeet

한국 주식 자동매매 시스템. KIS(한국투자증권) API 기반 실매매 봇으로, 글로벌 매크로 + 뉴스 감성 + 경제 지표를 종합한 **시장 온도**로 전략 파라미터를 동적 조절한다.

## 전략

| 봇 | 설명 | 실행 |
|---|---|---|
| AI Swing | Dual-LLM (Analyst→Executor→Vision) + ATR 기반 구조적 SL/TP | `python3 run_ai_swing_bot.py` |
| Day Trading | Larry Williams 변동성 돌파 전략 | `python3 run_firefeet.py` |
| Scalping | 5시그널 복합 스코어 + 9단계 청산 (1.5초 루프) | `python3 run_scalper.py` |

## 핵심 구조

```
MarketTemperature (매크로/감성/경제지표 → 온도)
    → 전략 파라미터 동적 조절 (k, TP, SL, ATR 멀티플라이어)

Scanner (거래량 TOP) → Screener (7팩터 스코어링)
    → [MA120 추세 필터] → AI 분석 or 변동성 돌파 시그널
    → Trader (리스크 관리 + 주문 실행)
```

## 실행

```bash
# 스윙 (메인)
python3 run_ai_swing_bot.py           # 실매매
python3 run_ai_swing_bot.py --paper   # 페이퍼

# 스캘핑
python3 run_scalper.py                # PAPER
python3 run_scalper.py --mode REAL    # REAL
python3 run_scalper.py --dry-run      # 시그널만

# 데이트레이딩
python3 run_firefeet.py

# 시장 온도
python3 -m core.market_temperature

# 웹 대시보드
cd web/backend && uvicorn main:app --port 8000
cd web/frontend && npm run dev
```

## 설정

모든 설정은 `config/*.yaml`에서 관리. 런타임 중 YAML 변경 시 매 루프마다 자동 반영.

| 파일 | 용도 |
|---|---|
| `secrets.yaml` | KIS API 키 (gitignore) |
| `trading_settings.yaml` | 예산, 화이트리스트 |
| `trading_rules.yaml` | 리스크 룰, 온도별 오버라이드 |
| `temperature_config.yaml` | 온도 모듈 가중치, strategy_profiles |
| `screener_settings.yaml` | 7팩터 가중치, 추세 필터 |
| `scalping_*.yaml` | 스캘핑 전용 설정 3종 |
| `deep_analysis.yaml` | AI 에이전트 모델/타임아웃 |

## 시장 온도 → 전략 매핑

| 레벨 | 온도 | k | TP | SL | 포지션% |
|---|---|---|---|---|---|
| HOT | 70+ | 0.3 | 4.0% | -3.0% | 35% |
| WARM | 40~69 | 0.4 | 3.5% | -3.0% | 30% |
| NEUTRAL | -20~39 | 0.5 | 3.0% | -3.0% | 25% |
| COOL | -60~-21 | 0.6 | 2.5% | -2.5% | 20% |
| COLD | <-60 | 0.7 | 2.0% | -2.0% | 15% |

## 수수료

매수 0.015% + 매도 0.015% + 거래세 0.18% = 왕복 ~0.21%

## 테스트

```bash
pytest tests/ -v                    # 전체 (575 cases)
pytest tests/test_strategy.py -v    # 스윙 전략
pytest tests/test_scalp_*.py -v     # 스캘핑
pytest tests/test_web_api.py -v     # 웹 API
```

## 디렉토리 구조

```
core/
  analysis/          # 기술 분석, 스코어링, AI 에이전트, LLM 모듈
  execution/         # 트레이더, 포트폴리오, 리스크 가드
  scalping/          # 스캘핑 엔진, 전략, 시그널, 리스크
  temperature/       # 온도 모듈 (매크로, 감성, 경제지표)
  providers/         # KIS API, 데이터 서비스
config/              # YAML 설정
web/
  backend/           # FastAPI (시세, 봇 제어, Discord 전송)
  frontend/          # Next.js 대시보드
tests/               # pytest 테스트 575건
docs/                # 전략/시스템 문서
.claude/
  agents/            # param-tune, market-brief, incident
  skills/            # trade-review, config-check
```

## 외부 API

KIS (시세/주문), yfinance (미 지수/VIX), Naver Finance (거래량/뉴스), Anthropic Claude (AI 분석), Discord Webhook (알림)
