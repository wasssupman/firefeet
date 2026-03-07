# AI 스윙 트레이딩 시스템

## 실행

```bash
python3 run_ai_swing_bot.py          # 실매매
python3 run_ai_swing_bot.py --paper  # 페이퍼 트레이딩
```

- 장 시간(09:00~15:20 KST, 평일)만 동작
- PID lock으로 단일 인스턴스 보장
- 시작 시 health check: Claude CLI, config, Discord webhook, API 키 검증

---

## 핵심 원리

> **"추세 안에서, 수축 이후의 확장을 산다."**

3개 기둥 + 1개 리스크 원칙:

| # | 기둥 | 무엇을 보는가 | 구현 |
|---|------|-------------|------|
| ① | **TREND (추세)** | 큰 흐름이 우호적인가 | MA120 필터 + MarketTemperature |
| ② | **CONTRACTION (수축)** | 리스크가 압축되었는가 | ATR(5)/ATR(20) 수축 비율 |
| ③ | **EXPANSION (확장)** | 지금 터지고 있는가 | 변동성 돌파 (Open + Range×K) |
| ④ | **RISK ANCHORING** | 손절이 구조에 앵커링 | ATR(14)×M 기반 SL/TP |

---

## 아키텍처

```
Scanner(거래량 TOP 20)
    │
    ▼
[MA120 추세 필터] ← ① TREND: Stage 2 종목만 통과
    │
    ▼
Screener(7팩터 스코어링 + 수축 보너스) ← ② CONTRACTION: ATR 비율로 수축 감지
    │
    ▼
[변동성 돌파 시그널?] ← ③ EXPANSION: 수축 이후 돌파
    │
    ▼
AI Dual-LLM 판단 (Analyst → Executor → Vision)
    │
    ▼
SwingTrader 매매 (ATR 기반 SL/TP) ← ④ RISK ANCHORING: 구조적 손절
    │
    ▼
KIS API 주문 → TradeLogger → Discord 알림
```

---

## Dual-LLM 파이프라인

```
┌──────────────────────────────────────────────────────────┐
│  Phase 1: Analyst (Claude Sonnet)                        │
│  입력: OHLC, 수급, 뉴스, 시장온도, 스크리너점수          │
│  출력: Markdown 분석 메모                                 │
├──────────────────────────────────────────────────────────┤
│  Phase 2: Executor (Claude Sonnet, temp=0.0)             │
│  입력: 분석 메모 + hard facts (현재가, 점수)              │
│  역할: CRO — 메모보다 hard facts 우선, sanity check      │
│  출력: JSON {decision, confidence, target, stop, reason}  │
├──────────────────────────────────────────────────────────┤
│  Phase 3: Vision AI (선택, BUY 시그널만)                  │
│  입력: 가격 차트 이미지                                   │
│  역할: 시각적 교차 검증                                   │
└──────────────────────────────────────────────────────────┘
```

**Decision 스키마**:
```json
{
  "decision": "BUY|HOLD|WAIT|SELL",
  "confidence": 0-100,
  "strategy_type": "BREAKOUT|PULLBACK|MEAN_REVERSION|TREND_FOLLOWING",
  "target_price": 55000,
  "stop_loss": 48000,
  "reasoning": "MA120 위 Stage 2, ATR 수축 후 거래량 돌파..."
}
```

**Sanity Check (Executor)**:
- `target_price` ∈ `[current × 1.05, current × 1.30]`
- `stop_loss` ∈ `[current × 0.90, current × 0.95]`
- 범위 밖이면 `WAIT` 반환 (오신호 차단)

---

## 스크리너 7팩터 스코어링

| 팩터 | 가중치 | 100점 | 0점 |
|------|--------|-------|-----|
| **거래량 급증** | 20% | 5일 평균 대비 5배↑ | 평균 미만 |
| **가격 모멘텀** | 10% | 등락률 +3% (sweet spot) | 0% 이하 or 13%+ |
| **MA 정배열** | 20% | P > MA5 > MA20 + 넓은 spread | 역배열 |
| **수급** | 20% | 외국인+기관 쌍끌이 매수 | 쌍끌이 매도 |
| **돌파 근접도** | 15% | 이미 돌파 (over 2% 미만) | 목표가까지 5%+ |
| **수축 보너스** | 10% | ATR(5)/ATR(20) < 0.5 | 이미 확장 (>1.0) |
| **장중 체력** | 5% | 고가 대비 -0.5% 이내 | 고가 대비 -3%+ |

**Pre-filter** (API 호출 전):
- 최소 거래량 50만주, 최대 가격 50만원
- 등락률 -2% ~ +15%

**MA120 추세 필터** (스코어링 전):
- `price > MA120` AND `MA120 기울기 > 0` (현재 MA120 > 20일전 MA120)
- 데이터 부족(120일 미만) 시 자동 비활성화

**AI 테마 필터** (스코어링 후, 선택):
- Claude Sonnet이 상위 15개 후보의 테마/내러티브 평가

---

## 매수 흐름

```
_process_ai_buy(code)
    │
    ├─ _can_buy() 체크
    │   ├─ 연속SL 브레이크 활성?
    │   ├─ 일일 손실한도 초과?
    │   ├─ 당일 재매수 금지?
    │   └─ 최대 보유 종목 초과?
    │
    ├─ AI 판단 요청 → decision
    │   └─ decision != "BUY" → 종료
    │
    ├─ confidence >= min_confidence (기본 80)?
    │   └─ 미달 → 종료
    │
    ├─ 수량 계산 (budget / price)
    │
    └─ KIS 매수 주문 → 로깅 → Discord 알림
```

## 매도 흐름

```
_process_ai_sell(code)
    │
    ├─ [1단계] 하드 손절 (AI 판단 전, 기계적 보호)
    │   ├─ 고정 SL: trading_rules.hard_stop_loss_pct (기본 -7%)
    │   ├─ ATR SL: -(ATR(14) × multiplier) / avg_price × 100
    │   ├─ effective = min(고정, ATR) ← 더 넓은 쪽 사용
    │   └─ profit_rate <= effective → 즉시 전량 매도
    │
    └─ [2단계] AI 판단
        ├─ decision == "SELL" → 매도
        └─ 그 외 → HOLD (유지)
```

---

## ATR 기반 구조적 손절/익절

### 원리

고정 % SL은 종목의 변동성을 무시한다:
- 변동폭 8% 종목에 -3% SL = 노이즈에 잘림
- 변동폭 1% 종목에 -3% SL = 3일치 하락 허용

ATR 기반 SL은 **종목의 변동성에 비례**:

```
effective_SL = min(고정_SL, ATR_SL)
effective_TP = max(고정_TP, ATR_TP)

ATR_SL = -(ATR(14) × atr_sl_multiplier) / buy_price × 100
ATR_TP = +(ATR(14) × atr_tp_multiplier) / buy_price × 100
```

- `min(고정, ATR)`: 고정 %가 floor (최소 보호). ATR이 더 넓으면 ATR 사용
- `max(고정, ATR)`: 고정 %가 floor (최소 보상). ATR이 더 넓으면 ATR 사용

### 예시

```
종목 A (저변동): 가격 50,000원, ATR(14) = 500원
  ATR SL = -(500 × 2.5) / 50000 × 100 = -2.5%
  고정 SL = -3.0%
  → effective = min(-3.0, -2.5) = -3.0% (고정이 더 넓어 고정 사용)

종목 B (고변동): 가격 50,000원, ATR(14) = 4,000원
  ATR SL = -(4000 × 2.5) / 50000 × 100 = -20.0%
  고정 SL = -3.0%
  → effective = min(-3.0, -20.0) = -20.0% (ATR이 더 넓어 ATR 사용)
```

### 온도별 ATR 멀티플라이어

| 레벨 | atr_sl_multiplier | atr_tp_multiplier | 의미 |
|------|------------------|------------------|------|
| HOT | 2.0 | 3.5 | 공격적: 좁은 SL, 넓은 TP (추세 신뢰) |
| WARM | 2.0 | 3.0 | |
| NEUTRAL | 2.5 | 3.0 | 균형 |
| COOL | 2.5 | 2.5 | |
| COLD | 3.0 | 2.0 | 방어적: 넓은 SL (노이즈 회피), 좁은 TP (빠른 수익 확정) |

---

## ATR 수축 비율 (Contraction Ratio)

```
contraction_ratio = ATR(5) / ATR(20)
```

| 비율 | 상태 | 스크리너 점수 | 의미 |
|------|------|-------------|------|
| < 0.5 | 극도의 수축 | 100점 | 폭발적 돌파 임박 가능 |
| < 0.8 | 수축 중 | 70점 | 돌파 시 가치 있는 신호 |
| 0.8~1.0 | 보통 | 30점 | 약간의 가산점 |
| > 1.0 | 이미 확장 | 0점 | 보너스 없음 |

---

## 온도 → 전략 프로파일

| 레벨 | 온도 범위 | k | TP | SL | 포지션% | ATR SL×M | ATR TP×M |
|------|----------|-----|------|------|---------|----------|----------|
| HOT | 70+ | 0.3 | 4.0% | -3.0% | 35% | 2.0 | 3.5 |
| WARM | 40~69 | 0.4 | 3.5% | -3.0% | 30% | 2.0 | 3.0 |
| NEUTRAL | -20~39 | 0.5 | 3.0% | -3.0% | 25% | 2.5 | 3.0 |
| COOL | -60~-21 | 0.6 | 2.5% | -2.5% | 20% | 2.5 | 2.5 |
| COLD | <-60 | 0.7 | 2.0% | -2.0% | 15% | 3.0 | 2.0 |

---

## 리스크 관리 계층

| 계층 | 메커니즘 | 설정 위치 |
|------|---------|----------|
| 건별 | 최대 포지션 금액 (100~200K) | `trading_rules.yaml` → `max_position_amount` |
| 일일 | 일일 손실 한도 (-30K~-80K) | `trading_rules.yaml` → `daily_loss_limit` |
| 연속 | N회 연속 SL → 매매 중단 (15~60분) | `trading_rules.yaml` → `consecutive_sl_brake` |
| 포트폴리오 | 최대 보유 종목 수 (2~15) | `trading_rules.yaml` → `max_holdings` |
| 쿨다운 | 매도 후 재매수 대기 (0~30분) | `trading_rules.yaml` → `no_rebuy_after_sell` |
| AI 확신도 | 최소 confidence 미달 시 매수 거부 | `trading_rules.yaml` → `ai_min_buy_confidence` |
| 하드 SL | ATR 기반 강제 손절 (-7% floor) | `trading_rules.yaml` → `hard_stop_loss_pct` |
| AI 일일 쿼터 | 일일 AI 호출 한도 (100회) | `deep_analysis.yaml` → `max_daily_calls` |

---

## 파일 맵

### 실행 & 진입점

| 파일 | 용도 |
|------|------|
| `run_ai_swing_bot.py` | 스윙 봇 메인 (초기화 → 메인 루프) |
| `run_firefeet.py` | 데이트레이딩(변동성 돌파) 봇 |
| `run_scalper.py` | 스캘핑 봇 |
| `run_report_bot.py` | 정기 리포트 데몬 (`--now` 즉시 실행) |
| `run_news_bot.py` | 뉴스 알림 봇 (60초 폴링) |
| `run_batch_reports.py` | 배치 리포트 |
| `run_deep_analysis.py` | AI 심층 분석 |
| `run_export.py` | CLI 리포트 (`macro\|watchlist\|econ\|all\|chat`) |

### 코어 — 분석

| 파일 | 클래스/함수 | 용도 |
|------|-----------|------|
| `core/analysis/technical.py` | `VolatilityBreakoutStrategy` | 변동성 돌파 전략, ATR 계산, 수축 비율, SL/TP |
| `core/analysis/scoring_engine.py` | `StockScreener` | 7팩터 스코어링, MA120 필터, 수축 보너스 |
| `core/analysis/ai_swing_agent.py` | `AISwingAgent` | Dual-LLM 오케스트레이터 (Analyst → Executor → Vision) |
| `core/analysis/llms/claude_analyst.py` | `ClaudeAnalyst` | Phase 1: Markdown 분석 메모 생성 |
| `core/analysis/llms/claude_executor.py` | `ClaudeExecutor` | Phase 2: CRO 역할, JSON 결정 출력 |
| `core/analysis/llms/vision_analyst.py` | `VisionAnalyst` | Phase 3: 차트 시각 검증 (선택) |
| `core/analysis/supply.py` | `SupplyAnalyzer` | 외국인/기관 수급 분석 |

### 코어 — 실행

| 파일 | 클래스 | 용도 |
|------|-------|------|
| `core/execution/trader.py` | `FirefeetTrader` | 베이스 트레이더 (예산, 리스크 룰, 포트폴리오) |
| `core/execution/swing_trader.py` | `SwingTrader` | AI 스윙 트레이더 (오버나잇, ATR 하드SL) |

### 코어 — 시장 분석

| 파일 | 용도 |
|------|------|
| `core/market_temperature.py` | 온도 오케스트레이터 (Macro 40% + Sentiment 35% + Econ 25%) |
| `core/temperature/macro_module.py` | 미 지수, VIX, 환율, 채권 분석 |
| `core/temperature/sentiment_module.py` | Naver/글로벌 뉴스 감성 분석 |
| `core/temperature/econ_module.py` | 경제 지표 서프라이즈 |
| `core/scanner.py` | 거래량 TOP 20 스캐너 |

### 설정

| 파일 | 핵심 파라미터 |
|------|-------------|
| `config/trading_settings.yaml` | `total_budget`, `whitelist` |
| `config/trading_rules.yaml` | 리스크 룰 + 온도별 오버라이드 |
| `config/temperature_config.yaml` | 온도 모듈 가중치 + `strategy_profiles` (k, TP, SL, ATR 멀티플라이어) |
| `config/screener_settings.yaml` | 7팩터 가중치 + `trend_filter` + pre-filter |
| `config/deep_analysis.yaml` | AI 에이전트 (모델, 타임아웃, 쿼터, 프롬프트 모드) |
| `config/agent_settings.yaml` | AI 모델/가중치 |

### 테스트

| 파일 | 대상 |
|------|------|
| `tests/test_strategy.py` | `VolatilityBreakoutStrategy` (42 cases: 시그널, ATR, 수축, SL/TP) |
| `tests/test_trader.py` | `FirefeetTrader` (포트폴리오, 매수/매도, 리스크 룰) |
| `tests/test_ai_swing_agent.py` | `AISwingAgent` (Dual-LLM 파이프라인) |

---

## 데이터 흐름 상세

```
1. Scanner → KIS API + Naver → 거래량 TOP 20 종목 리스트
       │
2. Screener Pre-filter → 가격/거래량/등락률 기본 제거
       │
3. MA120 추세 필터 → KIS OHLC 120일 → Stage 4/1 종목 제거
       │
4. 7팩터 스코어링 → 종합 점수 계산 (수축 보너스 포함)
       │
5. AI 테마 필터 → Claude Sonnet → 테마/내러티브 검증 (상위 15개)
       │
6. TOP 10 선별 → SwingTrader.target_codes 갱신
       │
7. 종목별 루프 (10~30초 주기):
   │
   ├─ 미보유: ai_data_provider(code) → AISwingAgent.analyze()
   │          → BUY + confidence ≥ 80 → KIS 매수
   │
   └─ 보유:   하드SL 체크 (ATR 기반) → AI 판단 → SELL 시 KIS 매도
```

---

## 설정 튜닝 가이드

### 공격적 (HOT 시장)
```yaml
# temperature_config.yaml → strategy_profiles → HOT
k: 0.3              # 낮은 k = 쉬운 돌파 조건
take_profit: 4.0     # 넓은 TP
atr_sl_multiplier: 2.0  # 좁은 SL (추세 신뢰)
atr_tp_multiplier: 3.5  # 넓은 TP (수익 극대화)
```

### 방어적 (COLD 시장)
```yaml
# temperature_config.yaml → strategy_profiles → COLD
k: 0.7              # 높은 k = 강한 돌파만 매수
take_profit: 2.0     # 빠른 수익 확정
atr_sl_multiplier: 3.0  # 넓은 SL (노이즈 회피)
atr_tp_multiplier: 2.0  # 좁은 TP (빠른 청산)
```

### 스크리너 조정
```yaml
# screener_settings.yaml
weights:
  contraction_bonus: 10  # 수축 보너스 비중 (↑ = 수축 종목 우대)
trend_filter:
  enabled: true          # false로 끄면 MA120 필터 비활성
output:
  min_score: 30          # ↑ = 더 엄격한 선별
```
