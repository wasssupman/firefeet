# Firefeet 7단계 마이그레이션 종합 테스트 플랜

## 현황 분석

### 테스트 인프라 현황 (2026-03-04 기준)

| 항목 | 수치 |
|------|------|
| 총 테스트 수 | 412 (collected), 406 passed, 6 failed |
| 테스트 파일 수 | 23개 (unit 17 + integration 2 + regression 1 + __init__ 3) |
| core 모듈 수 | 57개 |
| 테스트 있는 모듈 | 14개 (24.6%) |
| **테스트 없는 모듈** | **43개 (75.4%)** |
| 실행 시간 | ~3초 (빠름) |
| 프레임워크 | pytest 8.4.2 + unittest.mock |

### 현재 깨진 테스트 6건 (선행 수정 필요)

| 파일 | 원인 | 수정 방법 |
|------|------|-----------|
| `integration/test_buy_sell_flow.py` (3건) | `discard_client` 파라미터명이 `discord_client`로 수정됨 | `discard_client=` -> `discord_client=` |
| `regression/test_regressions.py` (2건) | 동일 원인 | `discard_client=` -> `discord_client=` |
| `test_screener.py` (1건) | `score_stock(None)` 반환값이 `None` (expected `0`) | `scoring_engine.py`의 None 처리 확인 |

### 기존 Mock/Fixture 인벤토리

**conftest.py 공유 fixtures:**
- `mock_auth` / `mock_manager` -- KIS API 계층
- `mock_discord` / `mock_news_scraper` -- 외부 서비스
- `mock_analyst` / `mock_executor` / `mock_vision` -- LLM 파이프라인
- `strategy` -- VolatilityBreakoutStrategy(k=0.5)
- `sample_ohlc` / `breakout_ohlc` -- OHLC 데이터
- `mock_config` / `trading_settings` / `temperature_config` -- 설정 파일
- `trader` -- FirefeetTrader 통합 fixture
- `scalp_settings` / `scalp_rules` / `scalp_strategies` -- 스캘핑 설정
- `tick_buffer` / `orderbook_analyzer` -- 스캘핑 데이터
- `make_data_provider` -- 데이터 프로바이더 팩토리

**mocks/ 디렉토리:**
- `mock_kis.py` -- MockKISAuth, MockKISManager, make_ohlc_dataframe
- `mock_external.py` -- MockDiscordClient, MockNewsScraper
- `mock_llm.py` -- MockClaudeAnalyst, MockClaudeExecutor, MockVisionAnalyst (IAnalystLLM/IExecutorLLM 인터페이스 구현)
- `mock_scalping.py` -- inject_ticks, inject_orderbook, make_strategy_profile, make_ta_overlay, make_tick_buffer_with_data, make_orderbook_with_data

---

## 단계 0: 선행 수정 (Pre-migration Baseline)

마이그레이션 시작 전 깨진 테스트를 수정하여 **그린 베이스라인**을 확보한다.

```
단계 0: Pre-migration Baseline
├── 수정 작업
│   ├── conftest.py:178 — discard_client= → discord_client=
│   ├── integration/test_buy_sell_flow.py:51 — discard_client= → discord_client=
│   ├── regression/test_regressions.py:85,250 — discard_client= → discord_client=
│   └── test_screener.py:230 — score_stock(None) 반환값 검증 로직 수정
└── 검증: pytest tests/ → 412 passed, 0 failed
```

**예상 테스트: 0 신규, 6 수정**

---

## 단계 1: BotLifecycle 공통 클래스

### 목표
PID 락, 장시간 체크, SIGTERM 핸들링 중복 제거. `run_firefeet.py`, `run_ai_swing_bot.py`, `run_scalper.py` 3곳에 동일 로직이 반복.

### 테스트 파일: `tests/test_bot_lifecycle.py` (신규)

```
단계 1: BotLifecycle
├── 회귀 테스트
│   ├── test_existing_run_scripts_import: 기존 run_*.py가 import 에러 없이 로드되는지 (test_bot_lifecycle.py)
│   └── test_trader_init_unchanged: FirefeetTrader/SwingTrader/ScalpEngine 초기화 시그니처 불변 (test_bot_lifecycle.py)
├── 신규 테스트
│   ├── test_pid_lock_creates_file: PID 파일이 생성되고 현재 PID가 기록되는지 (test_bot_lifecycle.py)
│   ├── test_pid_lock_blocks_duplicate: 이미 실행 중인 PID가 있으면 SystemExit 발생 (test_bot_lifecycle.py)
│   ├── test_pid_lock_cleans_zombie: 죽은 PID 파일이 있으면 덮어쓰기 (test_bot_lifecycle.py)
│   ├── test_pid_cleanup_on_exit: 정상 종료 시 PID 파일 제거 (test_bot_lifecycle.py)
│   ├── test_sigterm_triggers_graceful_shutdown: SIGTERM 수신 시 stop() 호출 (test_bot_lifecycle.py)
│   ├── test_is_market_hours_returns_true_during_trading: 09:00~15:30 KST → True (test_bot_lifecycle.py)
│   ├── test_is_market_hours_returns_false_outside: 15:31 KST → False (test_bot_lifecycle.py)
│   ├── test_is_market_hours_weekend_returns_false: 토요일/일요일 → False (test_bot_lifecycle.py)
│   └── test_lifecycle_context_manager: with BotLifecycle() as bot: 사용 시 enter/exit 동작 (test_bot_lifecycle.py)
└── 통합 테스트
    ├── test_scalper_uses_bot_lifecycle: run_scalper가 BotLifecycle을 사용하는지 (integration/test_lifecycle_integration.py)
    └── test_swing_bot_uses_bot_lifecycle: run_ai_swing_bot이 BotLifecycle을 사용하는지 (integration/test_lifecycle_integration.py)
```

### 필요 fixture/mock
- `tmp_pid_file` -- `tmp_path` 기반 PID 파일 경로
- `mock_kst_time(hour, minute, weekday)` -- KST 시각 모킹 헬퍼 (conftest.py에 추가)

**예상 테스트: 11건 신규**

---

## 단계 2: KIS DataService + TTL 캐시

### 목표
`MockKISManager`의 `get_current_price()`, `get_daily_ohlc()` 등을 DataService 레이어로 감싸고 TTL 캐시 적용. API 호출 횟수 최소화.

### 테스트 파일: `tests/test_data_service.py` (신규)

```
단계 2: KIS DataService + TTL Cache
├── 회귀 테스트
│   ├── test_manager_api_unchanged: KISManager의 기존 public API가 동일 시그니처 유지 (test_data_service.py)
│   ├── test_trader_works_with_data_service: FirefeetTrader가 DataService 경유해도 동일 동작 (test_trader.py 추가)
│   └── test_scalp_engine_works_with_data_service: ScalpEngine이 DataService 경유해도 동일 동작 (integration/test_scalp_engine_flow.py 추가)
├── 신규 테스트
│   ├── test_cache_hit_returns_same_object: 동일 키 + TTL 이내 → 캐시 히트, API 미호출 (test_data_service.py)
│   ├── test_cache_miss_after_ttl_expiry: TTL 초과 후 → 캐시 미스, API 재호출 (test_data_service.py)
│   ├── test_cache_isolation_by_key: 다른 종목코드 → 별도 캐시 엔트리 (test_data_service.py)
│   ├── test_cache_invalidate_clears_entry: 수동 무효화 시 다음 호출이 API 재호출 (test_data_service.py)
│   ├── test_cache_size_limit: 캐시 엔트리가 max_size 초과 시 LRU 방출 (test_data_service.py)
│   ├── test_get_current_price_delegates_to_manager: DataService.get_price()가 내부적으로 manager.get_current_price() 호출 (test_data_service.py)
│   ├── test_get_ohlc_delegates_to_manager: DataService.get_ohlc()가 내부적으로 manager.get_daily_ohlc() 호출 (test_data_service.py)
│   ├── test_api_failure_returns_cached_stale: API 에러 시 만료된 캐시라도 반환 (graceful degradation) (test_data_service.py)
│   └── test_concurrent_cache_access_thread_safe: 2 스레드 동시 접근 시 데이터 무결성 (test_data_service.py)
└── 통합 테스트
    ├── test_data_service_with_real_trader_flow: DataService → Trader → BUY 전체 플로우 (integration/test_buy_sell_flow.py 추가)
    └── test_cache_reduces_api_calls_in_loop: 10회 루프에서 API 호출이 1~2회로 줄어드는지 (test_data_service.py)
```

### 필요 fixture/mock
- `MockDataService` -- `tests/mocks/mock_data_service.py` 신규
- `data_service` fixture -- conftest.py에 추가

**예상 테스트: 12건 신규, 3건 회귀**

---

## 단계 3: FirefeetTrader 분해 (Portfolio/Risk/Execution)

### 목표
FirefeetTrader(~600줄)를 PortfolioManager, RiskGuard, ExecutionEngine 3개로 분리.

### 테스트 파일: `tests/test_portfolio.py`, `tests/test_risk_guard.py`, `tests/test_execution_engine.py` (모두 신규)

```
단계 3: FirefeetTrader 분해
├── 회귀 테스트
│   ├── test_trader_public_api_compat: FirefeetTrader의 기존 public 메서드가 동일하게 동작 (test_trader.py 기존 23건 전부)
│   ├── test_swing_trader_inherits_correctly: SwingTrader가 분해 후에도 동일 동작 (test_swing_trader.py 기존 36건 전부)
│   └── test_integration_buy_sell_unchanged: 통합 매수/매도 플로우 불변 (integration/test_buy_sell_flow.py 기존 4건)
├── 신규 테스트 — PortfolioManager (test_portfolio.py)
│   ├── test_sync_portfolio_from_balance: 잔고 API → portfolio dict 동기화
│   ├── test_add_position_updates_portfolio: 매수 후 포지션 추가
│   ├── test_remove_position_after_sell: 매도 후 포지션 제거
│   ├── test_held_codes_list: 보유 종목 코드 목록 반환
│   ├── test_position_pnl_calculation: 개별 포지션 수익률 계산
│   ├── test_total_exposure_amount: 총 투자 금액 합산
│   └── test_portfolio_empty_after_full_sell: 전량 매도 후 빈 포트폴리오
├── 신규 테스트 — RiskGuard (test_risk_guard.py)
│   ├── test_max_holdings_blocks_new_buy: max_holdings 초과 시 매수 거부
│   ├── test_daily_loss_limit_blocks_buy: 일일 손실 한도 도달 시 매수 거부
│   ├── test_consecutive_sl_brake_activates: 3연속 SL 후 브레이크 활성화
│   ├── test_sl_brake_expires_after_cooldown: 쿨다운 시간 후 브레이크 해제
│   ├── test_no_rebuy_after_sell_same_day: 당일 매도 종목 재매수 금지
│   ├── test_rebuy_allowed_if_profitable: 수익 매도 후 재매수 허용 (설정에 따라)
│   ├── test_max_position_amount_clamps_qty: 최대 포지션 금액 초과 시 수량 제한
│   ├── test_budget_exhausted_blocks_buy: 예산 소진 시 매수 거부
│   └── test_risk_check_passes_all_conditions: 모든 조건 통과 시 매수 허용
├── 신규 테스트 — ExecutionEngine (test_execution_engine.py)
│   ├── test_buy_places_order_via_manager: 매수 주문이 KIS API로 전달
│   ├── test_sell_take_profit: TP 도달 시 매도 주문
│   ├── test_sell_stop_loss: SL 도달 시 매도 주문
│   ├── test_sell_eod_closes_position: 장 마감 전 강제 매도
│   ├── test_order_failure_does_not_crash: 주문 실패 시 graceful 처리
│   └── test_partial_fill_handling: 부분 체결 시 나머지 수량 추적
└── 통합 테스트
    ├── test_portfolio_risk_execution_pipeline: Portfolio → RiskGuard.check() → Execution.buy() 파이프라인 (integration/test_trader_decomposition.py)
    └── test_decomposed_trader_matches_monolith: 분해 전/후 동일 시나리오에 동일 결과 (integration/test_trader_decomposition.py)
```

### 수수료 정확성 테스트 (실매매 안전성 최우선)

```
├── 수수료 테스트 (test_execution_engine.py에 포함)
│   ├── test_buy_fee_is_0_015_pct: 매수 수수료 = amount * 0.00015
│   ├── test_sell_fee_includes_tax: 매도 수수료 = amount * (0.00015 + 0.0018)
│   ├── test_roundtrip_fee_is_0_21_pct: 왕복 수수료 ~0.21% 검증
│   ├── test_fee_truncated_to_int: 수수료 원 단위 절사 (int())
│   └── test_fee_consistent_across_all_paths: TradeLogger/Trader/ExecutionEngine 모두 동일 수수료 계산
```

### 필요 fixture/mock
- `portfolio_manager` fixture -- conftest.py에 추가
- `risk_guard` fixture -- conftest.py에 추가
- `execution_engine` fixture -- conftest.py에 추가

**예상 테스트: 25건 신규, 63건 회귀 (기존 테스트가 그대로 통과해야 함)**

---

## 단계 4: firefeet.db + Background Writer (SQLite WAL)

### 목표
CSV 로깅을 SQLite WAL 모드 DB로 교체. queue.Queue + BackgroundWriter 스레드로 비동기 쓰기.

### 테스트 파일: `tests/test_firefeet_db.py`, `tests/test_background_writer.py` (모두 신규)

```
단계 4: firefeet.db + Background Writer
├── 회귀 테스트
│   ├── test_trade_logger_api_unchanged: TradeLogger.log_buy/log_sell/log_scalp_buy/log_scalp_sell 시그니처 불변 (test_scalp_trade_logger.py 기존 테스트)
│   └── test_csv_30col_still_works: 기존 CSV 30컬럼 호환 유지 (integration/test_scalp_engine_flow.py::TestCSVEndToEnd)
├── 신규 테스트 — DB 스키마 (test_firefeet_db.py)
│   ├── test_db_creates_tables_on_init: DB 초기화 시 trades/decisions 테이블 생성
│   ├── test_db_wal_mode_enabled: PRAGMA journal_mode = WAL 확인
│   ├── test_insert_trade_record: trade 레코드 삽입 + 조회
│   ├── test_insert_decision_record: decision 레코드 삽입 + 조회
│   ├── test_schema_matches_csv_header: DB 컬럼이 CSV_HEADER 30컬럼과 1:1 매핑
│   └── test_db_in_tmp_path: tmp_path에 DB 생성 가능 (테스트 격리)
├── 신규 테스트 — BackgroundWriter (test_background_writer.py)
│   ├── test_put_nowait_does_not_block: queue.put_nowait() 호출이 즉시 반환 (~0ms)
│   ├── test_writer_thread_consumes_queue: 큐에 넣은 레코드가 DB에 기록됨
│   ├── test_writer_handles_queue_empty_gracefully: 빈 큐에서 timeout 시 에러 없음
│   ├── test_writer_shutdown_flushes_remaining: stop() 호출 시 큐 잔여 레코드 모두 flush
│   ├── test_writer_survives_db_write_error: DB 쓰기 실패 시 스레드 죽지 않음 (로그만)
│   └── test_queue_full_drops_oldest: 큐 용량 초과 시 최신 레코드 우선 (또는 경고)
├── 동시성 테스트
│   ├── test_two_processes_concurrent_write: 2개 프로세스 동시 WAL 쓰기 → 데이터 손실 없음 (test_firefeet_db.py)
│   ├── test_read_while_write: Writer가 쓰는 중에 Reader가 읽기 가능 (WAL) (test_firefeet_db.py)
│   └── test_writer_thread_does_not_block_main_loop: 메인 루프 1.5초 주기에 Writer가 영향 없음 (test_background_writer.py)
├── 핫패스 성능 테스트
│   ├── test_put_nowait_under_1ms: put_nowait() 호출 시간 < 1ms (test_background_writer.py)
│   └── test_1000_writes_under_1_second: 1000건 비동기 쓰기가 1초 이내 큐 등록 (test_background_writer.py)
└── 통합 테스트
    ├── test_trade_logger_writes_to_db: TradeLogger → BackgroundWriter → DB 전체 흐름 (integration/test_db_integration.py)
    └── test_scalp_buy_sell_recorded_in_db: 스캘핑 매수/매도 → DB 레코드 확인 (integration/test_db_integration.py)
```

### 필요 fixture/mock
- `firefeet_db` fixture -- `tmp_path` 기반 SQLite DB (conftest.py에 추가)
- `background_writer` fixture -- 테스트용 BackgroundWriter (conftest.py에 추가)
- `MockBackgroundWriter` -- `tests/mocks/mock_db.py` 신규 (큐 동작만 시뮬레이션)

**예상 테스트: 17건 신규, 2건 회귀**

---

## 단계 5: decisions 로깅 (status 관리)

### 목표
AI 판단을 decisions 테이블에 기록. status 전이: PENDING -> FILLED / FAILED / PARTIAL / EXPIRED.

### 테스트 파일: `tests/test_decisions.py` (신규)

```
단계 5: decisions 로깅
├── 회귀 테스트
│   ├── test_ai_swing_agent_returns_same_format: AISwingAgent.analyze_trading_opportunity() 반환 형식 불변 (test_ai_swing_agent.py 기존 테스트)
│   └── test_trader_buy_sell_unaffected_by_decisions_log: decisions 로깅 추가가 매매 로직에 영향 없음 (test_trader.py)
├── 신규 테스트 — Status 전이 (test_decisions.py)
│   ├── test_new_decision_starts_as_pending: 새 decision은 status=PENDING
│   ├── test_pending_to_filled_on_order_success: 주문 성공 → FILLED
│   ├── test_pending_to_failed_on_order_failure: 주문 실패 → FAILED
│   ├── test_pending_to_partial_on_partial_fill: 부분 체결 → PARTIAL
│   ├── test_pending_to_expired_on_timeout: 일정 시간 후 미체결 → EXPIRED
│   ├── test_invalid_transition_raises_error: FILLED → PENDING 역전이 불가
│   ├── test_status_transition_is_idempotent: 동일 전이 2회 호출 시 에러 없음
│   └── test_all_statuses_queryable: DB에서 status별 필터 조회
├── 신규 테스트 — Decision 레코드 무결성 (test_decisions.py)
│   ├── test_decision_stores_ai_output: confidence, reasoning, strategy_type 등 AI 출력 전체 저장
│   ├── test_decision_links_to_order: order_no로 trades 테이블과 조인 가능
│   ├── test_decision_timestamp_is_kst: 타임스탬프가 KST 기준
│   └── test_wait_decision_recorded: WAIT 판단도 기록 (매매 안 하는 판단도 추적)
├── 주문 실패 시나리오 (실매매 안전성)
│   ├── test_api_timeout_marks_failed: KIS API 타임아웃 → FAILED + 에러 메시지 기록 (test_decisions.py)
│   ├── test_insufficient_margin_marks_failed: 증거금 부족 → FAILED + 사유 기록 (test_decisions.py)
│   └── test_partial_fill_records_filled_qty: 부분 체결 시 실제 체결 수량 기록 (test_decisions.py)
└── 통합 테스트
    ├── test_ai_decision_to_db_flow: AISwingAgent → decision DB 기록 → 주문 → status 업데이트 (integration/test_decisions_integration.py)
    └── test_decisions_query_daily_summary: 당일 decisions 요약 조회 (총 건수, BUY/SELL/WAIT 비율) (integration/test_decisions_integration.py)
```

### 필요 fixture/mock
- `decisions_db` fixture -- decisions 테이블이 있는 tmp DB (conftest.py에 추가)
- `MockOrderResult` -- 주문 결과 시뮬레이션 (성공/실패/부분체결/타임아웃)

**예상 테스트: 17건 신규, 2건 회귀**

---

## 단계 6: PostTradeCalibrator (conf 교정, 시그널 가중치)

### 목표
과거 거래 결과로 confidence threshold와 시그널 가중치를 자동 보정. 과적합 방지 안전장치 필수.

### 테스트 파일: `tests/test_calibrator.py` (신규)

```
단계 6: PostTradeCalibrator
├── 회귀 테스트
│   ├── test_scalp_strategy_default_weights_unchanged: 보정 전 기본 가중치가 기존과 동일 (test_scalp_strategy.py)
│   ├── test_confidence_threshold_default: 보정 전 기본 conf threshold가 기존과 동일 (test_scalp_strategy.py)
│   └── test_existing_trades_still_score_same: 기존 시그널 점수 계산이 변하지 않음 (test_scalp_signals.py)
├── 신규 테스트 — 보정 로직 (test_calibrator.py)
│   ├── test_calibrate_increases_weight_for_profitable_signal: 수익 시그널 가중치 증가
│   ├── test_calibrate_decreases_weight_for_losing_signal: 손실 시그널 가중치 감소
│   ├── test_calibrate_adjusts_confidence_threshold: 승률 기반 conf threshold 조정
│   ├── test_calibrate_requires_minimum_trades: 최소 거래 수(예: 20) 미만이면 보정 안 함
│   ├── test_calibrate_with_empty_history_returns_defaults: 거래 이력 없으면 기본값 유지
│   └── test_calibrate_output_format: 반환값이 {weights: {}, threshold: float} 형식
├── 교정 안전성 (과적합 방지)
│   ├── test_weight_clamp_min_5_max_50: 가중치가 [5, 50] 범위로 클램핑 (test_calibrator.py)
│   ├── test_threshold_clamp_min_0_2_max_0_8: threshold가 [0.2, 0.8] 범위로 클램핑 (test_calibrator.py)
│   ├── test_single_outlier_does_not_swing_weights: 극단적 1건이 가중치를 급변시키지 않음 (test_calibrator.py)
│   ├── test_weight_change_per_iteration_limited: 1회 보정 시 가중치 변동 폭 제한 (예: +-5%) (test_calibrator.py)
│   ├── test_total_weights_sum_to_100: 보정 후 가중치 합이 100 유지 (test_calibrator.py)
│   └── test_calibrator_rollback_on_degradation: 보정 결과가 기존보다 나쁘면 롤백 (test_calibrator.py)
└── 통합 테스트
    ├── test_calibrator_reads_from_db: decisions DB에서 거래 이력을 읽어 보정 (integration/test_calibrator_integration.py)
    └── test_calibrator_writes_to_config: 보정 결과가 설정 파일에 반영 (integration/test_calibrator_integration.py)
```

### 필요 fixture/mock
- `sample_trade_history` fixture -- 20+건의 거래 이력 (승/패 혼합)
- `calibrator` fixture -- PostTradeCalibrator(trade_history, default_weights)

**예상 테스트: 14건 신규, 3건 회귀**

---

## 단계 7: 온도 -> 국면 벡터 확장

### 목표
단일 스칼라 온도(int)를 다차원 국면 벡터로 확장. 기존 소비자(`strategy.apply_temperature()`, `trader._load_trading_rules()`, `ScalpEngine`)가 여전히 동작해야 함.

### 테스트 파일: `tests/test_regime_vector.py` (신규)

```
단계 7: 온도 → 국면 벡터
├── 회귀 테스트 (하위호환 최우선)
│   ├── test_temperature_int_still_works: 기존 int 온도를 받는 코드가 에러 없음 (test_market_temperature.py)
│   ├── test_apply_temperature_legacy_format: strategy.apply_temperature({"temperature": 80, "level": "HOT"}) 불변 (test_strategy.py)
│   ├── test_trading_rules_override_with_legacy: trading_rules의 온도 오버라이드가 기존대로 동작 (test_trader.py)
│   ├── test_scalp_strategy_selector_with_legacy: StrategySelector가 기존 온도 레벨로 동작 (test_scalp_strategy_selector.py)
│   └── test_integration_temperature_to_strategy: 통합: 온도 → 전략 파이프라인 불변 (integration/test_buy_sell_flow.py)
├── 신규 테스트 — 국면 벡터 구조 (test_regime_vector.py)
│   ├── test_regime_vector_has_required_dims: 벡터에 trend, volatility, liquidity, sentiment 차원 존재
│   ├── test_regime_vector_from_temperature: 기존 온도 결과로부터 국면 벡터 생성
│   ├── test_regime_vector_normalization: 각 차원이 [-100, 100] 범위로 정규화
│   ├── test_regime_vector_to_legacy_temperature: 국면 벡터 → 기존 int 온도 역변환
│   ├── test_regime_vector_to_legacy_level: 국면 벡터 → 기존 HOT/WARM/NEUTRAL/COOL/COLD 레벨 변환
│   └── test_regime_vector_serialization: JSON 직렬화/역직렬화
├── 신규 테스트 — 국면별 전략 매핑 (test_regime_vector.py)
│   ├── test_high_volatility_tightens_sl: 변동성 높음 → SL 축소
│   ├── test_low_liquidity_reduces_position: 유동성 낮음 → 포지션 축소
│   ├── test_strong_trend_increases_tp: 추세 강함 → TP 확대
│   └── test_negative_sentiment_raises_k: 감성 부정적 → k 값 상승 (보수적)
├── 하위호환 테스트 (기존 온도 소비자)
│   ├── test_trader_accepts_regime_vector: FirefeetTrader가 국면 벡터를 받아 처리 (test_regime_vector.py)
│   ├── test_swing_trader_accepts_regime_vector: SwingTrader가 국면 벡터를 받아 처리 (test_regime_vector.py)
│   ├── test_scalp_engine_accepts_regime_vector: ScalpEngine이 국면 벡터를 받아 처리 (test_regime_vector.py)
│   └── test_regime_vector_backward_compat_dict: 국면 벡터 dict에 "temperature" + "level" 키가 여전히 존재 (test_regime_vector.py)
└── 통합 테스트
    ├── test_full_regime_pipeline: MacroModule + SentimentModule + EconModule → 국면 벡터 → Strategy (integration/test_regime_integration.py)
    └── test_regime_transition_mid_session: 장 중 국면 변화 → 전략 파라미터 동적 갱신 (integration/test_regime_integration.py)
```

### 필요 fixture/mock
- `regime_vector` fixture -- 기본 국면 벡터 (NEUTRAL 상태)
- `hot_regime_vector` / `cold_regime_vector` -- 극단 시나리오용

**예상 테스트: 18건 신규, 5건 회귀**

---

## 트레이딩 시스템 특수 테스트 (Cross-cutting)

마이그레이션 전 단계에 걸쳐 적용되는 공통 테스트. 별도 파일로 관리.

### 테스트 파일: `tests/test_trading_safety.py` (신규)

```
실매매 안전성 테스트 (최고 우선순위)
├── 수수료 일관성
│   ├── test_fee_rate_constants_match_docs: BUY_FEE_RATE=0.00015, SELL_FEE_RATE=0.00015, SELL_TAX_RATE=0.0018
│   ├── test_roundtrip_fee_all_modules: TradeLogger, Trader, ScalpEngine 모두 동일 수수료율
│   └── test_fee_edge_case_1won_stock: 최소 금액(1원) 주식의 수수료 = 0 (절사)
├── 주문 실패 시나리오
│   ├── test_order_timeout_no_position_added: API 타임아웃 시 portfolio에 유령 포지션 추가 안 됨
│   ├── test_partial_fill_correct_qty: 부분 체결 시 남은 수량 정확히 추적
│   ├── test_insufficient_margin_no_crash: 증거금 부족 응답 시 예외 없이 스킵
│   └── test_network_error_retry_then_skip: 네트워크 에러 시 재시도 후 스킵
├── 데이터 정합성
│   ├── test_db_trade_matches_portfolio: DB의 trade 레코드와 portfolio 상태 일치
│   └── test_no_orphan_decisions: 모든 decision 레코드가 유효한 status를 가짐
└── 포지션 안전성
    ├── test_no_negative_qty_in_portfolio: 포트폴리오에 음수 수량 불가
    ├── test_sell_qty_not_exceed_held: 매도 수량이 보유 수량 초과 불가
    └── test_double_sell_prevented: 동일 종목 동시 매도 주문 방지
```

**예상 테스트: 12건 신규**

---

## 전체 요약

### 단계별 예상 테스트 수

| 단계 | 신규 | 회귀 | 합계 | 파일 |
|------|------|------|------|------|
| 0: Baseline Fix | 0 | 6 (수정) | 6 | 기존 4파일 수정 |
| 1: BotLifecycle | 11 | 0 | 11 | test_bot_lifecycle.py, integration/test_lifecycle_integration.py |
| 2: DataService | 12 | 3 | 15 | test_data_service.py, mocks/mock_data_service.py |
| 3: Trader 분해 | 25 | 63 | 88 | test_portfolio.py, test_risk_guard.py, test_execution_engine.py |
| 4: DB + Writer | 17 | 2 | 19 | test_firefeet_db.py, test_background_writer.py, mocks/mock_db.py |
| 5: decisions | 17 | 2 | 19 | test_decisions.py, integration/test_decisions_integration.py |
| 6: Calibrator | 14 | 3 | 17 | test_calibrator.py, integration/test_calibrator_integration.py |
| 7: 국면 벡터 | 18 | 5 | 23 | test_regime_vector.py, integration/test_regime_integration.py |
| Cross-cut: 안전성 | 12 | 0 | 12 | test_trading_safety.py |
| **합계** | **126** | **84** | **210** | **12 신규 파일** |

### 마이그레이션 후 목표

| 항목 | 현재 | 목표 |
|------|------|------|
| 총 테스트 수 | 412 | ~540 (+126) |
| 테스트 있는 모듈 비율 | 24.6% | ~60% |
| 깨진 테스트 | 6 | 0 |
| 통합 테스트 | 2파일 | 8파일 |
| 수수료 테스트 | 0 | 5+ |
| 동시성 테스트 | 0 | 4+ |
| 성능 테스트 | 0 | 3+ |

### 신규 Fixture/Mock 필요 목록

**conftest.py 추가 fixtures:**
```python
# 단계 1
@pytest.fixture
def tmp_pid_file(tmp_path):
    """PID 파일 경로 (tmp_path 기반)."""
    return str(tmp_path / "test_bot.pid")

@pytest.fixture
def mock_kst_time():
    """KST 시각 모킹 팩토리."""
    def _make(hour, minute, weekday=0):
        # weekday: 0=Monday ... 6=Sunday
        from datetime import datetime, timezone, timedelta
        KST = timezone(timedelta(hours=9))
        # 2026-03-02 = Monday
        base = datetime(2026, 3, 2 + weekday, hour, minute, 0, tzinfo=KST)
        return base
    return _make

# 단계 2
@pytest.fixture
def data_service(mock_manager):
    """DataService with mock manager and short TTL."""
    from core.data_service import DataService
    return DataService(mock_manager, ttl_seconds=1)

# 단계 3
@pytest.fixture
def portfolio_manager(mock_manager):
    from core.execution.portfolio import PortfolioManager
    return PortfolioManager(mock_manager)

@pytest.fixture
def risk_guard(trading_settings):
    from core.execution.risk_guard import RiskGuard
    return RiskGuard(settings_path=trading_settings)

@pytest.fixture
def execution_engine(mock_manager, mock_discord):
    from core.execution.execution_engine import ExecutionEngine
    return ExecutionEngine(mock_manager, discord=mock_discord)

# 단계 4
@pytest.fixture
def firefeet_db(tmp_path):
    """Temporary SQLite WAL database."""
    from core.firefeet_db import FirefeetDB
    db_path = str(tmp_path / "firefeet_test.db")
    return FirefeetDB(db_path)

@pytest.fixture
def background_writer(firefeet_db):
    from core.background_writer import BackgroundWriter
    writer = BackgroundWriter(firefeet_db)
    yield writer
    writer.stop()

# 단계 5
@pytest.fixture
def decisions_db(firefeet_db):
    """DB with decisions table initialized."""
    return firefeet_db

# 단계 6
@pytest.fixture
def sample_trade_history():
    """20+ trades with mixed outcomes for calibrator testing."""
    import random
    random.seed(42)
    trades = []
    for i in range(30):
        pnl = random.choice([1, -1]) * random.uniform(1000, 15000)
        trades.append({
            "code": f"00{i:04d}",
            "pnl": pnl,
            "confidence": random.uniform(0.2, 0.9),
            "sig_vwap": random.uniform(0, 100),
            "sig_ob": random.uniform(0, 100),
            "sig_mom": random.uniform(0, 100),
            "sig_vol": random.uniform(0, 100),
            "sig_trend": random.uniform(0, 100),
        })
    return trades

@pytest.fixture
def calibrator(sample_trade_history):
    from core.calibrator import PostTradeCalibrator
    return PostTradeCalibrator(sample_trade_history)

# 단계 7
@pytest.fixture
def regime_vector():
    """기본 국면 벡터 (NEUTRAL)."""
    return {
        "temperature": 0, "level": "NEUTRAL",
        "trend": 0, "volatility": 0,
        "liquidity": 0, "sentiment": 0,
    }
```

**신규 Mock 파일:**
```
tests/mocks/mock_data_service.py   -- MockDataService (캐시 동작 시뮬레이션)
tests/mocks/mock_db.py             -- MockFirefeetDB, MockBackgroundWriter
```

### 실행 순서 (의존성 기반)

```
단계 0 → 단계 1 → 단계 2 → 단계 3 → 단계 4 → 단계 5 → 단계 6 → 단계 7
                                        ↓
                              Cross-cut: 안전성 테스트 (단계 3~5와 병행)
```

각 단계는 **앞 단계의 테스트가 모두 그린**이어야 다음 단계 진행.

### 테스트 실행 커맨드

```bash
# 전체
pytest tests/ -v

# 단계별 확인
pytest tests/test_bot_lifecycle.py -v                      # 단계 1
pytest tests/test_data_service.py -v                       # 단계 2
pytest tests/test_portfolio.py tests/test_risk_guard.py tests/test_execution_engine.py -v  # 단계 3
pytest tests/test_firefeet_db.py tests/test_background_writer.py -v  # 단계 4
pytest tests/test_decisions.py -v                          # 단계 5
pytest tests/test_calibrator.py -v                         # 단계 6
pytest tests/test_regime_vector.py -v                      # 단계 7

# 회귀 확인 (기존 테스트 전부)
pytest tests/test_trader.py tests/test_swing_trader.py tests/test_strategy.py tests/test_scalp_strategy.py -v

# 통합 테스트만
pytest tests/integration/ -v -m integration

# 안전성 테스트만
pytest tests/test_trading_safety.py -v

# 성능 테스트 (시간 제한)
pytest tests/test_background_writer.py -v -k "performance or under_1ms or under_1_second"
```

### 우선순위 기준

```
실매매 안전성 > 데이터 정합성 > 성능 > 하위호환
     ↑              ↑           ↑        ↑
 수수료/주문실패  status전이  핫패스   국면벡터
 (단계3,5)       (단계5)    (단계4)   (단계7)
```
