# Market Temperature 시스템 워크플로우

## 개요

트레이딩 봇 실행 전에 시장 분위기를 종합 분석하여 **온도(Temperature)** 점수를 산출하고,
이 온도에 따라 전략 파라미터를 동적으로 조절하는 시스템.

**핵심 설계 원칙**: 모든 온도 구성요소는 **독립 모듈(플러그인)** 로 동작하며,
`temperature_config.yaml`에서 개별 ON/OFF, 가중치, 세부 파라미터를 조절할 수 있다.
모듈이 실패하거나 비활성화되면 나머지 모듈의 가중치를 자동 재배분한다.

```
                    ┌─────────────────────────┐
                    │  temperature_config.yaml │  ← 모든 설정의 Single Source
                    └────────────┬────────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          ▼                      ▼                      ▼
  ┌───────────────┐    ┌─────────────────┐    ┌─────────────────┐
  │ MacroModule   │    │ SentimentModule │    │ EconModule      │
  │ (플러그인)     │    │ (플러그인)       │    │ (플러그인)       │
  │               │    │                 │    │                 │
  │ ┌─ us_index ─┐│    │ ┌─ naver_news ─┐│    │ ┌─ surprise ──┐│
  │ │ (optional) ││    │ │ (optional)   ││    │ │ (optional)  ││
  │ ├─ vix ──────┤│    │ ├─ global_news ┤│    │ ├─ uncertainty┤│
  │ │ (optional) ││    │ │ (optional)   ││    │ │ (optional)  ││
  │ ├─ fx ───────┤│    │ └─────────────-┘│    │ └─────────────┘│
  │ │ (optional) ││    └────────┬────────┘    └───────┬────────┘
  │ ├─ bond ─────┤│             │                     │
  │ │ (optional) ││             │                     │
  │ └────────────┘│             │                     │
  └───────┬───────┘             │                     │
          │                     │                     │
          └──────────┬──────────┘─────────────────────┘
                     ▼
          ┌─────────────────┐
          │ MarketTemperature│  ← 오케스트레이터
          │ .calculate()    │     활성 모듈만 가중합산
          └────────┬────────┘     실패 모듈 자동 제외
                   ▼
            temperature: +42
            level: WARM
                   │
                   ▼
          ┌─────────────────┐
          │ Strategy        │
          │ .apply_temp()   │  ← k, TP, SL, position 조절
          └─────────────────┘
```

---

## 1. 온도 스케일

| 온도 | 범위 | 시장 상태 | 전략 방향 |
|------|------|-----------|-----------|
| 🔴 HOT | 70~100 | 강한 상승 분위기 | 공격적 매수, 익절 여유 |
| 🟠 WARM | 40~69 | 약한 상승/긍정 | 기본보다 약간 공격적 |
| ⚪ NEUTRAL | -19~39 | 혼조/불확실 | 기본 전략 유지 |
| 🔵 COOL | -59~-20 | 약한 하락/경계 | 보수적, 포지션 축소 |
| 🟣 COLD | -100~-60 | 강한 하락 분위기 | 매수 자제, 손절 타이트 |

---

## 2. 모듈 아키텍처

### 2-0. 공통 인터페이스

모든 온도 모듈은 동일한 인터페이스를 따른다.

```python
# core/temperature/base.py

class TempModule:
    """온도 모듈 공통 인터페이스"""

    name: str = "base"          # 모듈 식별자 (config 키와 일치)

    def __init__(self, config: dict):
        """
        config: temperature_config.yaml 에서 이 모듈에 해당하는 섹션
        예: {"enabled": true, "weight": 40, "sub_modules": {...}}
        """
        self.config = config
        self.enabled = config.get("enabled", True)
        self.weight = config.get("weight", 0)

    def calculate(self) -> dict:
        """
        Returns:
            {
                "score": float,        # -100 ~ +100 (정규화된 점수)
                "details": dict,       # 모듈별 상세 정보 (리포트용)
                "error": str | None,   # 실패 시 에러 메시지
            }
        실패 시에도 예외를 던지지 않고 {"score": 0, "error": "..."} 반환
        """
        raise NotImplementedError
```

### 2-1. MacroModule — 매크로 추세

**현재**: `MacroAnalyzer`가 전일 종가 vs 당일 종가 1회 비교만 수행
**변경**: 최근 N일간 추세 방향 + 변화율 기반 점수 산출. 내부 4개 서브모듈 각각 ON/OFF 가능.

```
core/temperature/macro_module.py

내부 서브모듈:
  - us_index:  미 3대지수 3일 추세      (기본 ON, 배점 -40~+40)
  - vix:       VIX 절대값 + 추세        (기본 ON, 배점 -30~+30)
  - fx:        원/달러 3일 방향          (기본 ON, 배점 -15~+15)
  - bond:      미 10년물 금리 방향       (기본 OFF, 배점 -15~+15)
```

#### 데이터 수집

```python
# core/macro_analyzer.py 에 추가

def get_trend_data(self, symbol, days=3):
    """
    최근 N일간 일별 등락률 + 추세 방향
    Returns: {
        "prices": [72100, 72500, 73200],
        "daily_changes": [+0.8, +0.55, +0.96],
        "avg_change": +0.77,
        "trend": "UP",          # UP / DOWN / FLAT
        "streak": 3,            # 연속 상승/하락 일수
        "current_price": 73200,
    }
    """
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=f"{days * 3}d")  # 넉넉히
    # 최근 days+1일 추출 → 일별 변화율 계산
    ...
```

#### 서브모듈별 점수 산출

```python
class MacroModule(TempModule):
    name = "macro"

    # 서브모듈 정의: (이름, 심볼맵, 점수범위, 점수함수)
    SUB_MODULES = {
        "us_index": {
            "symbols": {"나스닥": "^IXIC", "S&P 500": "^GSPC", "다우존스": "^DJI"},
            "score_range": (-40, 40),
        },
        "vix": {
            "symbols": {"VIX": "^VIX"},
            "score_range": (-30, 30),
        },
        "fx": {
            "symbols": {"원/달러": "USDKRW=X"},
            "score_range": (-15, 15),
        },
        "bond": {
            "symbols": {"미 10년물": "^TNX"},
            "score_range": (-15, 15),
        },
    }

    def calculate(self):
        total = 0
        details = {}

        for sub_name, sub_conf in self.SUB_MODULES.items():
            # config에서 해당 서브모듈 ON/OFF 확인
            if not self.config.get("sub_modules", {}).get(sub_name, {}).get("enabled", True):
                continue

            score = self._calc_sub(sub_name, sub_conf)
            total += score["score"]
            details[sub_name] = score

        return {"score": clamp(total, -100, 100), "details": details, "error": None}

    def _calc_sub_us_index(self, trends):
        """미 3대지수 — 3일 평균 등락률 기반"""
        avg_changes = [t["avg_change"] for t in trends.values()]
        us_avg = sum(avg_changes) / len(avg_changes)
        return clamp(us_avg * 20, -40, 40)

    def _calc_sub_vix(self, trends):
        """VIX — 절대 레벨 + 추세 방향"""
        vix = trends["VIX"]
        # 레벨 점수
        price = vix["current_price"]
        level_score = (
            -20 if price > 30 else
            -10 if price > 25 else
              0 if price > 18 else
            +10 if price > 12 else
            +20
        )
        # 추세 점수 (VIX 하락 = 긍정)
        trend_score = clamp(-vix["avg_change"] * 5, -10, 10)
        return level_score + trend_score

    def _calc_sub_fx(self, trends):
        """원/달러 — 환율 하락(원화 강세) = 긍정"""
        fx = trends["원/달러"]
        return clamp(-fx["avg_change"] * 10, -15, 15)

    def _calc_sub_bond(self, trends):
        """미 10년물 — 금리 하락 = 주식에 긍정"""
        bond = trends["미 10년물"]
        return clamp(-bond["avg_change"] * 5, -15, 15)
```

### 2-2. SentimentModule — 뉴스/커뮤니티 감성

**현재**: `RedditAnalyzer`(미작동), `NewsAnalyzer`(MarketWatch), `NewsScraper`(네이버)
**변경**: 과거 2~3일 뉴스 헤드라인 감성 분석. 소스별 ON/OFF 가능.

```
core/temperature/sentiment_module.py

내부 서브모듈:
  - naver_news:   네이버 금융 뉴스 (한국어 감성사전)   (기본 ON)
  - global_news:  MarketWatch 뉴스 (영어 감성사전)    (기본 ON)
```

#### 감성 사전 (외부 설정 가능)

```yaml
# temperature_config.yaml 의 sentiment 섹션
sentiment:
  enabled: true
  weight: 35
  days: 3                    # 분석 기간
  day_weights: [0.5, 0.3, 0.2]  # 최근일 가중 (오늘, 어제, 그제)
  sub_modules:
    naver_news:
      enabled: true
      pages_per_day: 3
      bullish_keywords: [급등, 상승, 호재, 매수세, 반등, 신고가, ...]
      bearish_keywords: [급락, 하락, 악재, 매도세, 폭락, 신저가, ...]
    global_news:
      enabled: true
      bullish_keywords: [rally, surge, bullish, breakout, ...]
      bearish_keywords: [crash, plunge, bearish, selloff, ...]
```

키워드 사전을 config에 두면 코드 수정 없이 키워드 추가/제거 가능.

#### 점수 산출

```python
class SentimentModule(TempModule):
    name = "sentiment"

    def calculate(self):
        days = self.config.get("days", 3)
        day_weights = self.config.get("day_weights", [0.5, 0.3, 0.2])
        daily_scores = {}
        details = {}

        for sub_name in ["naver_news", "global_news"]:
            sub_cfg = self.config.get("sub_modules", {}).get(sub_name, {})
            if not sub_cfg.get("enabled", True):
                continue

            # 소스별 날짜별 뉴스 수집
            headlines = self._fetch_headlines(sub_name, days, sub_cfg)
            sub_daily = self._score_daily(headlines, sub_cfg)
            details[sub_name] = sub_daily

            # 소스별 점수를 daily_scores에 합산
            for date, score in sub_daily.items():
                daily_scores[date] = daily_scores.get(date, 0) + score

        # 소스가 2개면 평균, 1개면 그대로
        active_sources = sum(1 for s in ["naver_news", "global_news"]
                            if self.config.get("sub_modules", {}).get(s, {}).get("enabled", True))
        if active_sources > 1:
            daily_scores = {d: v / active_sources for d, v in daily_scores.items()}

        # 날짜별 가중 평균
        sorted_dates = sorted(daily_scores.keys(), reverse=True)  # 최근순
        weighted_sum = 0
        weight_sum = 0
        for i, date in enumerate(sorted_dates[:len(day_weights)]):
            w = day_weights[i]
            weighted_sum += daily_scores[date] * w
            weight_sum += w

        score = weighted_sum / weight_sum if weight_sum > 0 else 0

        # 추세 판단
        trend = "STABLE"
        if len(sorted_dates) >= 2:
            today_score = daily_scores[sorted_dates[0]]
            yesterday_score = daily_scores[sorted_dates[1]]
            diff = today_score - yesterday_score
            if diff > 10:
                trend = "IMPROVING"
            elif diff < -10:
                trend = "WORSENING"

        return {
            "score": clamp(score, -100, 100),
            "details": {"daily": daily_scores, "trend": trend, "sources": details},
            "error": None,
        }

    def _fetch_headlines(self, source, days, sub_cfg):
        """소스별 뉴스 헤드라인 수집 (날짜별)"""
        if source == "naver_news":
            return self._fetch_naver(days, sub_cfg)
        elif source == "global_news":
            return self._fetch_marketwatch(days, sub_cfg)
        return {}

    def _score_daily(self, headlines_by_date, sub_cfg):
        """날짜별 감성 점수 (-100~+100)"""
        bullish = sub_cfg.get("bullish_keywords", [])
        bearish = sub_cfg.get("bearish_keywords", [])
        result = {}

        for date, titles in headlines_by_date.items():
            text = " ".join(titles)
            bull = sum(text.count(kw) for kw in bullish)
            bear = sum(text.count(kw) for kw in bearish)
            total = bull + bear
            result[date] = ((bull - bear) / total * 100) if total > 0 else 0

        return result
```

#### NewsScraper 확장

```python
# core/news_scraper.py 에 추가

def fetch_news_by_date(self, date_str, pages=3):
    """
    특정 날짜의 네이버 금융 뉴스를 수집
    date_str: "20260212" (YYYYMMDD)
    Returns: [title1, title2, ...]
    """
    titles = []
    for page in range(1, pages + 1):
        url = (
            "https://finance.naver.com/news/news_list.naver"
            f"?mode=LSS2D&section_id=101&section_id2=258"
            f"&date={date_str}&page={page}"
        )
        # ... 기존 파싱 로직 활용 ...
    return titles
```

### 2-3. EconModule — 경제 지표 이벤트

**현재**: `EconCalendar`가 오늘/내일 일정만 리포트
**변경**: 최근 발표 서프라이즈 점수 + 오늘 대형 이벤트 불확실성. 서브모듈 ON/OFF 가능.

```
core/temperature/econ_module.py

내부 서브모듈:
  - surprise:      최근 발표 실제 vs 예상 차이    (기본 ON)
  - uncertainty:   오늘 미발표 고중요도 이벤트 수  (기본 ON)
```

```python
class EconModule(TempModule):
    name = "econ"

    def calculate(self):
        events = EconCalendar().fetch_all()
        score = 0
        details = {}

        sub_modules = self.config.get("sub_modules", {})

        # 서프라이즈 분석
        if sub_modules.get("surprise", {}).get("enabled", True):
            surprise = self._calc_surprise(events)
            score += surprise["score"]
            details["surprise"] = surprise

        # 불확실성 분석
        if sub_modules.get("uncertainty", {}).get("enabled", True):
            uncertainty = self._calc_uncertainty(events)
            score += uncertainty["score"]
            details["uncertainty"] = uncertainty

        return {"score": clamp(score, -100, 100), "details": details, "error": None}

    def _calc_surprise(self, events):
        """최근 발표 결과의 서프라이즈 점수"""
        released = [e for e in events if e['actual'] != '-']
        total_score = 0
        items = []
        importance_multiplier = self.config.get("sub_modules", {}).get(
            "surprise", {}).get("importance_multiplier", {"high": 3, "medium": 2, "low": 1})

        for e in released:
            try:
                actual = parse_number(e['actual'])
                forecast = parse_number(e['forecast'])
                if forecast != 0:
                    surprise_pct = (actual - forecast) / abs(forecast) * 100
                    weight = importance_multiplier.get(e['importance'], 1)
                    contribution = clamp(surprise_pct * weight, -20, 20)
                    total_score += contribution
                    items.append({"name": e['name'], "surprise": surprise_pct, "contribution": contribution})
            except:
                pass

        return {"score": clamp(total_score, -60, 60), "items": items}

    def _calc_uncertainty(self, events):
        """오늘 미발표 고중요도 이벤트 → 불확실성 페널티"""
        today = datetime.date.today().isoformat()
        penalty_per_event = self.config.get("sub_modules", {}).get(
            "uncertainty", {}).get("penalty_per_event", -10)
        today_high = [e for e in events
                      if e['date'] == today and e['importance'] == 'high' and e['actual'] == '-']
        penalty = penalty_per_event * len(today_high)

        return {"score": clamp(penalty, -40, 0), "pending_events": len(today_high)}
```

---

## 3. 오케스트레이터: MarketTemperature

```python
# core/market_temperature.py

class MarketTemperature:
    """
    시장 온도 산출 오케스트레이터.
    config에서 활성화된 모듈만 로드하고, 가중 합산한다.
    모듈 실패 시 해당 모듈 제외 + 나머지 가중치 재배분.
    """

    # 모듈 레지스트리 (플러그인 패턴)
    MODULE_REGISTRY = {
        "macro": MacroModule,
        "sentiment": SentimentModule,
        "econ": EconModule,
    }

    LEVELS = [
        (70,  "HOT"),
        (40,  "WARM"),
        (-20, "NEUTRAL"),
        (-60, "COOL"),
    ]   # 미만은 "COLD"

    def __init__(self, config_path="config/temperature_config.yaml"):
        self.config = self._load_config(config_path)
        self.modules = self._init_modules()

    def _init_modules(self):
        """config에서 enabled인 모듈만 인스턴스화"""
        modules = {}
        for name, cls in self.MODULE_REGISTRY.items():
            mod_config = self.config.get("modules", {}).get(name, {})
            if mod_config.get("enabled", False):
                modules[name] = cls(mod_config)
        return modules

    def calculate(self):
        results = {}
        failed = []

        # 1. 각 모듈 실행
        for name, module in self.modules.items():
            result = module.calculate()
            if result.get("error"):
                failed.append(name)
                print(f"[Temperature] {name} 모듈 실패: {result['error']}")
            else:
                results[name] = result

        # 2. 활성 모듈만으로 가중치 재배분
        active_weights = {name: self.modules[name].weight for name in results}
        total_weight = sum(active_weights.values())

        if total_weight == 0:
            return {"temperature": 0, "level": "NEUTRAL", "components": {}, "failed": failed}

        # 3. 가중 합산
        temperature = 0
        for name, result in results.items():
            normalized_weight = active_weights[name] / total_weight
            temperature += result["score"] * normalized_weight

        temperature = round(clamp(temperature, -100, 100), 1)

        return {
            "temperature": temperature,
            "level": self._to_level(temperature),
            "components": {name: r["score"] for name, r in results.items()},
            "details": {name: r.get("details", {}) for name, r in results.items()},
            "failed": failed,
        }

    def _to_level(self, temp):
        for threshold, level in self.LEVELS:
            if temp >= threshold:
                return level
        return "COLD"
```

---

## 4. 설정 파일: `config/temperature_config.yaml`

```yaml
# ──────────────────────────────────────────
# Market Temperature 설정
# 모든 모듈/서브모듈을 enabled: false 로 끌 수 있음
# weight: 합산 시 상대 비중 (절대값 아님, 활성 모듈끼리 비례 배분)
# ──────────────────────────────────────────

modules:

  # ── 매크로 추세 ──
  macro:
    enabled: true
    weight: 40
    trend_days: 3             # 추세 분석 기간 (일)
    sub_modules:
      us_index:
        enabled: true
        score_range: [-40, 40]
        multiplier: 20        # avg_change * multiplier = raw score
      vix:
        enabled: true
        score_range: [-30, 30]
        level_thresholds:     # VIX 절대값 기준 (커스터마이징 가능)
          extreme_fear: 30    # 이상 → -20
          fear: 25            # 이상 → -10
          normal: 18          # 이상 →   0
          calm: 12            # 이상 → +10
                              # 미만 → +20
        trend_multiplier: 5
      fx:
        enabled: true
        score_range: [-15, 15]
        multiplier: 10
        invert: true          # 환율 하락 = 긍정 (부호 반전)
      bond:
        enabled: false        # 기본 OFF — 필요 시 활성화
        score_range: [-15, 15]
        multiplier: 5
        invert: true          # 금리 하락 = 긍정

  # ── 뉴스/커뮤니티 감성 ──
  sentiment:
    enabled: true
    weight: 35
    days: 3
    day_weights: [0.5, 0.3, 0.2]   # 오늘, 어제, 그제
    trend_threshold: 10              # 이 이상 변화면 IMPROVING/WORSENING
    sub_modules:
      naver_news:
        enabled: true
        pages_per_day: 3
        bullish_keywords:
          - 급등
          - 상승
          - 호재
          - 매수세
          - 반등
          - 신고가
          - 호실적
          - 상한가
          - 돌파
          - 강세
          - 기대감
          - 외국인 매수
          - 기관 매수
        bearish_keywords:
          - 급락
          - 하락
          - 악재
          - 매도세
          - 폭락
          - 신저가
          - 실적 부진
          - 하한가
          - 약세
          - 우려
          - 외국인 매도
          - 리스크
          - 경기 침체
      global_news:
        enabled: true
        bullish_keywords:
          - rally
          - surge
          - bullish
          - breakout
          - record high
          - beat expectations
          - strong earnings
          - upgrade
        bearish_keywords:
          - crash
          - plunge
          - bearish
          - selloff
          - recession
          - miss expectations
          - weak
          - downgrade

  # ── 경제 지표 ──
  econ:
    enabled: true
    weight: 25
    sub_modules:
      surprise:
        enabled: true
        score_range: [-60, 60]
        importance_multiplier:
          high: 3
          medium: 2
          low: 1
      uncertainty:
        enabled: true
        score_range: [-40, 0]
        penalty_per_event: -10   # 미발표 고중요도 이벤트 1건당

# ── 온도 → 전략 프로파일 ──
strategy_profiles:
  HOT:
    k: 0.3
    take_profit: 4.0
    stop_loss: -3.0
    max_position_pct: 0.35
    min_screen_score: 20
  WARM:
    k: 0.4
    take_profit: 3.5
    stop_loss: -3.0
    max_position_pct: 0.30
    min_screen_score: 30
  NEUTRAL:
    k: 0.5
    take_profit: 3.0
    stop_loss: -3.0
    max_position_pct: 0.25
    min_screen_score: 30
  COOL:
    k: 0.6
    take_profit: 2.5
    stop_loss: -2.5
    max_position_pct: 0.20
    min_screen_score: 45
  COLD:
    k: 0.7
    take_profit: 2.0
    stop_loss: -2.0
    max_position_pct: 0.15
    min_screen_score: 60

# ── 온도 레벨 경계값 (커스터마이징 가능) ──
level_thresholds:
  HOT: 70
  WARM: 40
  NEUTRAL: -20
  COOL: -60
  # COOL 미만 = COLD
```

---

## 5. 전략 연동

### Strategy 변경

```python
# core/strategy.py

class VolatilityBreakoutStrategy:
    def __init__(self, manager, k=0.5):
        self.manager = manager
        self.k = k
        self.take_profit = 3.0
        self.stop_loss = -3.0
        self.max_position_pct = 0.25
        self.min_screen_score = 30

    def apply_temperature(self, temp_result, profiles):
        """
        온도 결과 + config의 프로파일을 받아 파라미터 조절.
        profiles는 temperature_config.yaml의 strategy_profiles 섹션.
        """
        level = temp_result["level"]
        profile = profiles.get(level, profiles.get("NEUTRAL", {}))

        self.k = profile.get("k", self.k)
        self.take_profit = profile.get("take_profit", self.take_profit)
        self.stop_loss = profile.get("stop_loss", self.stop_loss)
        self.max_position_pct = profile.get("max_position_pct", self.max_position_pct)
        self.min_screen_score = profile.get("min_screen_score", self.min_screen_score)

    def should_sell(self, current_price, buy_price, current_time_str):
        profit_rate = (current_price - buy_price) / buy_price * 100

        if profit_rate >= self.take_profit:
            return "SELL_TAKE_PROFIT"
        if profit_rate <= self.stop_loss:
            return "SELL_STOP_LOSS"

        time_int = int(current_time_str.replace(":", "")[:4])
        if time_int >= 1520 and time_int < 1530:
            return "SELL_EOD"
        return None
```

---

## 6. 실행 흐름

```
run_firefeet.py 메인 루프
│
├─ [1] 장 시작 전 (08:50)
│   ├─ temp = MarketTemperature("config/temperature_config.yaml")
│   ├─ result = temp.calculate()
│   │   ├─ MacroModule.calculate()       ← 미장 3일 추세 (활성 서브모듈만)
│   │   ├─ SentimentModule.calculate()   ← 뉴스 2~3일 감성 (활성 소스만)
│   │   └─ EconModule.calculate()        ← 경제 지표 (활성 서브모듈만)
│   │   └─ 실패 모듈 → 자동 제외, 가중치 재배분
│   │
│   ├─ strategy.apply_temperature(result, config["strategy_profiles"])
│   ├─ Discord: "🌡️ 오늘의 시장 온도: +42 (WARM)"
│   └─ Discord: "전략 → k=0.4, TP=+3.5%, SL=-3.0%"
│
├─ [2] 장중 (09:00~15:30)
│   ├─ 기존 루프: scan → screen → trade
│   ├─ Screener min_score가 온도에 따라 조절됨
│   └─ Strategy TP/SL/k가 온도에 따라 조절됨
│
├─ [3] 점심 재계산 (선택적, config로 ON/OFF)
│   ├─ temp.calculate()
│   └─ strategy.apply_temperature(result, profiles)
│
└─ [4] 장 마감 후
    └─ 일별 요약에 온도 기록 포함
```

---

## 7. 파일 구조

```
core/
├── temperature/
│   ├── __init__.py
│   ├── base.py                  # TempModule 인터페이스
│   ├── macro_module.py          # 매크로 추세 모듈
│   ├── sentiment_module.py      # 뉴스 감성 모듈
│   └── econ_module.py           # 경제 지표 모듈
├── market_temperature.py        # 오케스트레이터
├── macro_analyzer.py            # 수정: get_trend_data() 추가
├── news_scraper.py              # 수정: fetch_news_by_date() 추가
├── news_analyzer.py             # 수정: fetch_global_news_by_date() 추가
├── econ_calendar.py             # 수정: (EconModule에서 직접 사용)
├── strategy.py                  # 수정: apply_temperature() 추가
├── trader.py                    # 수정: 온도 기반 포지션 사이징
└── screener.py                  # 수정: 온도 기반 min_score

config/
└── temperature_config.yaml      # 전체 설정 (위 섹션 4 참조)
```

---

## 8. Discord 출력 예시

```
🌡️ **시장 온도: +42 (🟠 WARM)**

📊 매크로 추세 [+55]
  나스닥 3일: +0.8%, +1.2%, +0.3% (연속 상승 ↑)
  S&P 500 3일: +0.5%, +0.9%, +0.1%
  VIX: 16.2 (안정) | 3일 변화: -1.8pt
  원/달러: 1,345 | 3일: -0.5% (원화 강세)

📰 뉴스 감성 [+38]
  한국 뉴스: 긍정 23건 / 부정 15건 (🟢 +21)
  해외 뉴스: 긍정 18건 / 부정 12건 (🟢 +20)
  추세: IMPROVING (어제 대비 감성 개선)

📅 경제 지표 [+25]
  CPI 발표: 실제 3.1% vs 예상 3.2% (소폭 긍정)
  오늘 고중요도 일정: 없음

⚙️ 전략 조정
  k: 0.5 → 0.4 | TP: 3.0% → 3.5% | SL: -3.0% 유지
  스크리닝 기준: 30점 이상 (기본)
  최대 포지션: 예산의 30%
```

---

## 9. 커스터마이징 시나리오

### 시나리오 A: "VIX만 보고 싶다"

```yaml
modules:
  macro:
    enabled: true
    weight: 100
    sub_modules:
      us_index: { enabled: false }
      vix: { enabled: true }
      fx: { enabled: false }
      bond: { enabled: false }
  sentiment: { enabled: false }
  econ: { enabled: false }
```
→ VIX 점수 하나만으로 온도 산출됨.

### 시나리오 B: "뉴스만 끄고 나머지는 기본"

```yaml
modules:
  macro: { enabled: true, weight: 60 }  # weight 비율 자동 재배분
  sentiment: { enabled: false }
  econ: { enabled: true, weight: 40 }
```
→ 매크로 60%, 경제 40%로 자동 재배분.

### 시나리오 C: "감성 사전에 키워드 추가"

```yaml
sentiment:
  sub_modules:
    naver_news:
      bullish_keywords:
        - 급등
        - ... (기존)
        - AI 수혜      # 추가
        - 반도체 호황   # 추가
```
→ 코드 수정 없이 config만 변경.

### 시나리오 D: "전략 프로파일 자체를 변경"

```yaml
strategy_profiles:
  HOT:
    k: 0.25          # 더 공격적으로
    take_profit: 5.0  # 익절 여유 확대
```
→ 코드 수정 없이 전략 반응 튜닝.

---

## 10. 구현 순서 (권장)

```
Phase 1: 기반 구조
  → core/temperature/ 패키지 + base.py (TempModule 인터페이스)
  → core/market_temperature.py (오케스트레이터 뼈대)
  → config/temperature_config.yaml
  → 단독 실행: python3 -m core.market_temperature

Phase 2: MacroModule
  → macro_analyzer.py에 get_trend_data() 추가
  → core/temperature/macro_module.py 구현
  → 단독 테스트 (yfinance 데이터 안정적)

Phase 3: SentimentModule
  → news_scraper.py에 fetch_news_by_date() 추가
  → news_analyzer.py에 fetch_global_news_by_date() 추가
  → core/temperature/sentiment_module.py 구현
  → 단독 테스트

Phase 4: EconModule
  → core/temperature/econ_module.py 구현
  → 단독 테스트

Phase 5: 통합 + 전략 연동
  → market_temperature.py 에서 3개 모듈 통합
  → strategy.py에 apply_temperature() 추가
  → trader.py / screener.py 연동
  → run_firefeet.py에 장 시작 전 온도 계산 삽입
  → Discord 리포트 출력
```

---

## 11. 리스크 & 고려사항

| 항목 | 설명 | 대응 |
|------|------|------|
| 모듈 전체 실패 | 3개 모듈 모두 에러 | temperature=0 (NEUTRAL) 반환 → 기본 전략 유지 |
| 뉴스 스크래핑 실패 | 네이버/MW 구조 변경 | 해당 서브모듈 에러 → 나머지 소스로 감성 산출 |
| 과적합 위험 | 온도에 과도하게 반응 | config에서 파라미터 범위 제한 (k: 0.3~0.7 등) |
| API 호출 비용 | yfinance 호출 증가 | 1일 1~2회 캐싱 (장중 재계산은 config로 ON/OFF) |
| 감성 사전 한계 | 키워드는 문맥 무시 | config 키워드 튜닝으로 점진 개선 + 향후 LLM 분석 고려 |
| 백테스트 부재 | 온도 조절이 실제 수익 개선하는지 불확실 | 초기: 로그만 + 기본 전략 유지, 데이터 축적 후 프로파일 조절 |
