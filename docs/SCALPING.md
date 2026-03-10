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
  ├─ on_tick ──────→ TickBuffer (VWAP, rolling VWAP, momentum, tick rate z-score)
  ├─ on_orderbook ─→ OrderbookAnalyzer (imbalance, spread, velocity)
  └─ on_notice ────→ 체결 통보 → positions 업데이트 (_processed_orders로 이중 처리 방지)

Scanner (3분 주기)
  → ScalpScreener.filter_stocks() (거래대금 + ATR 필터)
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
  ├─ 보유 종목별: _eval_exit() + MAE/MFE 추적
  └─ 타겟 종목별: _eval_entry()
```

## 파일 구조

```
core/scalping/
├── scalp_engine.py          # 메인 오케스트레이터 (1.5초 루프, 변동성 게이트, MAE/MFE)
├── scalp_strategy.py        # 진입/청산 판단 (evaluate + should_exit 3조건)
├── scalp_signals.py         # 2개 시그널 (VWAP reversion 이벤트 트리거 + orderbook)
├── strategy_selector.py     # 시간+온도 기반 전략 프로필 선택
├── risk_manager.py          # 리스크 한도 + 서킷브레이커
├── tick_buffer.py           # 틱 링버퍼 (3000틱, ~180초, rolling VWAP)
├── orderbook_analyzer.py    # 호가 분석 (10호가)
├── scalp_screener.py        # 종목 필터링 + 스코어링
└── __init__.py

config/
├── scalping_settings.yaml   # 예산, 포지션, 시그널 임계값
├── scalping_rules.yaml      # REAL/PAPER 모드별 리스크 규칙
└── scalping_strategies.yaml # 전략 프로필 정의 + 점심 차단

tests/
├── test_scalp_strategy.py          # evaluate + should_exit + temperature
├── test_scalp_signals.py           # 시그널 계산 + TickBuffer 신규 메서드 + 3조건 AND
├── test_scalp_strategy_selector.py # 시간/온도 매칭 + 프로필 선택
├── test_scalp_risk_manager.py      # 리스크 한도 + 서킷브레이커 (이중 리셋 방지 포함)
├── test_scalp_screener.py          # 종목 필터링 + 스코어링 + ticks_to_cover 수수료 계산
├── test_scalp_trade_logger.py      # 39컬럼 CSV 로깅
├── test_scalp_config_validation.py # 설정 파일 일관성 (배포 전 필수)
├── integration/
│   └── test_scalp_engine_flow.py   # 엔진 시나리오 (진입→청산 플로우, 변동성 게이트)
└── mocks/
    └── mock_scalping.py            # TickBuffer/Orderbook 헬퍼
```

## 전략: VWAP Deviation Reversion (2026-03-10 전환)

### 설계 근거

386건 거래 시뮬레이션 결과, 기존 5시그널 가중 합산(composite score) 방식은 **시그널에 엣지가 없었다**:
- 세전 손익 -320K, 수수료 -1,529K → 순손익 -1,848K
- 모든 confidence 밴드에서 건당 PnL 음수
- conf↑ → 승률↓ (시그널 역전)
- 5개 시그널 중 4개가 동일 데이터(tick_buffer) → 앙상블이 아닌 중복 계산

**전환 방향**: "마이크로스트럭처 예측(composite score)" → **"VWAP Deviation Reversion(이벤트 트리거)"**

핵심 개념: 평소 거래 안 함. 가격이 VWAP에서 0.8%+ 이탈 + 거래 과열 + 속도 반전 시에만 진입 → VWAP 복귀 노림.

### 제약 조건
- **Long-only**: 한국 개인투자자 공매도 불가 → 하방 이탈(VWAP 아래) 복귀만 가능
- **수수료 0.21%**: TP 0.6% 시 필요 승률 42%
- **1.5초 루프**: 레이턴시 추가 금지

## 매매 로직

### 진입 (_eval_entry)

```
1. 용량 확인: 보유 + 미체결 < max_positions
1.5. 시장 패닉 가드: _market_panic_active → 즉시 리턴
2. 쿨다운 확인: 주문 쿨다운(30초) + 매도 쿨다운(10분)
3. 데이터 충분성: TickBuffer에 30틱 이상
4. 전략 선택: StrategySelector.select(시간, 온도) → StrategyProfile
   - None이면 진입 차단 (점심시간 12:00~15:20)
5. VWAP 필터: vwap_dist > -0.8% → 즉시 리턴
6. 변동성 게이트: ATR < 0.3% → 즉시 리턴
7. 시그널 계산: ScalpStrategy.evaluate()
   - 이벤트 트리거 (3조건 AND) → confidence
   - 페널티 검사: spread_penalty × volume_penalty < 0.5 → 거부
   - confidence ≥ threshold → 진입 허용
8. 리스크 확인: RiskManager.can_enter()
9. 주문: place_order(BUY) → pending_orders 등록
```

### 이벤트 트리거 (3조건 AND)

```
signal_vwap_reversion() — 하나라도 미충족 시 score = 0

조건 1: VWAP 이격 (과매도)
  └─ vwap_dist < -0.8% (고정, -0.6% 금지 — 수수료 불가)

조건 2: 거래 과열
  └─ tick_rate_zscore > 2.0 OR volume_accel > 2.0
     (volume spike + vwap deviation 동시 충족 시에만 허용)

조건 3: 모멘텀 반전 (하락→상승 교차)
  └─ mom_short(10초) > +0.1% AND mom_long(30초) < 0
     (2-3틱 바운스 noise 필터: threshold 0.1%)

score = dist_score(30~50) + heat_score(max 30) + reversal_score(max 20)
confidence = 최약 조건의 강도가 결정
```

### 청산 (_eval_exit)

우선순위 순서:

| 순서 | 조건 | 시그널 | 주문 타입 |
|------|------|--------|-----------|
| 1 | 건당 손실률 초과 (max_loss_pct %) | `RISK` | 시장가 |
| 2 | 트레일링 스탑 (수익 ≥ 0.5% 후 65% 이탈) | `TRAILING` | 시장가 |
| 3 | 손절 (profit ≤ -0.4%) | `SL` | 시장가 |
| 4 | 익절 (profit ≥ +0.6%) | `TP` | 지정가 |
| 5 | 타임아웃 (hold ≥ 120초) | `TIMEOUT` | 지정가 |

> **Exit 단순화 (2026-03-10)**: 기존 9개 → 5개. SIGNAL/BB/RESISTANCE/WALL exit 제거.
> SIGNAL: 구조적 전패 (진입시그널 재사용 + 손실게이트), BB/RESISTANCE/WALL: reversion 전략과 충돌.
> disposition effect 방지를 위해 time decay exit도 미적용.

## 2개 시그널

| 시그널 | 가중치 | 역할 | 데이터 소스 |
|--------|--------|------|-------------|
| VWAP Reversion | 80% | 핵심 이벤트 트리거 (3조건 AND) | TickBuffer (VWAP, tick rate z-score, momentum reversal) |
| Orderbook Pressure | 20% | 지지 확인용 보조 필터 | OrderbookAnalyzer (imbalance, velocity, slope) |

> **비활성 시그널 (2026-03-10)**: Momentum Burst, Volume Surge, Micro Trend — 코드 존속, calculate_all()에서 제외.
> 이유: 동일 tick_buffer 데이터 중복 계산 (앙상블 아닌 노이즈 증폭).

## TickBuffer 신규 메서드 (2026-03-10)

| 메서드 | 용도 | 사용처 |
|--------|------|--------|
| `get_tick_rate_zscore(code, 5s, 300s)` | z-score 정규화 틱 강도 (종목간 비교) | 이벤트 트리거 조건 2 |
| `get_momentum_reversal(code, 10s, 30s)` | 하락→상승 교차 감지 (threshold 0.1%) | 이벤트 트리거 조건 3 |
| `get_rolling_vwap_distance(code, 3600s)` | 최근 60분 Rolling VWAP 이격도 | 로깅 (full-day VWAP와 비교) |
| `get_tick_direction_ratio_time(code, 5s)` | 시간 기반 틱 방향 비율 | 분석용 |

## 핵심 파라미터

| 항목 | 값 | 비고 |
|------|---|------|
| TP | **+0.6%** | 2026-03-10 변경 (기존 1.5%). reversion edge ~0.8% |
| SL | **-0.4%** | 2026-03-10 변경 (기존 -0.5%). R:R 1.5:1 |
| 왕복 수수료 | ~0.21% | 매수 0.015% + 매도 0.015% + 거래세 0.18% |
| VWAP 이탈 임계값 | **-0.8%** | -0.6% 금지 (수수료 불가), -1.0% 빈도 부족 |
| conf threshold | **0.45** | 2026-03-10 변경 (기존 0.40). 엄선 진입 |
| max_hold | **120초** (2분) | 2026-03-10 변경 (기존 180초). reversion edge ~60-90초 |
| tick_buffer_size | **3000틱** | 2026-03-10 변경 (기존 600). 대형주 180초 커버 |
| eval_interval | 1,500ms | |
| 매도 쿨다운 | 600초 (10분) | |
| ATR 게이트 | ≥ 0.3% | 변동성 부족 시 진입 차단 |

## MAE/MFE 추적 (2026-03-10 추가)

보유 중 가격 극값을 실시간 추적하여 청산 시 CSV에 기록:

| 필드 | 계산 | 용도 |
|------|------|------|
| `mae` | (min_price - buy_price) / buy_price × 100 | 최대 역행 — SL 최적화 |
| `mfe` | (max_price - buy_price) / buy_price × 100 | 최대 순행 — TP 최적화 |
| `time_to_peak` | MFE 도달 시점 (초) | 최적 보유 시간 분석 |

## CSV 로깅 (39컬럼)

기존 30컬럼 + VWAP reversion 확장 9컬럼:

```
tick_rate_zscore     — 정규화 틱 강도
rolling_vwap_dist    — 60분 Rolling VWAP 이격도
momentum_velocity    — 반전 속도 (mom_short - mom_long)
atr_pct              — ATR %
regime               — 'reversion' | 'no_trade'
entry_trigger        — 3조건 충족 상태 (all_met/vwap/heat/reversal)
mae                  — Max Adverse Excursion (%)
mfe                  — Max Favorable Excursion (%)
time_to_peak         — MFE 도달 시간 (초)
```

## 리스크 규칙 (PAPER / REAL)

| 항목 | PAPER | REAL |
|------|-------|------|
| 건당 최대 손실률 | 0.7% | 0.5% |
| 건당 포지션 한도 | 2,000,000원 | 200,000원 |
| 일일 최대 손실 | 200,000원 | 30,000원 |
| 일일 거래 횟수 | 20건 | 50건 |
| 서킷브레이커 | 5연패 → 300초 쿨다운 | 5연패 → 600초 쿨다운 |
| 진입 금지 시간 | ~09:00, 15:25~ | ~09:05, 15:10~ |
| 강제 청산 시간 | 15:28 | 15:20 |

## 시장 패닉 가드

### 3단계 방어 체계

| Level | 위치 | 동작 |
|-------|------|------|
| 1 | `scalp_screener.py` | `change_rate ≤ -3%` 종목 타겟 제외 |
| 2 | `scalp_engine.py` | 30초 주기 타겟 평균 하락률 감시, -2% 이하 시 진입 전면 차단 |
| 3 | `run_scalper.py` | 30분 주기 온도 재계산, VIX↑/지수↓ → COLD 전환 |

## 설정 우선순위 (3중 threshold)

```
전략 프로필 (profile.confidence_threshold)
  > 온도 오버라이드 (rules.temperature_overrides[level].confidence)
    > 글로벌 기본값 (settings.default_confidence_threshold)
```

## PAPER 검증 계획 (2026-03-10~)

### Go/No-Go 기준 (2-3주 PAPER 데이터 수집 후)

| 조건 | Go | No-Go |
|------|-----|--------|
| 건당 순PnL | > 0 | < 0 |
| 승률 | > 42% | < 40% |
| 일 시그널 빈도 | > 3건 | < 1건 |
| 샘플 수 | > 30건 | < 15건 |

**하나라도 No-Go → 전략 폐기 또는 근본 재설계.**

Go 판정 시 → Phase 4 (RegimeDetector: reversion/no_trade 2분류) 진행.

## 수수료 분석

### 275거래 기준 (2026-02-26, 구 시그널)

| 항목 | 값 |
|------|---|
| 세전 손익 | -20,254원 (거의 본전) |
| 세후 손익 | -1,084,720원 |
| **수수료 비중** | **총 손실의 98%** |

### 386거래 기준 (2026-03-09, 구 시그널)

| 항목 | 값 |
|------|---|
| 세전 손익 | -320K |
| 수수료 | -1,529K |
| 순손익 | -1,848K |
| 모든 conf 밴드 | 건당 PnL 음수 |

핵심: **전략 자체에 엣지 없음 확정 → VWAP Reversion 이벤트 트리거로 전환.**

## 변경 이력

### 2026-03-10: VWAP Deviation Reversion 전환

| 항목 | Before | After |
|------|--------|-------|
| 시그널 구조 | 5개 가중 합산 (composite) | 2개 (이벤트 트리거 + 보조) |
| 진입 로직 | composite ≥ threshold | 3조건 AND (VWAP + 과열 + 반전) |
| Exit 조건 | 9개 (SL/TP/TIMEOUT/SIGNAL/BB/RESISTANCE/WALL 등) | 5개 (RISK/TRAILING/SL/TP/TIMEOUT) |
| TP / SL | 1.5% / -0.5% | 0.6% / -0.4% |
| max_hold | 180초 | 120초 |
| tick_buffer | 600틱 | 3000틱 + rolling VWAP + tick rate z-score |
| conf threshold | 0.40 | 0.45 |
| 전략 프로필 | orb + momentum_scalp + vwap_reversion | vwap_reversion 단일 |
| 활성 시간 | 09:00-12:00 (3개 프로필) | 09:30-12:00 (VWAP 안정 후) |
| 변동성 게이트 | 없음 | ATR < 0.3% 차단 |
| MAE/MFE | 없음 | 실시간 추적 + CSV 기록 |
| CSV 컬럼 | 30개 | 39개 |

### 2026-03-03: 패닉 가드 + 버그 수정

| 이슈 | 파일 | 내용 |
|------|------|------|
| SIGNAL 청산 구조결함 | `scalping_settings.yaml` | `exit_threshold_ratio: 0.0` — 13건 전패 제거 |
| 서킷브레이커 이중 리셋 | `risk_manager.py` | 카운트 중복 방지 |
| ticks_to_cover 계산 오류 | `scalp_screener.py` | 100배 과소 계산 수정 |
| WebSocket 이중 체결 | `scalp_engine.py` | `_processed_orders` 세트 추가 |
| 시장 패닉 가드 | `scalp_engine.py`, `scalp_screener.py` | 폭락장 매수 방지 |
| 장중 온도 재계산 | `run_scalper.py` | 1회→30분 주기 |

## 소스 → 테스트 매핑

| 소스 파일 | 테스트 파일 | 변경 시 업데이트 |
|-----------|-----------|----------------|
| `scalp_strategy.py` | `test_scalp_strategy.py` | evaluate/should_exit, 청산 조건, 페널티 |
| `scalp_signals.py` | `test_scalp_signals.py` | 이벤트 트리거, 3조건 AND, TickBuffer 메서드 |
| `strategy_selector.py` | `test_scalp_strategy_selector.py` | StrategyProfile, 시간 매칭, 온도 |
| `risk_manager.py` | `test_scalp_risk_manager.py` | 한도값, 서킷브레이커, 시간 제한 |
| `scalp_screener.py` | `test_scalp_screener.py` | 필터 조건, 스코어링, 급락 필터 |
| `scalp_engine.py` | `integration/test_scalp_engine_flow.py` | 진입/청산 플로우, 변동성 게이트, MAE/MFE |
| `trade_logger.py` | `test_scalp_trade_logger.py` | CSV_HEADER 39컬럼 |
| `config/scalping_*.yaml` | `test_scalp_config_validation.py` | TP/SL, threshold, weights |

## 커맨드 치트시트

```bash
# 테스트
pytest tests/test_scalp_*.py tests/integration/test_scalp_*.py -v  # 스캘핑 전체
pytest tests/test_scalp_config_validation.py -v                     # 설정 검증
pytest tests/ -v --tb=short                                         # 전체 (595 cases)

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
- [x] ~~수수료 대비 TP/SL 최적화~~ — TP 0.6%, SL -0.4%
- [x] ~~Micro Trend 시그널 폐지~~ — calculate_all()에서 제외 (2026-03-10)
- [x] ~~Volume Surge 방향성~~ — vwap_reversion 이벤트 트리거 내부 조건으로 흡수
- [x] ~~장중 온도 재계산~~ — 30분 주기 재계산 완료
- [x] ~~이벤트 트리거 전환~~ — 5시그널 가중합산 → 3조건 AND (2026-03-10)
- [ ] 2-3주 PAPER 데이터 수집 → Go/No-Go 판단
- [ ] Go 시: RegimeDetector (reversion/no_trade 2분류) 구현
- [ ] Go 시: ORB 전략 복원 검토 (09:00-09:30 VWAP 안정성 데이터 기반)
- [ ] 수수료 우대 협상 (0.21% → 0.05% 가능 시 수익 영역 극적 확장)
- [ ] Orderbook Pressure 스푸핑 필터
- [ ] 매 사이클 YAML 리로드 캐싱 — 1.5초마다 파일 I/O 성능 개선
- [ ] 패닉 가드 Level 3 — 실시간 시장 레짐 감지 (KOSPI 지수 모니터링)
