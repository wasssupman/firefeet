# AI 스윙 트레이딩 전략 심층 리뷰

> 분석 일자: 2026-03-03
> 분석 대상: 02-20 실매매 로그 (36건, 1일)
> 작성자: Architect Agent

---

## Executive Summary

현재 시스템의 PF 0.43(승률 36.1%)은 **구조적으로 수익 불가능한 상태**이다. 근본 원인은 단일 버그가 아니라, 여러 설계 결함이 중첩되어 발생한 복합적 문제이다.

**핵심 발견 5가지:**

1. **온도 시스템 미연결 (치명적)**: `run_ai_swing_bot.py`에서 `strategy.apply_temperature()`가 호출되지 않아, 시장 온도와 무관하게 항상 NEUTRAL 파라미터(k=0.5, TP=3.0%, SL=-3.0%)로 매매
2. **포지션 사이징 제한 없음**: `target_allocation_per_stock` 설정이 config에 없어 기본값 1,000,000원(=전체 예산)이 적용. 후반 종목에 자금이 집중되는 구조
3. **스크리너 점수 미전달**: `screener_score: 0`으로 하드코딩되어 AI가 종목 품질 정보 없이 판단
4. **매도 후 추적 누락**: `SwingTrader._execute_sell()`이 `sold_today`, `daily_realized_pnl`, `consecutive_sl_count`를 업데이트하지 않아 모든 안전장치 무력화
5. **R:R 구조적 역전**: TP 3.75% vs SL 3.41%에서 승률 36%이면 기대값 = (0.36 x 3.75) - (0.64 x 3.41) = **-0.83%/건**. 최소 승률 48% 필요

---

## Part A. 전략 구조 분석

### A-1. 3기둥 전략 실전 작동 여부

#### TREND (MA120 추세 필터) -- 부분 작동

- **코드 위치**: `scoring_engine.py:222-244`
- **문제점**: MA120 필터는 스크리너 단계에서 작동하지만, **데이터 부족(120일 미만) 시 자동 통과**시킨다 (line 229-230). 신규 상장 종목이나 데이터 부족 종목이 필터를 우회하여 추세와 무관한 종목이 진입할 수 있다.
- **양호한 점**: `price > MA120` AND `MA120 기울기 > 0` 이중 조건은 Stage 2 필터로서 합리적이다.

```python
# scoring_engine.py:229-230 -- 데이터 부족 시 필터 무효화
if ohlc is None or (hasattr(ohlc, 'empty') and ohlc.empty) or len(ohlc) < 120:
    return True, "데이터 부족 (MA120 필터 비활성)"  # ← 위험: 무조건 통과
```

#### CONTRACTION (ATR 수축) -- 가중치 과소

- **코드 위치**: `scoring_engine.py:246-268`, `screener_settings.yaml:12`
- **문제점**: 수축 보너스 가중치가 10%뿐이다. "수축 이후의 확장"이 핵심 전략인데, 수축 종목과 비수축 종목의 점수 차이가 최대 10점(100점 만점)에 불과하다. contraction_ratio가 0.5 이하인 극도의 수축 종목과 이미 확장 중인 종목(1.0 이상)의 실질적 점수 차이가 전체 선별에 미미한 영향만 준다.
- **결과**: 수축 없이 단순 거래량 급증 종목이 상위에 오르고, 이들은 이미 추세의 후반부인 경우가 많아 SL에 걸린다.

#### EXPANSION (변동성 돌파) -- 스윙봇에서 미사용

- **코드 위치**: `technical.py:74-103` (check_buy_signal)
- **치명적 문제**: `SwingTrader`는 `check_buy_signal()`을 **호출하지 않는다**. 매수 판단을 100% AI에 위임한다. 즉 3기둥 중 EXPANSION은 스윙봇에서 완전히 생략되어 있다.
- `FirefeetTrader._process_buy()`(line 250-252)만이 `strategy.check_buy_signal()`을 호출한다.
- **결과**: "추세 안에서, 수축 이후의 확장을 산다"는 핵심 원리 중 "확장" 검증이 없다. AI가 변동성 돌파 여부와 무관하게 BUY를 결정할 수 있다.

#### RISK ANCHORING (ATR 기반 SL/TP) -- 부분 작동, 구조적 문제 있음

- **코드 위치**: `swing_trader.py:134-153`
- **작동**: 하드 SL은 ATR 기반으로 작동한다.
- **문제점 1**: 온도 미연결로 인해 `hard_sl_atr_multiplier`는 항상 기본값 3.0이 적용된다 (line 145). 시장 상황과 무관.
- **문제점 2**: AI의 `target_price`와 `stop_loss`가 있지만 하드 SL 외에는 실제 TP/SL 판단에 사용되지 않는다. 보유 중 매도는 (1) 하드 SL 도달 또는 (2) AI가 SELL을 판단할 때만 발생한다. ATR 기반 TP는 어디에도 구현되어 있지 않다.

### A-2. 7팩터 스코어링 가중치 분석

| 팩터 | 가중치 | 실전 유효성 | 문제점 |
|------|--------|-------------|--------|
| 거래량 급증 | 20% | 중 | 5x 이상이면 100점이지만, 거래량 폭발은 종종 추세 후반/과열 신호 |
| 가격 모멘텀 | 10% | 중 | +3% sweet spot은 합리적이나, 스윙에서는 당일 등락률보다 다일 추세가 중요 |
| MA 정배열 | 20% | 상 | P > MA5 > MA20 조건 자체는 양호 |
| 수급 | 20% | 상 | 외국인+기관 쌍끌이 매수 감지는 유효한 시그널 |
| 돌파 근접도 | 15% | 하 | **변동성 돌파 목표가 기준인데, 스윙봇은 변동성 돌파를 사용하지 않아 무의미** |
| 수축 보너스 | 10% | 하 | 핵심 전략인데 가중치가 너무 낮음 |
| 장중 체력 | 5% | 하 | 스윙(3일~2주 보유)에서 장중 고점 대비 위치는 의미 미약 |

**구조적 불일치**: 스크리너는 "변동성 돌파 데이트레이딩"에 최적화되어 있고, 스윙 트레이딩의 핵심 팩터(다일 추세 강도, 섹터 모멘텀, 기관 누적 매수 기간, 이격도)가 반영되지 않았다.

### A-3. Dual-LLM 파이프라인 의사결정 품질

#### screener_score 미전달 (치명적)

```python
# run_ai_swing_bot.py:275 -- 항상 0으로 전달
"screener_score": 0  # (실제 구현 시 Screener 결과를 캐싱하여 주입 고려)
```

AI Analyst와 Executor 모두 `screener_score`를 받지만, 실제로는 항상 0이다. 7팩터 스코어링의 결과가 AI 판단에 전혀 반영되지 않는다. AI는 OHLC, 수급, 뉴스, 시장온도만으로 판단하며, 스크리너가 왜 이 종목을 선별했는지 모른다.

#### Analyst-Executor 간 정보 손실

- **Analyst** (`claude_analyst.py:13`): `claude-sonnet-4-20250514` 사용
- **Executor** (`claude_executor.py:14`): `claude-3-5-sonnet-20241022` 사용 (구 버전)
- Executor는 Analyst의 Markdown 메모 + hard facts만 받는다. hard facts에 `current_price`와 `score(=0)` 두 개만 존재한다.
- 온도 레벨, ATR 수축 비율, 수급 sentiment, 변동성 돌파 여부 등이 hard facts에 포함되지 않아 Executor가 sanity check할 근거가 부족하다.

#### Sanity Check 범위 문제

```python
# ai_swing_agent.py:130-152
# target_price ∈ [current × 1.05, current × 1.30] → 문서에만 있고 코드에는 미구현
# 실제 코드는 target > price, stop < price만 체크
if target <= price or stop >= price:  # ← 매우 느슨한 조건
```

문서(`swing_trading.md:89-91`)에는 `target_price ∈ [current × 1.05, current × 1.30]`, `stop_loss ∈ [current × 0.90, current × 0.95]` 범위 체크가 있다고 기술되어 있지만, 실제 코드에는 이 범위 제한이 없다. AI가 현재가 50,000원에 target_price 51,000원(+2%), stop_loss 30,000원(-40%)을 제안해도 통과한다.

---

## Part B. 리스크/수익 구조 진단

### B-1. TP/SL 비율 구조적 마이너스 원인

실매매 결과: TP 평균 +3.75%, SL 평균 -3.41%, 승률 36.1%

**기대값 계산:**
```
E[수익] = (0.361 × 3.75%) + (0.639 × (-3.41%))
        = 1.354% - 2.179%
        = -0.825% per trade
```

36건 × -0.825% × 평균 포지션 ≈ -70,000원 → 실제 결과 -70,255원과 일치.

**R:R이 마이너스인 근본 원인:**

1. **TP/SL 비율이 거의 1:1** (3.75%:3.41% = 1.10:1). 스윙 트레이딩에서 최소 R:R 2:1 이상이 필요하다.
2. **TP가 너무 좁다**: NEUTRAL 기준 고정 TP 3.0%, ATR TP는 `max(3.0%, ATR×3.0/price)`. 한국 주식의 일평균 ATR이 2-3%인 종목에서 3%는 1일 변동폭 수준으로, 트레이딩 수수료(왕복 0.21%)를 제하면 실질 수익은 2.79%.
3. **SL이 너무 좁다**: 고정 SL -3.0%는 한국 주식의 일중 노이즈 범위. 스윙에서 3일 이상 보유하면 정상적인 조정에도 SL에 걸린다.
4. **온도 미적용**: HOT 시장에서도 TP=3.0%, SL=-3.0%이므로 상승 추세의 잠재력을 활용하지 못한다.

### B-2. 포지션 사이징 후반 과대 문제

```python
# swing_trader.py:99-101
target_allocation = self.trading_rules.get("target_allocation_per_stock", 1000000)
budget = min(self.manager.get_balance()['available_cash'], target_allocation)
qty = int(budget // current_price)
```

- `target_allocation_per_stock`가 `trading_rules.yaml`에 정의되어 있지 않다. 기본값 1,000,000원(=전체 예산)이 적용된다.
- `max_position_amount`(15만원 제한)는 `FirefeetTrader._process_buy()`에서만 적용되고, `SwingTrader._process_ai_buy()`에서는 **체크되지 않는다**.
- 결과: 전체 가용 잔고가 첫 종목 매수에 들어간다. 이후 매도 → 재투자 시 잔고가 점점 줄면서 포지션 크기가 불규칙해진다.
- 02-20 로그에서 "후반 종목일수록 포지션 커지고 연속 SL" 현상은 이 때문이다.

### B-3. 시간대별 성과 차이 원인

09시대 +18,626원(수익) vs 10시 이후 -79,881원(전패)

**원인 분석:**

1. **09시대**: 장 초반 갭업/변동성 돌파가 가장 유효한 시간대. 거래량 급증 + 추세 시작 구간에서 모멘텀이 강하다.
2. **10시 이후**:
   - 장 초반 모멘텀이 소진된 후, 동일 전략으로 진입하면 "이미 오른 종목"을 추격 매수하는 결과가 된다.
   - 스크리너가 **당일 거래량 급증**을 최우선(20%)으로 보기 때문에, 오전에 이미 급등한 종목이 계속 상위에 랭크된다.
   - 이 시점의 진입은 이미 과열 구간이며, 차익 실현 매물에 의해 SL에 걸린다.
3. **시간대 필터 부재**: 스캘핑 시스템(`scalp_risk_manager.py:123`)에는 `no_entry_before`/`no_entry_after` 시간 필터가 있지만, 스윙 시스템에는 시간대별 진입 제한이 전혀 없다.

### B-4. PF 0.43의 구조적 불가능성

Profit Factor = 총이익 / 총손실 = (13 × 3,201) / (18 × 5,344) = 41,613 / 96,192 = 0.43

PF < 1.0은 손실이 이익보다 크다는 의미. PF 0.43은:
- 1원을 벌기 위해 2.33원을 잃는 구조
- 수수료(왕복 0.21%) 포함 시 더욱 악화
- **어떤 시장 환경에서도 수익 불가능**

필요 최소 PF ≥ 1.5 (수수료 포함 시 실질 1.3 이상)를 달성하려면:
- 현재 R:R(1.10:1) 유지 시 → 승률 58% 필요 (현재 36%)
- 현재 승률(36%) 유지 시 → R:R 3.5:1 필요 (TP ≈ 12%, SL ≈ -3.5%)

---

## Part C. 구체적 개선 제안

### Tier 1: 즉시 적용 (코드 수정 + 설정 변경)

#### C-1. 온도 시스템 연결 [치명적 버그 수정]

**파일**: `run_ai_swing_bot.py`
**위치**: 메인 루프, 온도 계산 후
**현상**: `strategy.apply_temperature()` 미호출

```python
# 현재 코드: 온도를 계산하지만 전략에 적용하지 않음
cached_temp["result"] = market_temp.calculate()

# 수정: 온도 계산 후 전략에 적용
cached_temp["result"] = market_temp.calculate()
profiles = market_temp.config.get("strategy_profiles", {})
strategy.apply_temperature(cached_temp["result"], profiles)
# trading_rules도 온도에 따라 리로드
trader.trading_rules = trader._load_trading_rules()
```

**영향**: 모든 k, TP, SL, ATR 멀티플라이어가 시장 상황에 맞게 동적 조절됨.

#### C-2. 매도 후 상태 추적 수정 [안전장치 복원]

**파일**: `swing_trader.py`, `_execute_sell()` 메서드 (line 162-177)
**현상**: 매도 후 `sold_today`, `daily_realized_pnl`, `consecutive_sl_count` 미업데이트, `portfolio` 미삭제

추가해야 할 로직:
```python
def _execute_sell(self, code, name, qty, current_price, trade_type, reason):
    # ... 기존 API 호출 및 로깅 ...
    if result and (...):
        # 추가 필요:
        avg_price = self.portfolio.get(code, {}).get('buy_price', 0)
        pnl = (current_price - avg_price) * qty  # 실현 손익
        self.daily_realized_pnl += pnl
        self.sold_today[code] = {
            "time": datetime.datetime.now(),
            "profitable": pnl > 0,
        }
        if trade_type == "SELL_HARD_STOP":
            self.consecutive_sl_count += 1
            # ... 연속SL 브레이크 로직 ...
        else:
            self.consecutive_sl_count = 0
        del self.portfolio[code]
```

#### C-3. 포지션 사이징 제한 추가

**파일**: `trading_rules.yaml`
**현상**: `target_allocation_per_stock` 미정의 → 기본값 1,000,000원 (전체 예산)

```yaml
# trading_rules.yaml에 추가
rules:
  target_allocation_per_stock: 150000   # 건당 최대 15만원
```

또는 `swing_trader.py:99-101`을 수정하여 `max_position_amount` 규칙을 SwingTrader에서도 적용:
```python
# max_position_amount 규칙 적용 (FirefeetTrader와 동일)
pos_rule = self.trading_rules.get("max_position_amount", {})
if pos_rule.get("enabled", False):
    max_pos = pos_rule.get("default_amount", 150000)
    budget = min(budget, max_pos)
```

#### C-4. screener_score 전달

**파일**: `run_ai_swing_bot.py:275`
**현상**: 항상 0으로 하드코딩

스크리너 결과를 캐싱하여 `ai_data_provider`에 주입:
```python
# screener 결과 캐시 (scan 단계에서 저장)
screener_cache = {}  # {code: score}

# scan 후:
for r in screened_stocks:
    screener_cache[r["code"]] = r["total_score"]

# ai_data_provider 내:
"screener_score": screener_cache.get(code, 0)
```

### Tier 2: 구조적 로직 개선 (1~2일 작업)

#### C-5. TP/SL 비율 재설계 -- R:R 2:1 이상 확보

현재 NEUTRAL: TP=3.0%, SL=-3.0% → R:R 1:1

**제안 프로파일 (스윙용):**

| 레벨 | k | TP | SL | ATR SL×M | ATR TP×M | R:R |
|------|-----|------|------|----------|----------|-----|
| HOT | 0.3 | 8.0% | -3.0% | 1.5 | 4.0 | 2.7:1 |
| WARM | 0.4 | 6.0% | -3.0% | 2.0 | 4.0 | 2.0:1 |
| NEUTRAL | 0.5 | 6.0% | -3.0% | 2.5 | 5.0 | 2.0:1 |
| COOL | 0.6 | 5.0% | -2.5% | 2.5 | 4.0 | 2.0:1 |
| COLD | 0.7 | 4.0% | -2.0% | 3.0 | 4.0 | 2.0:1 |

**근거**: 스윙(3일~2주 보유)에서 TP 3%는 "데이트레이딩 TP"이다. 한국 KOSPI/KOSDAQ 종목의 주간 변동폭은 5~15%가 일반적이므로, TP 6~8%가 합리적이다. SL은 ATR 기반으로 노이즈 밖에 두되, 고정 floor -3%는 유지한다.

#### C-6. 시간대 필터 추가

**파일**: `swing_trader.py`, `_process_ai_buy()` 메서드

```python
# 10:30 이후 신규 매수 차단 (또는 confidence 상향)
time_int = int(time_str[:4])
if time_int >= 1030:
    min_confidence = max(min_confidence, 90)  # 오후 진입 시 확신도 90 이상 요구
if time_int >= 1400:
    return  # 14:00 이후 신규 스윙 매수 금지 (오버나잇 리스크)
```

**근거**: 09시대만 수익인 것은 모멘텀 소진 때문. 오후 진입은 당일 추세의 말기에 해당하며, 다음날 갭다운 리스크가 있다.

#### C-7. Sanity Check 범위 강화

**파일**: `ai_swing_agent.py:130-152`

```python
if action == "BUY":
    # 범위 체크 추가 (문서와 코드 일치시키기)
    if target <= price * 1.03 or target >= price * 1.30:
        decision["decision"] = "WAIT"
        decision["reasoning"] = f"Target price out of range: {target} vs [{price*1.03:.0f}, {price*1.30:.0f}]"
    if stop <= price * 0.85 or stop >= price * 0.98:
        decision["decision"] = "WAIT"
        decision["reasoning"] = f"Stop loss out of range: {stop} vs [{price*0.85:.0f}, {price*0.98:.0f}]"
```

#### C-8. AI 판단에 ATR/수축 정보 전달

**파일**: `ai_swing_agent.py:48-56`

hard_facts에 추가 정보 포함:
```python
hard_facts = {
    "current_price": current_price,
    "score": screener_score,
    "atr14": data.get("atr14"),
    "contraction_ratio": data.get("contraction_ratio"),
    "temperature_level": data.get("market_temp", {}).get("level", "N/A"),
    "supply_sentiment": data.get("supply", {}).get("sentiment", "N/A") if isinstance(data.get("supply"), dict) else "N/A",
}
```

### Tier 3: 새로 추가해야 할 필터/조건 (3~5일 작업)

#### C-9. 변동성 돌파 시그널 게이트 복원

스윙봇에서도 `check_buy_signal()`을 AI 판단 전 pre-filter로 사용:

```python
# swing_trader.py, _process_ai_buy() 내
ohlc = ai_data.get('ohlc')
if ohlc is not None and self.strategy:
    signal = self.strategy.check_buy_signal(code, ohlc, current_price)
    if not signal or signal['signal'] != 'BUY':
        return  # 변동성 돌파 미달 → AI 호출 자체를 스킵
```

**효과**: AI 호출 횟수 감소 (쿼터 절약) + 변동성 돌파가 확인된 종목만 AI가 분석.

#### C-10. 스윙 전용 스코어링 팩터 추가

현재 스크리너는 데이트레이딩에 최적화되어 있다. 스윙 전용 팩터 제안:

| 팩터 | 가중치 | 설명 |
|------|--------|------|
| 다일 모멘텀 (5일) | 15% | 5일간 양봉 비율 + 누적 수익률 |
| 기관 연속 매수 일수 | 15% | 기관이 3일 이상 연속 순매수 시 가산 |
| 이격도 (MA20) | 10% | 현재가 / MA20 비율. 1.00~1.05 구간이 최적 |
| ATR 수축 보너스 | 20% | 핵심 전략이므로 가중치 대폭 상향 |

#### C-11. Trailing Stop 구현

현재는 고정 TP만 있고, 수익이 나는 동안 따라가는 Trailing Stop이 없다:

```python
# 제안: ATR 기반 트레일링 스탑
if profit_rate >= 3.0:  # 3% 이상 수익 시 활성화
    trailing_sl = max_profit_rate - (atr14 * 1.5 / avg_price * 100)
    if profit_rate <= trailing_sl:
        return "SELL_TRAILING_STOP"
```

**효과**: TP 6%로 높여도, 중간에 반전 시 수익을 보전. 추세가 강하면 6% 이상도 가능.

#### C-12. 일일 매매 건수 제한

36건/일은 "스윙 트레이딩"이 아니라 "고빈도 데이트레이딩"이다. 스윙에서는 3~5건/일이 적정.

```yaml
# trading_rules.yaml에 추가
rules:
  max_daily_trades:
    enabled: true
    max_buy_count: 5      # 일일 최대 매수 5건
    max_sell_count: 10     # 매도는 보유 종목 전체 허용
```

---

## Trade-offs 요약

| 개선안 | Pros | Cons |
|--------|------|------|
| C-1. 온도 연결 | 시장 적응형 전략, COLD 시장에서 방어적 매매 | 온도 계산 오류 시 잘못된 파라미터 적용 가능 |
| C-2. 매도 후 추적 | 안전장치(연속SL 브레이크, 일일한도) 정상 작동 | 추가 코드 복잡도 (하지만 필수 수정) |
| C-3. 포지션 제한 | 단일 종목 집중 리스크 제거 | 확신도 높은 기회에서 수익 제한 |
| C-5. TP 상향 | R:R 개선, PF 상승 가능 | TP 도달 확률 하락, 보유 기간 증가 |
| C-6. 시간 필터 | 오후 추격매수 방지, 승률 개선 | 오후 유효 기회 놓칠 수 있음 |
| C-9. 돌파 게이트 | AI 쿼터 절약, 시그널 품질 향상 | 돌파 전 눌림목 매수 기회 차단 |
| C-11. 트레일링 | 대세 상승 시 수익 극대화 | 구현 복잡도, 변동성 큰 종목에서 조기 청산 |
| C-12. 건수 제한 | 과매매 방지, 수수료 절감 | 기회 제한 |

---

## 우선순위 로드맵

```
[Phase 1: 긴급 수정] — 1일 이내
├── C-1. 온도 시스템 연결 (치명적 버그)
├── C-2. 매도 후 상태 추적 (안전장치 복원)
├── C-3. 포지션 사이징 제한
└── C-4. screener_score 전달

[Phase 2: R:R 구조 개선] — 2~3일
├── C-5. TP/SL 비율 재설계 (R:R 2:1+)
├── C-6. 시간대 필터
├── C-7. Sanity Check 강화
└── C-8. AI hard_facts 확장

[Phase 3: 전략 고도화] — 1주
├── C-9. 변동성 돌파 게이트 복원
├── C-10. 스윙 전용 스코어링
├── C-11. Trailing Stop
└── C-12. 일일 매매 건수 제한
```

---

## 수치 목표

Phase 1+2 완료 후 기대 효과:

| 지표 | 현재 | 목표 | 근거 |
|------|------|------|------|
| 승률 | 36.1% | 45%+ | 시간 필터 + 돌파 게이트로 저품질 진입 차단 |
| R:R | 1.10:1 | 2.0:1+ | TP 상향(6%+), SL 유지(-3%) |
| PF | 0.43 | 1.5+ | 승률 45% × R:R 2:1 = PF 1.64 |
| 일일 매매 건수 | 36건 | 5~8건 | 건수 제한 + 돌파 게이트 |
| 일일 손익 | -70K | +10K~+30K | 구조적 양의 기대값 확보 |

---

## 참조 파일

| 파일 | 핵심 발견 |
|------|----------|
| `run_ai_swing_bot.py:275` | screener_score 항상 0으로 하드코딩 |
| `run_ai_swing_bot.py` 전체 | `strategy.apply_temperature()` 미호출 |
| `swing_trader.py:99-101` | `target_allocation_per_stock` 미정의 → 기본값 100만원 |
| `swing_trader.py:162-177` | `_execute_sell()`에서 sold_today/pnl/SL카운터 미업데이트, portfolio 미삭제 |
| `scoring_engine.py:229-230` | 데이터 부족 시 MA120 필터 무효화 |
| `scoring_engine.py:246-268` | 수축 보너스 가중치 10% (과소) |
| `technical.py:74-103` | `check_buy_signal()` — 스윙봇에서 미사용 |
| `ai_swing_agent.py:48-56` | hard_facts에 price, score만 포함 |
| `ai_swing_agent.py:130-152` | sanity check 범위 미구현 (문서와 불일치) |
| `claude_executor.py:14` | 구 버전 모델 사용 (`claude-3-5-sonnet-20241022`) |
| `trading_rules.yaml` | `target_allocation_per_stock`, `hard_stop_loss_pct`, `hard_sl_atr_multiplier` 미정의 |
| `temperature_config.yaml` | 전략 프로파일 정의되어 있으나 스윙봇에서 미사용 |
