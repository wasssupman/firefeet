# Firefeet 실행 플로우 가이드

> 각 실행 진입점별 초기화 → 메인 로직 → 종료 흐름을 정리한 문서.

---

## 목차

| # | 스크립트 | 유형 | 설명 |
|---|---------|------|------|
| 1 | `run_firefeet.py` | 상주 봇 | 변동성 돌파 자동매매 (메인) |
| 2 | `run_ai_swing_bot.py` | 상주 봇 | AI 스윙 트레이딩 |
| 3 | `run_scalper.py` | 상주 봇 | WebSocket 실시간 스캘핑 |
| 4 | `run_report_bot.py` | 데몬 | 정기 리포트 스케줄러 |
| 5 | `run_news_bot.py` | 데몬 | 뉴스 키워드 알림 |
| 6 | `run_export.py` | CLI | 리포트 단발 생성/전송 |
| 7 | `run_deep_analysis.py` | CLI | AI 딥 리서치 (장기투자) |
| 8 | `run_batch_reports.py` | CLI | 대량 종목 스크리닝 + 배치 분석 |
| 9 | `dashboard.py` | 웹 | Streamlit 대시보드 |
| 10 | `predict_market.py` | CLI | Gemini 시황 예측 |

---

## 1. run_firefeet.py — 변동성 돌파 자동매매

> PID: `/tmp/firefeet_main.pid` | 모드: REAL | 루프 주기: 10초

### 초기화

```
PID Lock 획득
    │
    ├─ ConfigLoader → secrets.yaml + trading_settings.yaml
    ├─ KISAuth → OAuth2 토큰
    ├─ KISManager(REAL)
    ├─ VolatilityBreakoutStrategy(k=0.5)
    ├─ DiscordClient
    ├─ FirefeetTrader(manager, strategy, discord)
    │   └─ sync_portfolio() → 실계좌 보유종목 동기화
    ├─ StockScanner(primary_fetcher=manager)
    ├─ StockScreener(strategy, discord)
    └─ SupplyAnalyzer
```

### 메인 루프

```
while True:
    │
    ├─ [장외 시간?] ──Yes──→ 일일 상태 초기화 → sleep(60) → continue
    │   │                    (sold_today, daily_pnl, sl_count, temp_done)
    │   No
    │
    ├─ [temp_done == False?] ──Yes──→ 시장 온도 계산 (1회)
    │   │                            MarketTemperature().calculate()
    │   │                            → strategy.apply_temperature()
    │   │                            → k, TP%, SL%, 포지션% 동적 조절
    │   │                            → Discord 전송
    │   │                            → temp_done = True
    │
    ├─ [스캔 주기 도달?] ──Yes──→ Scanner: 거래량 TOP 20 종목 조회
    │   │                         → Screener: 복합 스코어링
    │   │                           (OHLC + 수급 + 현재가, 종목간 0.5s 딜레이)
    │   │                         → bot.update_target_codes(screened)
    │
    ├─ [동기화 주기 5분?] ──Yes──→ bot.sync_portfolio()
    │
    ├─ settings/trading_rules YAML 리로드
    │
    ├─ target_codes에서 sold_today 제외 → current_targets
    │
    ├─ for code in current_targets:
    │   │
    │   ├─ [미보유?] → _process_buy()
    │   │              strategy.check_buy_signal()
    │   │              → _can_buy() 가드:
    │   │                 ├─ 연속 손절 브레이크?
    │   │                 ├─ 일일 손실 한도?
    │   │                 ├─ 재매수 금지 규칙?
    │   │                 └─ 최대 보유 수 초과?
    │   │              → place_order(BUY)
    │   │
    │   └─ [보유중?] → _process_sell()
    │                  strategy.should_sell()
    │                  → SELL_TAKE_PROFIT | SELL_STOP_LOSS | SELL_EOD
    │                  → place_order(SELL)
    │
    ├─ [차단 비율 ≥ 30%?] ──Yes──→ 조기 재스캔 (60초 쿨다운)
    │
    └─ sleep(loop_interval)  ← 기본 10초
```

### 종료

```
KeyboardInterrupt → trade_logger.print_daily_summary() → PID Lock 해제
```

---

## 2. run_ai_swing_bot.py — AI 스윙 트레이딩

> PID: `/tmp/firefeet_ai_swing.pid` | 모드: REAL / `--paper` | 루프 주기: 10~30초

### 초기화

```
PID Lock 획득
    │
    ├─ ConfigLoader → KISAuth → KISManager
    ├─ DiscordClient (paper 모드면 None)
    ├─ MarketTemperature
    ├─ NewsScraper
    ├─ AISwingAgent (Claude API)
    ├─ StockScanner + StockScreener
    ├─ SwingTrader(manager, ai_agent, discord)
    │
    └─ 백그라운드 데몬 스레드 2개:
        ├─ DART 공시 폴링 (30초 간격)
        │   DartAPIClient → DartEventHandler.on_announcement()
        └─ 보유종목 동기화 (10초 간격)
            trader.portfolio → dart_handler.holdings
```

### 메인 루프

```
while True:
    │
    ├─ [장외 시간? (paper가 아닌 경우)] ──Yes──→ sleep(60)
    │
    ├─ [포트폴리오 동기화 주기 10분?] ──Yes──→ trader.sync_portfolio()
    │
    ├─ [스캔 주기 도달?] ──Yes──→ Scanner: 거래량 TOP 15
    │                             → Screener: 스코어링
    │                             → trader.update_target_codes(상위 5종목)
    │
    └─ for code in target_codes:
        │
        └─ trader.process_stock_with_ai(code, time_str, ai_data_provider)
            │
            ai_data_provider(code):
            ├─ OHLC + 수급 + 현재가 (KIS API)
            ├─ 최근 뉴스 5건 (NewsScraper)
            └─ 시장 온도 (MarketTemperature)
            │
            → AISwingAgent가 종합 판단 → 매수/매도/홀드 결정
```

### vs. run_firefeet.py 차이점

| 항목 | firefeet (메인) | ai_swing |
|------|----------------|----------|
| 전략 | 변동성 돌파 (수식 기반) | Claude AI 판단 |
| 데이터 | OHLC + 수급 | OHLC + 수급 + 뉴스 + 온도 |
| 공시 감지 | 없음 | DART 실시간 폴링 |
| 스캐너 | TOP 20 | TOP 15 → 상위 5 |
| 동기화 | 5분 | 10분 |

---

## 3. run_scalper.py — WebSocket 스캘핑

> PID: `/tmp/firefeet_scalper.pid` | 모드: REAL / `--paper` / `--dry-run`

### 초기화

```
PID Lock 획득
    │
    ├─ ConfigLoader → KISAuth
    ├─ KISManager (paper → DummyManager)
    ├─ DiscordClient(webhook_key="DISCORD_SCALP_WEBHOOK_URL")
    ├─ StockScanner
    ├─ KISWebSocket(auth, hts_id, max_subscriptions)
    ├─ ScalpEngine(manager, ws, scanner, discord)
    │
    └─ 기존 미체결 주문 전량 취소
        manager.get_order_status() → cancel_order()
```

### 메인 루프

```
while True:
    │
    ├─ [장외 시간?] ──Yes──→ WebSocket 해제 → engine.reset_daily() → sleep(60)
    │
    ├─ [temp_done == False?] ──Yes──→ 시장 온도 계산 (1회)
    │                                 → engine.apply_temperature()
    │
    ├─ [WebSocket 미접속?] ──Yes──→ ws.connect() + 체결통보 구독
    │                               실패 시 30초 후 재시도
    │
    ├─ [스캔 주기 도달?] ──Yes──→ Scanner: 거래량 TOP N
    │                             → engine.update_targets() → WS 구독 갱신
    │
    ├─ [타겟 없음?] ──Yes──→ 30초 대기 후 즉시 재스캔
    │
    ├─ [틱 데이터 부족?] ──Yes──→ 5초 대기 (최소 30틱 필요)
    │   (tick_buffer.has_enough_data)
    │
    └─ [dry-run?]
        ├─ Yes → _dry_run_cycle(): 시그널 평가만 로깅
        │         (VWAP, 호가압력, 모멘텀, 거래량급증, 마이크로트렌드)
        └─ No  → engine.run(): 실매매 (1.5초 주기)
```

### 종료

```
KeyboardInterrupt / 치명적 오류
    │
    ├─ 잔여 포지션 강제 청산 (_force_exit_all)
    ├─ WebSocket unsubscribe_all() + disconnect()
    ├─ trade_logger.print_daily_summary()
    ├─ engine.print_status()
    ├─ Discord 종료 알림 (일일 손익 + 거래 건수)
    └─ PID Lock 해제
```

---

## 4. run_report_bot.py — 정기 리포트 데몬

> 즉시 실행: `--now` 플래그

### 스케줄

```
08:00 ─→ job_macro()      🌍 글로벌 시장 브리핑
         MacroAnalyzer → generate_report_section() → Discord

08:15 ─→ job_econ()       📅 경제 지표 일정
         EconCalendar → generate_report_section() → Discord

08:30 ─→ job_watchlist()  📊 관심 종목 분석
         KIS 초기화 → ReportGenerator
         → generate_full_report(watchlist, include_macro=False) → Discord

12:00 ─→ job_reddit()     🗣️ Reddit 감성 (CLIENT_ID 없으면 스킵)
         RedditAnalyzer → generate_report_section() → Discord

15:40 ─→ job_full_report()  📝 종합 리포트
일 20:00   Macro + Econ + KIS + Watchlist + Reddit(선택)
           → ReportGenerator.generate_full_report(include_macro=True)
           → Discord
```

### 실행 플로우

```
[--now?] ──Yes──→ job_full_report() → exit

[데몬 모드]
register_schedules()
print_status()
while True:
    schedule.run_pending()
    sleep(30)
```

---

## 5. run_news_bot.py — 뉴스 키워드 알림

> 폴링 주기: 60초

### 감시 키워드

`공시`, `계약`, `무상증자`, `유상증자`, `특허`, `수주`, `개발`, `임상`, `인수`, `합병`

### 실행 플로우

```
NewsScraper() + DiscordClient()
    │
    ├─ 초기 fetch → seen_links 등록 (기존 뉴스 무시)
    ├─ Discord "시스템 시작" 알림
    │
    └─ while True:
        scraper.fetch_news()          ← Naver Finance 스크래핑
        │                               (dd.articleSubject a 셀렉터)
        │                               seen_links로 중복 자동 제거
        │
        scraper.filter_news(KEYWORDS) ← 제목에 키워드 포함 여부
        │
        for alert in alerts:
            discord.send_alert(title, link, keyword)
        │
        sleep(60)
```

---

## 6. run_export.py — CLI 리포트 도구

> 단발 실행 후 종료. 결과를 콘솔 출력 + Discord 전송.

### 서브커맨드 플로우

```
python3 run_export.py <command>

┌─────────┬──────────────────────────────────────────────────────┐
│ macro   │ MacroAnalyzer → generate_report_section() → Discord │
├─────────┼──────────────────────────────────────────────────────┤
│ econ    │ EconCalendar → generate_report_section() → Discord  │
├─────────┼──────────────────────────────────────────────────────┤
│ watchlist│ KIS 초기화 → SupplyAnalyzer(auth)                  │
│         │ → ReportGenerator(manager, supply, strategy)        │
│         │ → generate_full_report(watchlist) → Discord         │
├─────────┼──────────────────────────────────────────────────────┤
│ reddit  │ secrets.yaml에서 REDDIT 설정 확인                    │
│         │ → RedditAnalyzer → generate_report_section()        │
├─────────┼──────────────────────────────────────────────────────┤
│ all     │ Macro + Econ + KIS + Watchlist + Reddit(선택)       │
│         │ → ReportGenerator(전체 주입) → Discord              │
├─────────┼──────────────────────────────────────────────────────┤
│ chat    │ python3 run_export.py chat <코드> [이름]             │
│ <code>  │ StockAgent(auth, loader).analyze(code, name)        │
│         │ → Claude AI 종합 분석 → Discord                     │
├─────────┼──────────────────────────────────────────────────────┤
│ deep    │ python3 run_export.py deep <코드> [이름]             │
│ <code>  │ → run_deep_analysis.run_single() 위임               │
│         │ → 파일 저장 + Discord                               │
└─────────┴──────────────────────────────────────────────────────┘
```

---

## 7. run_deep_analysis.py — AI 딥 리서치

> Claude API 기반 장기투자 종합 분석

### 실행 모드

```
python3 run_deep_analysis.py <코드> <이름> [--sections a,b,c]
python3 run_deep_analysis.py --watchlist
```

### 단일 종목 (run_single) 플로우

```
ConfigLoader → KISAuth → KISManager
DeepAgent() + ReportBuilder(config)
    │
    ├─ data_provider(code):
    │   OHLC + investor_trend + current_price (KIS API)
    │
    ├─ agent.analyze(code, name, sections_filter, data_provider)
    │   └─ Claude API 멀티섹션 분석
    │
    ├─ builder.build(code, name, sections) → 풀 리포트
    ├─ builder.build_summary() → 요약
    │
    ├─ [save_file?] → reports/ 디렉토리에 MD 파일 저장
    ├─ [discord_summary?] → Discord 요약 전송
    └─ [discord_full?] → Discord 전문 전송
```

### 워치리스트 모드

```
watchlist.yaml 로드 → for stock in watchlist: run_single(code, name)
```

---

## 8. run_batch_reports.py — 대량 종목 배치 분석

> 3단계 파이프라인 + CLI 플래그로 단계 제어

### 파이프라인

```
Stage 1: 거래량 스크리닝
    KOSPI + KOSDAQ 거래량 TOP 100 (50+50)
    │
Stage 2: 수급 + 기술적 필터링
    for stock in volume_top:
    ├─ get_investor_trend() → 최근 3일 외국인/기관 순매수
    │   둘 다 매도중이면 탈락
    ├─ get_daily_ohlc() → StockScreener.score_stock()
    │   total_score < 15이면 탈락
    └─ 통과 종목 리스트 생성
    │
Stage 3: AI 테마 필터 + 딥 리서치
    ├─ NewsScraper → 최근 뉴스 10건
    ├─ Claude CLI subprocess 호출
    │   "시장 테마와 가장 부합하는 종목 N개 선정"
    │   → JSON {reasoning, codes} 응답 파싱
    │   (파싱 실패 시 score 순 fallback)
    │
    └─ run_batch_analysis():
        for batch in chunks(stocks, batch_size=3):
            for stock in batch:
                DeepAgent.analyze() → ReportBuilder → 파일 저장
                sleep(15초)  ← 종목 간 쿨다운
            sleep(300초)     ← 배치 간 휴식 (5분)
```

### CLI 플래그

| 플래그 | 동작 |
|--------|------|
| (기본) | Stage 1→2→3 전체 실행 |
| `--no-ai` | Stage 1만, score 순 CSV 출력 |
| `--stage2-only` | Stage 1→2, AI 테마 선별까지만 (MD 출력) |
| `--limit N` | 최종 선정 종목 수 (기본 10) |
| `--batch N` | 배치 크기 (기본 3) |
| `--delay N` | 종목 간 대기 초 (기본 15) |
| `--rest N` | 배치 간 대기 초 (기본 300) |

---

## 9. dashboard.py — Streamlit 대시보드

```
streamlit run dashboard.py
```

### 화면 구성

```
┌──────────────────────────────────────────────────┐
│ 🔥 Firefeet Auto Trading System                 │
├─────────┬────────────────────────────────────────┤
│ Sidebar │  Section 1: Account Status 💰         │
│ ─────── │  ┌─────────────┬──────────────┐       │
│ Mode:   │  │ Total Asset │ Deposit      │       │
│ ○ REAL  │  └─────────────┴──────────────┘       │
│ ○ PAPER │  Holdings DataFrame                   │
│         │                                        │
│ □ Auto  │  Section 2: Supply/Demand 📊          │
│   Refresh│  삼성전자 / SK하이닉스 / 현대차       │
│ (60s)   │  외국인·기관 3일 순매수 + 바차트       │
│         │                                        │
│         │  Section 3: News Alert 📰              │
│         │  (run_news_bot.py 안내만 표시)          │
└─────────┴────────────────────────────────────────┘
```

### 데이터 흐름

```
@st.cache_resource
get_manager(mode) → KISManager + SupplyAnalyzer

Section 1: manager.get_balance() → 총자산, 예수금, 보유종목
Section 2: supply_analyzer.analyze_supply(code) → 수급 데이터 + 차트
Section 3: 정적 안내 텍스트
```

---

## 10. predict_market.py — Gemini 시황 예측

```
python3 predict_market.py
```

### 플로우

```
NewsAnalyzer().fetch_global_news_titles(limit=15)
    │
    └─ 15개 뉴스 헤드라인 수집
       │
       Gemini API (gemini-2.5-flash)
       ├─ 프롬프트: "내일 KOSPI/KOSDAQ 예측"
       │   1. 미 증시/글로벌 이벤트 영향
       │   2. 시초가 예상 분위기
       │   3. 핵심 테마/섹터
       │   4. 종합 투자 의견
       │
       └─ 응답 콘솔 출력

환경변수 필요: GEMINI_API_KEY
```

---

## 공통 패턴 요약

### PID Lock (상주 봇 3종)

| 봇 | PID 파일 |
|----|---------|
| firefeet | `/tmp/firefeet_main.pid` |
| ai_swing | `/tmp/firefeet_ai_swing.pid` |
| scalper | `/tmp/firefeet_scalper.pid` |

`os.kill(old_pid, 0)` 으로 프로세스 생존 확인 → 중복 실행 방지.

### 장 운영시간

| 봇 | 시작 | 종료 | 주말 |
|----|------|------|------|
| firefeet | 09:00 | 15:30 | 제외 |
| ai_swing | 09:00 | 15:20 | 제외 |
| scalper | 09:00 | 15:30 | 제외 |

### 시장 온도 적용 체인

```
MarketTemperature.calculate()
    ├─ MacroModule (40%) — 미 지수, VIX, 환율, 채권
    ├─ SentimentModule (35%) — 뉴스 키워드 감성
    └─ EconModule (25%) — 경제 지표 서프라이즈
    │
    → 가중 합산 → clamp(-100, +100) → 레벨 판정
    │
    ├─ firefeet: strategy.apply_temperature() → k, TP, SL, 포지션% 조절
    ├─ ai_swing: AI 판단 입력 데이터로 전달
    └─ scalper:  engine.apply_temperature() → confidence_threshold 조절
```

### 공통 초기화 스택

```
ConfigLoader → secrets.yaml
    → KISAuth (OAuth2)
        → KISManager (시세/주문/잔고)
```

모든 실매매/리포트 기능이 이 3단계를 공유한다.
