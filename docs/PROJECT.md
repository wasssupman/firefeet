# Firefeet — 한국 주식 AI 자동매매 시스템

> KIS(한국투자증권) API 기반 변동성 돌파 전략 자동매매 + 다중 소스 AI 분석 리포트 시스템

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [기술 스택](#2-기술-스택)
3. [프로젝트 구조](#3-프로젝트-구조)
4. [아키텍처](#4-아키텍처)
5. [핵심 모듈 상세](#5-핵심-모듈-상세)
6. [매매 전략](#6-매매-전략-volatility-breakout)
7. [분석 엔진](#7-분석-엔진)
8. [리포트 시스템](#8-리포트-시스템)
9. [설정 파일 가이드](#9-설정-파일-가이드)
10. [실행 방법](#10-실행-방법)
11. [데이터 흐름](#11-데이터-흐름)
12. [로드맵](#12-로드맵)

---

## 1. 프로젝트 개요

### 목적

**Firefeet**은 한국 주식 시장(KOSPI/KOSDAQ)에서 자동 매매를 수행하는 트레이딩 봇입니다. 기술적 매매 전략(변동성 돌파)을 핵심 엔진으로 사용하면서, 글로벌 거시 지표·경제 일정·수급·뉴스·커뮤니티 감성 등 다중 소스 분석을 종합하여 투자 인텔리전스를 제공합니다.

### 핵심 기능

| 기능 | 설명 |
|------|------|
| **자동매매** | 변동성 돌파 전략 기반 실시간 매수/매도 실행 |
| **동적 종목 스캔** | 거래량 상위 종목 자동 탐색 (5분 주기) |
| **글로벌 매크로 분석** | 미 3대 지수, 환율, VIX, 채권, 원자재, 크립토 |
| **수급 분석** | 외국인/기관 3일 순매수 추이 |
| **경제 일정 추적** | MarketWatch 경제 지표 일정 파싱 |
| **커뮤니티 감성 분석** | Reddit(WSB, r/stocks) 트렌딩 종목·감성 |
| **뉴스 모니터링** | 네이버 금융 뉴스 스크래핑 + 키워드 알림 |
| **AI 종합 분석** | Claude API 기반 종합 투자 리포트 생성 |
| **정기 리포트** | 시간대별 자동 분석 → Discord 전송 |
| **대시보드** | Streamlit 기반 웹 대시보드 |

---

## 2. 기술 스택

### 언어 & 런타임
- **Python 3** (약 2,900줄)

### 외부 API
| API | 용도 |
|-----|------|
| **KIS (한국투자증권)** | 시세 조회, 주문 실행, 잔고 조회 (REAL/PAPER 모드) |
| **yfinance** | 미국 지수, 환율, 원자재, 크립토 데이터 |
| **PRAW (Reddit API)** | 투자 서브레딧 감성 분석 |
| **Anthropic Claude** | AI 기반 종합 분석 리포트 |
| **Discord Webhook** | 알림 및 리포트 전송 |

### 주요 라이브러리

```
requests          # HTTP 클라이언트
pyyaml            # YAML 설정 파싱
pandas            # 데이터 분석
schedule          # 작업 스케줄링
yfinance          # 글로벌 금융 데이터
praw              # Reddit API
beautifulsoup4    # HTML 파싱
lxml              # XML/HTML 처리
websockets        # WebSocket 지원
anthropic         # Claude AI API
```

---

## 3. 프로젝트 구조

```
firefeet/
├── core/                           # 핵심 비즈니스 로직
│   ├── config_loader.py            # YAML 설정 관리
│   ├── kis_auth.py                 # KIS OAuth2 인증 & 토큰 캐싱
│   ├── kis_manager.py              # KIS API 클라이언트 (시세/주문/잔고)
│   ├── strategy.py                 # 변동성 돌파 전략
│   ├── trader.py                   # 메인 트레이딩 엔진
│   ├── scanner.py                  # 거래량 기반 종목 스캐너
│   ├── macro_analyzer.py           # 글로벌 거시 지표 분석
│   ├── econ_calendar.py            # 경제 일정 파서 (MarketWatch)
│   ├── supply_analyzer.py          # 외국인/기관 수급 분석
│   ├── reddit_analyzer.py          # Reddit 감성 분석
│   ├── news_analyzer.py            # 글로벌 뉴스 분석 (MarketWatch)
│   ├── news_scraper.py             # 네이버 금융 뉴스 스크래핑
│   ├── report_generator.py         # 통합 리포트 생성
│   ├── stock_agent.py              # Claude AI 에이전트
│   └── discord_client.py           # Discord Webhook 클라이언트
│
├── config/                         # 설정 파일
│   ├── secrets.yaml                # API 키 & 인증 정보 (gitignore)
│   ├── secrets_template.yaml       # secrets 템플릿
│   ├── watchlist.yaml              # 관심 종목 리스트 & 스케줄
│   ├── trading_settings.yaml       # 예산 & 리스크 설정
│   ├── macro_config.yaml           # MacroAnalyzer Phase ON/OFF
│   ├── agent_settings.yaml         # AI 에이전트 가중치 & 모델 설정
│   └── econ_calendar.yaml          # 감시 경제 지표 필터
│
├── strategies/                     # 전략 모듈 확장용 (예약)
├── db/                             # DB 저장소 (예약)
├── logs/                           # 로그 파일
├── docs/                           # 문서
│
├── run_firefeet.py                 # 자동매매 봇 (메인 진입점)
├── run_report_bot.py               # 정기 리포트 데몬
├── run_export.py                   # CLI 리포트 내보내기
├── run_news_bot.py                 # 뉴스 알림 봇
├── dashboard.py                    # Streamlit 웹 대시보드
│
├── test_auth.py                    # 인증 테스트
├── test_manager.py                 # KIS API 테스트
├── test_strategy.py                # 전략 테스트
├── test_supply.py                  # 수급 분석 테스트
├── debug_api_response.py           # API 응답 디버깅
│
├── requirements.txt                # Python 의존성
└── .token_cache.json               # OAuth 토큰 캐시
```

---

## 4. 아키텍처

### 전체 시스템 구성도

```
┌──────────────────────────────────────────────────────────┐
│                      진입점 (Entry Points)                │
│                                                          │
│  run_firefeet.py    run_report_bot.py    run_news_bot.py │
│  (자동매매)          (정기 리포트)         (뉴스 알림)      │
│  run_export.py      dashboard.py                         │
│  (CLI 내보내기)      (웹 대시보드)                         │
└───────┬──────────────────┬─────────────────┬─────────────┘
        │                  │                 │
┌───────▼──────────────────▼─────────────────▼─────────────┐
│                    핵심 엔진 (Core)                        │
│                                                           │
│  FirefeetTrader ─── VolatilityBreakoutStrategy            │
│       │                    │                              │
│  StockScanner         KISManager ◄── KISAuth              │
│       │                    │                              │
│  ReportGenerator ──── StockAgent (Claude AI)              │
│       │                    │                              │
│  MacroAnalyzer    EconCalendar    SupplyAnalyzer          │
│  RedditAnalyzer   NewsAnalyzer    NewsScraper             │
└───────┬──────────────────┬─────────────────┬─────────────┘
        │                  │                 │
┌───────▼──────────────────▼─────────────────▼─────────────┐
│                  데이터 소스 (External)                     │
│                                                           │
│  KIS API     yfinance     Reddit      MarketWatch         │
│  (한국 시세)  (미국/글로벌)  (감성)      (뉴스/경제일정)      │
│                                                           │
│  네이버금융    Claude API    Discord Webhook               │
│  (한국 뉴스)   (AI 분석)     (알림 전송)                    │
└───────────────────────────────────────────────────────────┘
```

### 매매 흐름 (Trading Flow)

```
StockScanner                FirefeetTrader              VolatilityBreakoutStrategy
    │                            │                              │
    │  get_top_volume_stocks()   │                              │
    ├───────────────────────────►│                              │
    │                            │  check_buy_signal(code)      │
    │                            ├─────────────────────────────►│
    │                            │         BUY Signal           │
    │                            │◄─────────────────────────────┤
    │                            │                              │
    │                            │  place_order(BUY)            │
    │                            ├──────────► KISManager        │
    │                            │                              │
    │                            │  should_sell(price, buy, t)  │
    │                            ├─────────────────────────────►│
    │                            │    SELL_STOP_LOSS / SELL_EOD │
    │                            │◄─────────────────────────────┤
    │                            │                              │
    │                            │  place_order(SELL)           │
    │                            ├──────────► KISManager        │
```

### 리포트 흐름 (Report Flow)

```
run_report_bot.py (schedule)
    │
    ├─ 08:00 ─► MacroAnalyzer.generate_report_section()  ─► Discord
    ├─ 08:15 ─► EconCalendar.generate_report_section()   ─► Discord
    ├─ 08:30 ─► ReportGenerator.generate_full_report()   ─► Discord
    ├─ 12:00 ─► RedditAnalyzer.generate_report_section() ─► Discord
    ├─ 15:40 ─► 종합 리포트 (전체 통합)                    ─► Discord
    └─ SUN 20:00 ─► 주간 종합 리포트                       ─► Discord
```

---

## 5. 핵심 모듈 상세

### 5.1 KISAuth (`core/kis_auth.py`, 97줄)

KIS API OAuth2 인증을 관리합니다.

| 메서드 | 설명 |
|--------|------|
| `get_access_token()` | OAuth 토큰 발급 (캐시 우선) |
| `get_headers(tr_id)` | API 요청 헤더 생성 |

- `.token_cache.json`에 토큰 캐싱 (만료 60초 전 갱신)
- REAL/PAPER 모드별 URL 분기

### 5.2 KISManager (`core/kis_manager.py`, 174줄)

KIS API 호출을 래핑한 클라이언트입니다.

| 메서드 | 설명 |
|--------|------|
| `get_daily_ohlc(code)` | 30일 일봉 OHLC 데이터 (DataFrame 반환) |
| `get_current_price(code)` | 현재가·등락률·거래량 조회 |
| `get_balance()` | 계좌 잔고·보유 종목 조회 |
| `place_order(code, qty, price, type)` | 매수/매도 주문 실행 |

- `OrderType` Enum: `BUY("2")`, `SELL("1")`
- 시장가 주문: `price=0` → `ORD_DVSN="01"`
- 지정가 주문: `price>0` → `ORD_DVSN="00"`

### 5.3 FirefeetTrader (`core/trader.py`, 168줄)

메인 트레이딩 오케스트레이터입니다.

| 메서드 | 설명 |
|--------|------|
| `run_loop()` | 메인 매매 루프 (10초 주기) |
| `process_stock(code, time_str)` | 개별 종목 매수/매도 판단 및 실행 |
| `sync_portfolio()` | KIS 계좌와 로컬 포트폴리오 동기화 |
| `update_target_codes(new_stocks)` | 스캐너 결과로 감시 목록 갱신 |
| `add_target(code, name)` | 관심 종목 추가 |

**상태 관리:**
```
portfolio: {code: {qty, buy_price}}  # 보유 종목 추적
target_codes: [code, ...]           # 감시 대상 목록
stock_names: {code: name}           # 종목명 매핑
```

### 5.4 VolatilityBreakoutStrategy (`core/strategy.py`, 86줄)

래리 윌리엄스(Larry Williams)의 변동성 돌파 전략을 구현합니다.

| 메서드 | 설명 |
|--------|------|
| `get_target_price(code)` | 목표 매수가 계산 |
| `check_buy_signal(code)` | 돌파 매수 신호 확인 |
| `should_sell(price, buy_price, time)` | 매도 조건 확인 (손절/장마감) |

### 5.5 StockScanner (`core/scanner.py`, 91줄)

거래량 기반으로 주목할 종목을 자동 탐색합니다.

| 메서드 | 설명 |
|--------|------|
| `get_top_stocks()` | 거래량 상위 종목 조회 |
| `get_top_volume_stocks(limit)` | 상위 N개 종목 반환 |

- KOSPI 우선, 결과 부족 시 KOSDAQ 병합
- 5분 주기로 `FirefeetTrader.update_target_codes()`에 전달

### 5.6 StockAgent (`core/stock_agent.py`, 127줄)

Claude AI를 활용한 종합 분석 에이전트입니다.

| 메서드 | 설명 |
|--------|------|
| `collect_data(stock_code)` | 모든 분석기에서 데이터 수집 |
| `analyze(stock_code, name)` | Claude에 프롬프트 전송 → 종합 리포트 생성 |

**가중치 기반 프롬프트 구성:**
```
수급(supply): 35%  →  가장 높은 비중
거시경제(macro): 25%
경제지표(econ): 20%
Reddit(reddit): 10%
뉴스(news): 10%
```

최종 의견: 적극 매수 / 매수 / 관망 / 매도 / 적극 매도

---

## 6. 매매 전략 (Volatility Breakout)

### 알고리즘

변동성 돌파 전략은 전일의 가격 변동폭(Range)을 기반으로 당일 목표가를 산출하고, 현재가가 이를 돌파하면 매수합니다.

```
목표가 = 당일 시가 + (전일 고가 - 전일 저가) × K
```

### 매수 조건
```
현재가 ≥ 목표가  →  BUY 신호 발동
```

### 매도 조건
```
(현재가 - 매수가) / 매수가 ≤ -3.0%   →  SELL_STOP_LOSS (손절)
시간 ≥ 15:20 and < 15:30            →  SELL_EOD (장마감 청산)
```

### 파라미터

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| K (변동성 계수) | 0.5 | 돌파 민감도 (0~1, 높을수록 보수적) |
| 손절률 | -3.0% | 최대 허용 손실 |
| 익절률 | 5.0% | 목표 수익 (선택사항) |
| 장마감 시간 | 15:20 | 강제 매도 시점 |

### 예산 관리

| 설정 | 기본값 | 설명 |
|------|--------|------|
| `total_budget` | 1,000,000 KRW | 전체 투자 한도 |
| `max_budget_per_stock` | 200,000 KRW | 종목당 최대 투자금 |

```
매수 수량 = max_budget_per_stock ÷ 현재가  (소수점 버림)
```

### 실행 사이클

```
[10초 주기 메인 루프]
  │
  ├─ 미보유 종목 → check_buy_signal() → BUY 시 시장가 주문
  │
  └─ 보유 종목 → should_sell() → 손절/장마감 시 시장가 매도

[5분 주기 스캔]
  └─ StockScanner → 거래량 TOP 10 → target_codes 갱신
```

---

## 7. 분석 엔진

### 7.1 MacroAnalyzer (`core/macro_analyzer.py`, 274줄)

글로벌 거시 지표를 분석합니다. Phase별로 점진적으로 기능을 확장하는 구조입니다.

#### Phase 1 (MVP) — 현재 활성
| 지표 | 심볼 | 한국 시장 영향 |
|------|------|----------------|
| 나스닥 종합 | `^IXIC` | 코스닥 직결 |
| S&P 500 | `^GSPC` | 코스피 연동 |
| 다우존스 | `^DJI` | 코스피 대형주 |
| 원/달러 환율 | `USDKRW=X` | 환율↑ → 외국인 매도 압력 |
| VIX | `^VIX` | VIX↑ → 리스크 확대 |

#### Phase 2 — 채권 & 원자재
| 지표 | 심볼 | 비고 |
|------|------|------|
| 미 10년물 국채 | `^TNX` | 금리↑ → 성장주 약세 |
| WTI 원유 | `CL=F` | 정유/화학 섹터 |
| 금 | `GC=F` | 안전자산 선호도 |
| 구리 | `HG=F` | 경기 선행지표 |

#### Phase 3 — 심리 & 대체 지표
| 지표 | 심볼 | 비고 |
|------|------|------|
| 비트코인 | `BTC-USD` | 위험자산 심리 |
| 이더리움 | `ETH-USD` | 기술 혁신 테마 |
| 필라델피아 반도체 | `^SOX` | 삼성전자/하이닉스 |
| 닛케이 225 | `^N225` | 아시아 시장 분위기 |
| 항셍 | `^HSI` | 중국 경기 |

#### 종합 시장 점수 (-100 ~ +100)

```python
score = (미지수 평균등락률 × 0.4) - (환율 변동 × 0.3) - (VIX 변동 × 0.3)
```

| 점수 구간 | 시장 판단 | 전략 |
|-----------|-----------|------|
| +60 이상 | 적극 매수 | 공격적 진입 |
| +20 ~ +60 | 매수 우위 | 일반 전략 유지 |
| -20 ~ +20 | 관망/중립 | 현금 비중 유지 |
| -60 ~ -20 | 보수적 | 손절 기준 강화 |
| -60 이하 | 위험/방어 | 매수 중단 |

### 7.2 EconCalendar (`core/econ_calendar.py`, 250줄+)

MarketWatch에서 경제 일정을 스크래핑하여 한국 시간으로 변환합니다.

- ET → KST 시간 변환
- 주요 지표 키워드 필터링 (NFP, CPI, PPI 등)
- `config/econ_calendar.yaml`에서 감시 대상 설정

### 7.3 SupplyAnalyzer (`core/supply_analyzer.py`, 85줄)

외국인·기관 투자자 매매 동향을 분석합니다.

| 메서드 | 설명 |
|--------|------|
| `get_investor_trend(code)` | 투자자별 매매 데이터 조회 |
| `analyze_supply(code)` | 3일 롤링 합계 → 감성 판단 |

**감성 판정:**
```
3일 외국인/기관 순매수 > 0  →  BULLISH
3일 외국인/기관 순매도 < 0  →  BEARISH
그 외                      →  NEUTRAL
```

### 7.4 RedditAnalyzer (`core/reddit_analyzer.py`, 115줄)

Reddit 투자 커뮤니티에서 시장 심리를 수집합니다.

**대상 서브레딧:** r/wallstreetbets, r/stocks, r/investing

**분석 방법:**
1. 트렌딩 티커 추출 (`$NVDA`, `$TSLA` 등 빈도 카운팅)
2. 감성 점수: `(Bullish - Bearish) / (Bullish + Bearish)` → -1.0 ~ 1.0
3. Bullish 키워드: buy, moon, calls, long, green, bull
4. Bearish 키워드: sell, crash, puts, short, red, bear

### 7.5 NewsAnalyzer & NewsScraper

| 모듈 | 소스 | 용도 |
|------|------|------|
| `news_analyzer.py` | MarketWatch | 글로벌 경제 뉴스 (Reddit 불가 시 Fallback) |
| `news_scraper.py` | 네이버 금융 | 한국 종목별 뉴스 스크래핑 + 키워드 필터 |

**뉴스 봇 감시 키워드:** 공시, 계약, 무상증자, 유상증자, 특허, 수주, 개발, 임상, 인수, 합병

---

## 8. 리포트 시스템

### 8.1 정기 스케줄

| 시간 | 내용 | 담당 모듈 |
|------|------|-----------|
| 08:00 | 글로벌 시장 브리핑 | `MacroAnalyzer` |
| 08:15 | 경제 지표 일정 | `EconCalendar` |
| 08:30 | 관심 종목 프리마켓 분석 | `ReportGenerator` |
| 12:00 | Reddit 감성 분석 | `RedditAnalyzer` |
| 15:40 | 장 마감 종합 리포트 | 전체 통합 |
| 일 20:00 | 주간 종합 리포트 | 전체 통합 |

### 8.2 종목 리포트 구성

| 항목 | 데이터 소스 |
|------|-------------|
| 현재가/등락률 | KIS API `get_current_price` |
| 변동성 돌파 신호 | `VolatilityBreakoutStrategy` |
| 수급 동향 (외국인/기관 3일 순매수) | `SupplyAnalyzer` |
| 뉴스 키워드 | `NewsScraper` |
| 종합 의견 (BUY/HOLD/WAIT) | 위 데이터 종합 |

### 8.3 Discord 전송

`DiscordClient`가 Webhook으로 Markdown 형식 리포트를 전송합니다.
- 1,900자 초과 시 자동 분할 전송
- 알림용 `send_alert()`와 리포트용 `send()` 분리

---

## 9. 설정 파일 가이드

### 9.1 `config/secrets.yaml` (인증 정보)

```yaml
# 한국투자증권 API
PROD:
  APP_KEY: "your-prod-app-key"
  APP_SECRET: "your-prod-app-secret"
PAPER:
  APP_KEY: "your-paper-app-key"
  APP_SECRET: "your-paper-app-secret"

CANO: "12345678"          # 계좌번호
ACNT_PRDT_CD: "01"        # 계좌상품코드

# Discord Webhook
DISCORD_WEBHOOK_URL: "https://discord.com/api/webhooks/..."

# Reddit API (선택)
REDDIT:
  CLIENT_ID: "your-reddit-client-id"
  CLIENT_SECRET: "your-reddit-client-secret"

# Claude API (선택)
ANTHROPIC_API_KEY: "your-anthropic-api-key"
```

### 9.2 `config/watchlist.yaml` (관심 종목)

```yaml
watchlist:
  - code: "005930"
    name: "삼성전자"
  - code: "000270"
    name: "기아"
  - code: "035720"
    name: "카카오"
  - code: "105560"
    name: "KB금융"

schedule:
  pre_market: "08:30"
  post_market: "15:40"
  weekly: "SUN 20:00"
```

### 9.3 `config/trading_settings.yaml` (매매 설정)

```yaml
total_budget: 1000000        # 전체 투자 한도 (KRW)
max_budget_per_stock: 200000 # 종목당 최대 투자금 (KRW)
stop_loss_rate: -3.0         # 손절 라인 (%)
take_profit_rate: 5.0        # 익절 라인 (%)
```

### 9.4 `config/macro_config.yaml` (매크로 지표 ON/OFF)

```yaml
phase1:                # MVP 핵심 지표
  us_indices: true
  fx_rate: true
  vix: true
phase2:                # 채권 & 원자재
  bond_yields: false
  commodities: false
phase3:                # 심리 & 대체 지표
  fear_greed: false
  crypto: false
  global_indices: false
phase4:                # 한국 고유 지표
  kospi_futures: false
  program_trading: false
  short_selling: false
```

### 9.5 `config/agent_settings.yaml` (AI 에이전트 설정)

```yaml
weights:
  macro: 0.25        # 거시 경제 (25%)
  econ: 0.20         # 경제 일정 (20%)
  supply: 0.35       # 수급 (35%) ← 최고 비중
  reddit: 0.10       # Reddit (10%)
  news: 0.10         # 뉴스 (10%)

language: "ko"
claude_model: "claude-3-5-sonnet-20240620"
max_tokens: 2000
temperature: 0.2
```

---

## 10. 실행 방법

### 사전 준비

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. 인증 정보 설정
cp config/secrets_template.yaml config/secrets.yaml
# secrets.yaml에 KIS API 키, Discord Webhook URL 등 입력
```

### 실행 커맨드

```bash
# 자동매매 봇 (메인 — 연속 실행)
python3 run_firefeet.py

# 정기 리포트 데몬 (백그라운드)
python3 run_report_bot.py

# 즉시 전체 리포트 1회 실행
python3 run_report_bot.py --now

# CLI 개별 리포트 내보내기
python3 run_export.py macro          # 글로벌 시장 브리핑
python3 run_export.py watchlist      # 관심 종목 분석
python3 run_export.py reddit         # Reddit 감성 분석
python3 run_export.py econ           # 경제 일정
python3 run_export.py all            # 전체 통합 리포트
python3 run_export.py chat 005930 "삼성전자"  # Claude AI 분석

# 뉴스 알림 봇 (연속 실행, 60초 폴링)
python3 run_news_bot.py

# 웹 대시보드
streamlit run dashboard.py

# 테스트/디버그
python3 test_auth.py
python3 test_manager.py
python3 test_strategy.py
python3 test_supply.py
python3 debug_api_response.py
```

---

## 11. 데이터 흐름

### 자동매매 데이터 흐름

```
KIS API
  │
  ├─ 거래량 순위 ──► StockScanner ──► target_codes 갱신
  │
  ├─ 일봉 OHLC ──► VolatilityBreakoutStrategy
  │                    │
  │                    ├─ 목표가 계산
  │                    └─ BUY/SELL 신호 ──► FirefeetTrader
  │                                            │
  ├─ 현재가 ──────────────────────────────────►│
  │                                            │
  ├─ 잔고 조회 ──► 포트폴리오 동기화 ──────────►│
  │                                            │
  └─ 주문 실행 ◄──────────────────────────────┤
                                               │
Discord ◄── 알림 ────────────────────────────┘
```

### 리포트 데이터 흐름

```
yfinance ──────► MacroAnalyzer ──────┐
                                     │
MarketWatch ───► EconCalendar ───────┤
                                     │
KIS API ───────► SupplyAnalyzer ─────┤
                                     ├──► ReportGenerator / StockAgent
Reddit ────────► RedditAnalyzer ─────┤           │
                                     │      Claude API
MarketWatch ───► NewsAnalyzer ───────┤           │
                                     │      종합 리포트
네이버금융 ────► NewsScraper ─────────┘           │
                                          Discord Webhook
```

---

## 12. 로드맵

### 현재 구현 상태

| Phase | 기능 | 상태 |
|-------|------|------|
| Core | 변동성 돌파 자동매매 | ✅ 완료 |
| Core | 동적 종목 스캔 | ✅ 완료 |
| Core | KIS API 연동 (REAL/PAPER) | ✅ 완료 |
| Phase 1 | 미 3대 지수 + 환율 + VIX | ✅ 완료 |
| Phase 1 | 관심 종목 정기 리포트 | ✅ 완료 |
| Phase 1 | Discord 알림 통합 | ✅ 완료 |
| Phase 1 | 경제 일정 추적 | ✅ 완료 |
| Phase 1 | 수급 분석 (외국인/기관) | ✅ 완료 |
| Phase 1 | Reddit 감성 분석 | ✅ 완료 |
| Phase 1 | 뉴스 모니터링 | ✅ 완료 |
| Phase 1 | Claude AI 에이전트 | ✅ 완료 |
| Phase 2 | 채권 금리 (10년물) | 🔧 코드 준비, 설정 OFF |
| Phase 2 | 원자재 (WTI/금/구리) | 🔧 코드 준비, 설정 OFF |
| Phase 3 | 크립토 (BTC/ETH) | 🔧 코드 준비, 설정 OFF |
| Phase 3 | 글로벌 지수 (SOX/닛케이/항셍) | 🔧 코드 준비, 설정 OFF |
| Phase 3 | Fear & Greed Index | 📋 계획 단계 |
| Phase 4 | 코스피 선물 | 📋 계획 단계 |
| Phase 4 | 프로그램 매매 동향 | 📋 계획 단계 |
| Phase 4 | 공매도 비중 | 📋 계획 단계 |
| Phase 4 | 신용잔고 추이 | 📋 계획 단계 |
| — | 백테스팅 프레임워크 | ❌ 미구현 |
| — | 멀티 전략 지원 | ❌ 미구현 |
| — | ML 모델 통합 | ❌ 미구현 |

### 확장 방향

```
Phase 1 (MVP) ✅     Phase 2 🔧         Phase 3 🔧         Phase 4 📋
──────────────────────────────────────────────────────────────────────
미 3대 지수      →   미 국채 금리     →   Fear & Greed    →   코스피 선물
원달러 환율      →   WTI/금/구리      →   BTC/ETH         →   프로그램 매매
VIX              →   천연가스         →   SOX/닛케이/항셍  →   공매도 비중
수급/뉴스/Reddit  →                   →                   →   신용잔고
──────────────────────────────────────────────────────────────────────
             yfinance                   yfinance +           KIS API +
                                        외부 API             KRX 크롤링
```

---

## 부록: 주요 성능 특성

| 항목 | 값 |
|------|-----|
| 메인 루프 주기 | 10초 |
| 종목 스캔 주기 | 5분 |
| 뉴스 폴링 주기 | 60초 |
| API 호출 간 딜레이 | 1~10초 (Rate limit) |
| OAuth 토큰 갱신 | 24시간 (만료 60초 전) |
| 리포트 생성 시간 | ~30-60초 (다중 소스 집계) |
| Discord 메시지 제한 | 1,900자 (자동 분할) |
| 전체 코드 규모 | ~2,900줄 (Python) |
