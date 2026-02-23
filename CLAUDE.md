# Firefeet - 한국 주식 자동매매 시스템

## 프로젝트 개요

변동성 돌파 전략(Larry Williams) 기반 한국 주식 자동매매 봇. KIS(한국투자증권) API로 실매매하며, 글로벌 시장 분석 + 뉴스 감성 + 경제 지표를 종합한 **시장 온도**로 전략 파라미터를 동적 조절한다.

## 실행 방법

```bash
# 자동매매 봇 (메인)
python3 run_firefeet.py

# 정기 리포트 데몬 (08:00~15:40 스케줄)
python3 run_report_bot.py
python3 run_report_bot.py --now  # 즉시 1회 실행

# CLI 리포트
python3 run_export.py macro|watchlist|reddit|econ|all
python3 run_export.py chat 005930 "삼성전자"

# 뉴스 알림 봇 (60초 폴링)
python3 run_news_bot.py

# 대시보드
streamlit run dashboard.py

# 거래 로그 조회
python3 -m core.trade_logger

# 시장 온도 단독 실행
python3 -m core.market_temperature
```

## 아키텍처

```
Scanner(거래량 TOP) → Screener(복합스코어) → Trader(매매)
                                               ↑
                                     MarketTemperature(온도 → 전략 조절)
                                       ├─ MacroModule (40%)
                                       ├─ SentimentModule (35%)
                                       └─ EconModule (25%)
```

### 핵심 트레이딩 흐름

1. **MarketTemperature** — 장 시작 전 시황 분석 → 전략 파라미터(k, TP, SL) 동적 조절
2. **StockScanner** — 5분마다 거래량 기반 종목 발굴 (KIS API + Naver 금융)
3. **StockScreener** — 거래량 급증, 모멘텀, MA정렬, 수급, 돌파근접도 복합 스코어링
4. **FirefeetTrader** — 10초 주기 매매 루프 (변동성 돌파 매수 / TP·SL·EOD 매도)

## 디렉토리 구조

```
core/                        # 핵심 모듈
├── kis_auth.py              # KIS OAuth2 인증 + 토큰 캐싱
├── kis_manager.py           # KIS API (시세, 주문, 잔고)
├── trader.py                # 메인 트레이딩 엔진
├── strategy.py              # 변동성 돌파 전략 + 온도 적용
├── scanner.py               # 거래량 기반 종목 스캐너
├── screener.py              # 복합 스코어링 스크리너
├── market_temperature.py    # 온도 오케스트레이터
├── temperature/             # 온도 플러그인 모듈
│   ├── base.py              # TempModule 인터페이스 + clamp
│   ├── macro_module.py      # 미 지수, VIX, 환율, 채권
│   ├── sentiment_module.py  # 뉴스 키워드 감성 분석
│   └── econ_module.py       # 경제 지표 서프라이즈
├── macro_analyzer.py        # yfinance 글로벌 지표 + 추세
├── econ_calendar.py         # MarketWatch 경제 일정 파싱
├── supply_analyzer.py       # 외국인/기관 수급 (KIS API)
├── news_scraper.py          # 네이버 금융 뉴스
├── news_analyzer.py         # MarketWatch + Google News RSS
├── reddit_analyzer.py       # Reddit 감성 (현재 미연동)
├── stock_agent.py           # Claude AI 종합 분석
├── report_generator.py      # 통합 리포트 생성
├── trade_logger.py          # 거래 CSV 로깅 + 수수료 계산
├── discord_client.py        # Discord Webhook (1,900자 분할)
└── config_loader.py         # YAML 설정 관리

config/                      # 설정 파일
├── secrets.yaml             # API 키 (gitignore 대상)
├── secrets_template.yaml    # secrets 템플릿
├── trading_settings.yaml    # 예산 (total_budget)
├── temperature_config.yaml  # 온도 모듈별 ON/OFF, 가중치, 키워드
├── watchlist.yaml           # 관심 종목
├── screener_settings.yaml   # 스크리너 가중치/필터
├── macro_config.yaml        # 매크로 지표 Phase별 ON/OFF
├── agent_settings.yaml      # Claude AI 모델/가중치
└── econ_calendar.yaml       # 경제 지표 필터

logs/                        # 거래 로그 (trades.csv)
docs/                        # 프로젝트 문서
```

## 설정 시스템

모든 설정은 `config/*.yaml`에서 관리. 온도 모듈은 `temperature_config.yaml`에서 모듈/서브모듈 단위 ON/OFF + 가중치 + 키워드 커스터마이징 가능.

### 온도 → 전략 매핑

| 레벨 | 온도 범위 | k | TP | SL | 포지션% |
|------|----------|-----|------|------|---------|
| HOT | 70+ | 0.3 | 4.0% | -3.0% | 35% |
| WARM | 40~69 | 0.4 | 3.5% | -3.0% | 30% |
| NEUTRAL | -20~39 | 0.5 | 3.0% | -3.0% | 25% |
| COOL | -60~-21 | 0.6 | 2.5% | -2.5% | 20% |
| COLD | <-60 | 0.7 | 2.0% | -2.0% | 15% |

## 수수료 구조

```
매수: 0.015%
매도: 0.015% + 거래세 0.18%
왕복: ~0.21%
```

## 외부 API

| API | 모듈 | 용도 |
|-----|------|------|
| KIS (한국투자증권) | kis_auth, kis_manager | 시세, 주문, 잔고 |
| yfinance | macro_analyzer | 미 지수, 환율, VIX, 채권 |
| Naver Finance | scanner, news_scraper | 거래량 순위, 한국 뉴스 |
| MarketWatch | econ_calendar, news_analyzer | 경제 일정, 글로벌 뉴스 |
| Google News RSS | news_analyzer | 뉴스 fallback |
| Discord Webhook | discord_client | 알림/리포트 |
| Anthropic (Claude) | stock_agent | AI 종합 분석 |
| Reddit (PRAW) | reddit_analyzer | 커뮤니티 감성 (미연동) |

## 개발 컨벤션

- **언어**: 코드는 영문, 주석/로그/리포트는 한국어
- **종목 코드**: 6자리 문자열 (`"005930"`)
- **시간**: KST 기준, `"%H%M"` 포맷 (예: `"1520"`)
- **에러 처리**: 모듈별 try/except로 독립 실행. 하나 실패해도 나머지 계속 동작
- **설정 변경**: YAML 파일만 수정하면 런타임에 반영 (trader는 매 루프 reload)
- **뉴스 스크래핑**: Naver 금융은 `dd.articleSubject a` 셀렉터 사용
- **온도 모듈**: `TempModule` 베이스 클래스 상속, `calculate()` → `{"score", "details"}` 반환
- **테스트**: `test_*.py` 파일들이 루트에 존재 (pytest 아닌 직접 실행 방식)

## 알려진 이슈

- MarketWatch 스크래핑이 간헐적으로 403 반환 → Google News RSS fallback 사용
- Reddit API 현재 미연동 (credentials 문제)
- econ_module의 `parse_number()` — 일부 경제 지표 서프라이즈 계산이 부정확할 수 있음
