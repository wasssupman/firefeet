# 스캘핑 봇 시스템 문서

## 실행 방법

```bash
# 스캘핑 봇 (PAPER 모드)
python3 run_scalper.py

# 스캘핑 봇 (REAL 모드)
python3 run_scalper.py --mode REAL

# DRY-RUN (시그널만 로깅, 주문 없음)
python3 run_scalper.py --dry-run

# 테스트 실행
python3 -m pytest tests/test_scalp_*.py tests/integration/test_scalp_*.py -v

# 설정 검증만
python3 -m pytest tests/test_scalp_config_validation.py -v
```

## 아키텍처

```
WebSocket (KIS)
  ├─ on_tick ──────→ TickBuffer (VWAP, momentum, volume accel)
  ├─ on_orderbook ─→ OrderbookAnalyzer (imbalance, spread, velocity)
  └─ on_notice ────→ 체결 통보 → positions 업데이트 (_processed_orders로 이중 처리 방지)

Scanner (3분 주기)
  → ScalpScreener.filter_stocks()
  → WebSocket rotate_subscriptions()

MarketTemperature (30분 주기 장중 재계산)
  → ScalpStrategy.apply_temperature()
  → StrategySelector.apply_temperature()
  → RiskManager.apply_temperature()

ScalpEngine._eval_cycle() [1.5초 루프]
  ├─ 시장 패닉 가드 (30초 주기, 타겟 전종목 평균 하락률 감시)
  ├─ 불변식 검증 (포지션/예산 한도)
  ├─ EOD 강제 청산 (15:28 PAPER / 15:20 REAL)
  ├─ 서킷브레이커 확인
  ├─ 미체결 주문 관리 (15초 타임아웃)
  ├─ 보유 종목별: _eval_exit()
  └─ 타겟 종목별: _eval_entry()
```

## 파일 구조

```
core/scalping/
├── scalp_engine.py          # 메인 오케스트레이터 (1.5초 루프)
├── scalp_strategy.py        # 진입/청산 판단 (evaluate + should_exit)
├── scalp_signals.py         # 5개 독립 시그널 계산기
├── strategy_selector.py     # 시간+온도 기반 전략 프로필 선택
├── risk_manager.py          # 리스크 한도 + 서킷브레이커
├── tick_buffer.py           # 틱 링버퍼 (600틱, ~10분)
├── orderbook_analyzer.py    # 호가 분석 (10호가)
├── scalp_screener.py        # 종목 필터링 + 스코어링
└── __init__.py

config/
├── scalping_settings.yaml   # 예산, 포지션, 시그널 임계값
├── scalping_rules.yaml      # REAL/PAPER 모드별 리스크 규칙
└── scalping_strategies.yaml # 전략 프로필 정의 + 점심 차단

tests/
├── test_scalp_strategy.py          # evaluate + should_exit + temperature + SIGNAL 비활성화 회귀
├── test_scalp_signals.py           # 5개 시그널 실제 계산 검증
├── test_scalp_strategy_selector.py # 시간/온도 매칭 + 프로필 선택
├── test_scalp_risk_manager.py      # 리스크 한도 + 서킷브레이커 (이중 리셋 방지 포함)
├── test_scalp_screener.py          # 종목 필터링 + 스코어링 + ticks_to_cover 수수료 계산
├── test_scalp_trade_logger.py      # 30컬럼 CSV 로깅
├── test_scalp_config_validation.py # 설정 파일 일관성 (배포 전 필수)
├── integration/
│   └── test_scalp_engine_flow.py   # 엔진 시나리오 (진입→청산 플로우)
└── mocks/
    └── mock_scalping.py            # TickBuffer/Orderbook 헬퍼
```

## 매매 로직

### 진입 (_eval_entry)

```
1. 용량 확인: 보유 + 미체결 < max_positions
1.5. 시장 패닉 가드: _market_panic_active → 즉시 리턴
2. 쿨다운 확인: 주문 쿨다운(30초) + 매도 쿨다운(10분)
3. 데이터 충분성: TickBuffer에 30틱 이상
4. 전략 선택: StrategySelector.select(시간, 온도) → StrategyProfile
   - None이면 진입 차단 (점심시간 12:00~15:20)
5. 시그널 계산: ScalpStrategy.evaluate()
   - 5개 시그널 → 가중 합산 → composite score (0~100)
   - 페널티 검사: spread_penalty × volume_penalty < 0.5 → 거부
   - composite ≥ threshold → 진입 허용
6. 리스크 확인: RiskManager.can_enter()
   - 일일 손실 한도, 거래 횟수, 시간 제한, 포지션 금액
7. 주문: place_order(BUY) → pending_orders 등록
```

### 청산 (_eval_exit)

우선순위 순서:

| 순서 | 조건 | 시그널 | 주문 타입 |
|------|------|--------|-----------|
| 1 | 건당 손실 한도 초과 | `RISK` | 시장가 |
| 2 | 트레일링 스탑 (수익 ≥ 0.5% 후 65% 이탈) | `TRAILING` | 시장가 |
| 3 | 손절 (profit ≤ SL%) | `SL` | 시장가 |
| 4 | 익절 (profit ≥ TP%) | `TP` | 지정가 |
| 5 | 타임아웃 (hold ≥ 180초) | `TIMEOUT` | **지정가** |
| 6 | ~~시그널 청산~~ | `SIGNAL` | **비활성화** |
| 7 | BB 상단 (profit>0.25% + BB>0.9) | `BB` | 지정가 |
| 8 | 저항선 근접 (profit>0.25% + 0.05% 이내) | `RESISTANCE` | 지정가 |
| 9 | 매도벽 감지 (profit>0.25% + ask wall) | `WALL` | 지정가 |

> **SIGNAL 청산 비활성화 (2026-03-03)**: 275거래 분석에서 SIGNAL 청산 13건이 전패(-92K).
> 근본 원인: (1) `min_loss_pct` 게이트가 손실 거래만 선택 → 100% 패배 구조적 보장,
> (2) 진입 시그널을 청산에 재사용 → 90초 후 자연 감쇠로 항상 발동.
> `exit_threshold_ratio: 0.0`으로 비활성화. 기존 SIGNAL 대상 거래는 SL/TP/TIMEOUT으로 자연 분배.

> **TIMEOUT 지정가 변경 (2026-03-03)**: 기존 시장가 → 지정가로 변경. 24건 -70K 슬리피지 출혈 감소.

## 5개 시그널

| 시그널 | 가중치 | 입력 데이터 | 점수 범위 |
|--------|--------|-------------|-----------|
| VWAP Reversion | 25% | VWAP 거리 + 거래량 가속 + 60초 추세 | 0~100 |
| Orderbook Pressure | 25% | 매수/매도 불균형 + 속도 + 기울기 | 0~100 |
| Momentum Burst | 20% | 틱 비율 + 10초 모멘텀 + 거래량 | 0~100 |
| Volume Surge | 15% | 30초 거래량 / 180초 평균 | 0~100 |
| Micro Trend | 15% | 10/30/60초 모멘텀 정렬 | 0~100 |

composite = 가중 합산 (0~100), threshold 이상이면 진입.

### 시그널 품질 평가 (2026-03-03 분석)

| 시그널 | 등급 | 비고 |
|--------|------|------|
| VWAP Reversion | B+ | 가장 유용. 60초 추세 조건이 진입 지연시킬 수 있음 |
| Orderbook Pressure | B- | 스푸핑 필터 부재 |
| Momentum Burst | C+ | 모멘텀 추격 위험 |
| Volume Surge | C | 방향성 결여 — 패닉셀에도 고점수 |
| Micro Trend | D+ | VWAP/Momentum과 중복, 폐지 검토 중 |

## 핵심 파라미터

| 항목 | 값 | 비고 |
|------|---|------|
| TP (기본) | **1.5%** | 2026-03-03 상향 (기존 1.2%). R:R 1.81 |
| SL (기본) | -0.5% | |
| 왕복 수수료 | ~0.21% | 매수 0.015% + 매도 0.015% + 거래세 0.18% |
| min_price | **10,000원** | 2026-03-03 상향 (기존 3,000). 틱사이즈 불리 종목 제거 |
| max_price | **500,000원** | 2026-03-03 상향 (기존 50,000). 삼전/하이닉스 포함 |
| conf threshold | 0.40 (기본) | 온도/프로필에 따라 0.35~0.50 |
| max_hold | 180초 (3분) | |
| eval_interval | 1,500ms | |
| 매도 쿨다운 | 600초 (10분) | |

## 온도별 파라미터

| 레벨 | conf | max_pos | 모드 | TP | SL |
|------|------|---------|------|----|----|
| HOT | 0.35 | 3 | aggressive | 2.0% | -0.8% |
| WARM | 0.38 | 2 | aggressive | 1.5% | -0.7% |
| NEUTRAL | 0.40 | 2 | aggressive | 1.5% | -0.5% |
| COOL | 0.45 | 2 | micro_swing | 1.0% | -0.5% |
| COLD | 0.50 | 1 | micro_swing | 0.8% | -0.4% |

## 리스크 규칙 (PAPER / REAL)

| 항목 | PAPER | REAL |
|------|-------|------|
| 건당 최대 손실 | 20,000원 / 1.0% | 5,000원 / 0.5% |
| 건당 포지션 한도 | 2,000,000원 | 200,000원 |
| 일일 최대 손실 | 200,000원 | 30,000원 |
| 일일 거래 횟수 | 20건 | 50건 |
| 서킷브레이커 | 5연패 → 300초 쿨다운 | 5연패 → 600초 쿨다운 |
| 진입 금지 시간 | ~09:00, 15:25~ | ~09:05, 15:10~ |
| 강제 청산 시간 | 15:28 | 15:20 |

## 시장 패닉 가드 (2026-03-03 추가)

KOSPI -7.24% 폭락 (미국-이란 전쟁) 시 봇이 삼성전자를 "틱 효율이 좋다"는 이유로 매수한 사건에서 발견된 구조적 결함 수정.

### 문제: 3가지 방어 부재

1. **온도 1회 계산** — 장 시작 시 1회만 계산, 장중 급변 미반영
2. **시그널 개별 종목만** — 5개 시그널 전부 개별 종목 데이터만 분석, 시장 전체 상황 무시
3. **서킷브레이커 사후 대응** — 돈을 잃고 나서야 작동

### 해결: 2단계 방어 체계

**Level 1 — 종목 낙폭 필터 + 시장 패닉 가드**

| 방어선 | 위치 | 동작 |
|--------|------|------|
| 급락 종목 차단 | `scalp_screener.py` | `change_rate ≤ -3%` 종목은 타겟에서 제외 |
| 시장 패닉 감지 | `scalp_engine.py` | 30초마다 타겟 전종목 평균 하락률 체크 |
| 진입 전면 차단 | `scalp_engine.py` | 평균 -2% 이하 또는 50%+ 급락 → 신규 매수 전면 중단 |

설정 (`config/scalping_settings.yaml`):
```yaml
panic_guard:
  enabled: true
  avg_decline_threshold: -2.0    # 평균 하락률 임계값 (%)
  crash_stock_pct: 50            # 급락 종목 비율 임계값 (%)
  crash_stock_threshold: -3.0    # 개별 급락 기준 (%)
  check_interval: 30             # 체크 주기 (초)
```

**Level 2 — 장중 온도 재계산 (30분 주기)**

`run_scalper.py`에서 30분마다 `MarketTemperature` 재계산. 전쟁/폭락 시 VIX↑, 지수↓로 COLD 전환 → confidence 0.50, max_positions 1로 자동 조절.

- 최초 실패: NEUTRAL 폴백
- 재계산 실패: 기존 온도 유지 (덮어쓰지 않음)

### 방어 흐름 (오늘 같은 폭락장)

```
09:00  온도=NEUTRAL (아침 계산)
09:30  전쟁 뉴스 → KOSPI 급락
09:31  스캐너: 삼성전자 -5% → screener: change_rate ≤ -3% → ❌ 타겟 제외
09:31  패닉 가드: 타겟 평균 -4% → ❌ 전면 진입 차단
09:30  온도 재계산: VIX↑, 지수↓ → COLD → threshold 0.50, max_positions 1
```

## 설정 우선순위 (3중 threshold)

```
전략 프로필 (profile.confidence_threshold)
  > 온도 오버라이드 (rules.temperature_overrides[level].confidence)
    > 글로벌 기본값 (settings.default_confidence_threshold)
```

evaluate() 호출 시: `max(profile.conf, 온도-조정-글로벌)` 사용.
온도는 apply_temperature()로 글로벌 threshold를 업데이트하지만 profile이 우선.

## 수수료 분석 (275거래 기준, 2026-02-26)

| 항목 | 값 |
|------|---|
| 세전 손익 | -20,254원 (거의 본전) |
| 세후 손익 | -1,084,720원 |
| **수수료 비중** | **총 손실의 98%** |
| conf < 0.35 | 219거래, 43.4% 승률, -1.04M |
| conf ≥ 0.35 | 56거래, 51.8% 승률, -127K |
| **conf 필터 효과** | **손실 88% 감소** |

핵심: 전략 자체는 본전이나 수수료가 모든 것을 삼킨다. conf ≥ 0.35 필터 + 12시 이후 차단(D전략)이 최적.

## 버그 수정 이력 (2026-03-03)

| 이슈 | 파일 | 내용 |
|------|------|------|
| SIGNAL 청산 구조결함 | `config/scalping_settings.yaml` | `exit_threshold_ratio: 0.50→0.0` — 13건 전패 제거 |
| 서킷브레이커 이중 리셋 | `risk_manager.py` | `can_enter()` + `check_circuit_reset()` 이중 호출 시 카운트 중복 방지 |
| ticks_to_cover 계산 오류 | `scalp_screener.py` | `0.21/(tick_pct*100)→0.21/tick_pct` — 100배 과소 계산 수정 |
| WebSocket 이중 체결 | `scalp_engine.py` | `_processed_orders` 세트로 notice/API 폴링 간 경합 방지 |
| TP 상향 | `config/scalping_settings.yaml` | `1.2%→1.5%` — R:R 1.39→1.81 |
| min_price 상향 | `config/scalping_settings.yaml` | `3,000→10,000원` — 틱사이즈 불리 종목 제거 |
| TIMEOUT 지정가 | `scalp_strategy.py` | 시장가→지정가 — 슬리피지 감소 |
| max_price 상향 | `config/scalping_settings.yaml` | `50,000→500,000원` — 삼전/하이닉스 대형주 포함 |
| 시장 패닉 가드 | `scalp_engine.py`, `scalp_screener.py` | 폭락장 매수 방지 — 급락종목 차단 + 시장 패닉 감지 |
| 장중 온도 재계산 | `run_scalper.py` | 1회→30분 주기 — 장중 급변 시황 반영 |

## 소스 → 테스트 매핑

| 소스 파일 | 테스트 파일 | 변경 시 업데이트 |
|-----------|-----------|----------------|
| `scalp_strategy.py` | `test_scalp_strategy.py` | evaluate/should_exit 시그니처, 청산 조건, 페널티 로직 |
| `scalp_signals.py` | `test_scalp_signals.py` | 시그널 계산 로직, 새 시그널 추가 |
| `strategy_selector.py` | `test_scalp_strategy_selector.py` | StrategyProfile 필드, 시간 매칭, 온도 매핑 |
| `risk_manager.py` | `test_scalp_risk_manager.py` | 한도값, 서킷브레이커 조건, 시간 제한 |
| `scalp_screener.py` | `test_scalp_screener.py` | 필터 조건, 스코어링, ticks_to_cover, 급락 필터 |
| `scalp_engine.py` | `integration/test_scalp_engine_flow.py` | 진입/청산 플로우, pending 관리, 패닉 가드 |
| `trade_logger.py` | `test_scalp_trade_logger.py` | CSV_HEADER, log_scalp_buy/sell 시그니처 |
| `config/scalping_*.yaml` | `test_scalp_config_validation.py` | TP/SL 값, threshold, 시간대, weights |

## 커맨드 치트시트

```bash
# 테스트
pytest tests/test_scalp_*.py tests/integration/test_scalp_*.py -v  # 스캘핑 전체 (163 cases)
pytest tests/test_scalp_config_validation.py -v                     # 설정 검증
pytest tests/ -v --tb=short                                         # 전체 (pre-commit hook)

# 실행
python3 run_scalper.py                     # PAPER 모드
python3 run_scalper.py --mode REAL         # REAL 모드
python3 run_scalper.py --dry-run           # 시그널만

# 로그
python3 -m core.trade_logger              # 거래 로그 조회
tail -f logs/scalp_trades_*.csv           # CSV 실시간
```

## TODO

- [x] ~~SIGNAL 청산 로직 점검~~ — 비활성화 완료 (exit_threshold_ratio=0.0)
- [x] ~~수수료 대비 TP/SL 최적화~~ — TP 1.2%→1.5% 상향, min_price 10,000원
- [ ] Micro Trend 시그널 폐지 검토 — VWAP/Momentum과 중복 (D+ 등급), 가중치 재분배
- [ ] Volume Surge 방향성 추가 — 매수 체결 비중 기반으로 패닉셀 필터링
- [ ] Orderbook Pressure 스푸핑 필터 — 급변하는 허수 호가 감지
- [ ] 매 사이클 YAML 리로드 캐싱 — 1.5초마다 17회 파일 I/O 성능 개선
- [ ] WebSocket/메인루프 간 threading.Lock — GIL이 완화하지만 명시적 동기화 필요
- [ ] TA overlay 실패 시 fallback — IntradayAnalyzer 에러 시 동적 TP/SL 미적용
- [ ] 미체결 주문 타임아웃 재검토 — 설정 3초 vs 하드코딩 15초 불일치 (M-3)
- [ ] adaptive 풀 회전 비대칭 — 50사이클 차단 후 해제가 3분 주기에 의존
- [x] ~~장중 온도 재계산~~ — 30분 주기 재계산 완료 (run_scalper.py)
- [ ] 20거래일 데이터 수집 후 파라미터 재분석 (D전략 2026-02-26 적용 시작)
- [ ] 패닉 가드 Level 3 — 실시간 시장 레짐 감지 (KOSPI 지수 모니터링, sidecar/VI 감지)
- [ ] "스캘핑" → "초단기 스윙(Micro Swing)" 정체성 전환 검토
