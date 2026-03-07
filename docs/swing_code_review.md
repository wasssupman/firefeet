# 스윙 트레이딩 코드 품질 리뷰

**리뷰 일자**: 2026-03-03
**리뷰 대상**: AI 스윙 트레이딩 파이프라인 (9개 파일)
**리뷰어**: Quality Reviewer (oh-my-claudecode)

---

## 요약

| 영역 | 평가 |
|------|------|
| 전체 | NEEDS WORK |
| 로직 정확성 | warn |
| 에러 처리 | warn |
| 설계 | warn |
| 유지보수성 | warn |

심각한 버그는 없으나 **운영 중 손실을 유발할 수 있는 로직 결함이 2건**(CRITICAL), 실무적으로 위험한 설계 문제가 다수 존재한다. 나머지는 유지보수성 및 일관성 문제다.

---

## CRITICAL 이슈 (즉시 수정 필요)

### C-1. `screener_score`가 항상 0으로 AI에 전달됨

**파일**: `run_ai_swing_bot.py:275`

```python
"screener_score": 0  # (실제 구현 시 Screener 결과를 캐싱하여 주입 고려)
```

`ai_data_provider()` 함수가 AI 분석 데이터를 조립할 때 `screener_score`를 항상 `0`으로 하드코딩하여 전달한다. Screener가 산출한 실제 점수(0~100점)가 AI 프롬프트에 전혀 반영되지 않는다.

`ClaudeAnalyst._build_analyst_prompt()`는 이 점수를 "초기 퀀트 스코어: {score} / 100"으로 프롬프트에 삽입하며, `ClaudeExecutor._build_executor_prompt()`도 "퀀트 스코어: {score}"로 판단에 사용한다. 스크리닝 단계에서 70점을 받은 종목과 35점짜리 종목이 AI에게 동일한 0점으로 보이므로 AI의 품질 판단이 체계적으로 오염된다.

**수정 방향**: `screen()` 결과를 딕셔너리(`{code: score}`)로 캐싱한 뒤 `ai_data_provider` 클로저에서 참조한다.

```python
# run_ai_swing_bot.py 수정 예시
screener_score_cache: dict = {}

# screened_stocks를 받은 직후
for r in screened_stocks:
    screener_score_cache[r["code"]] = r["total_score"]

def ai_data_provider(code):
    ...
    return {
        ...
        "screener_score": screener_score_cache.get(code, 0),
    }
```

---

### C-2. `SwingTrader`에 `strategy=None`을 전달 — 상속된 매도 경로가 런타임에 크래시

**파일**: `run_ai_swing_bot.py:202`, `core/execution/swing_trader.py:17-18`

```python
# run_ai_swing_bot.py:202
trader = SwingTrader(manager, ai_agent, strategy=None, discord_client=discord)
```

`SwingTrader`는 `FirefeetTrader`를 상속하며, 부모의 `__init__`에서 `self.strategy = strategy`로 저장된다. 부모 클래스의 `_process_sell()` (`trader.py:340`)은 `self.strategy.should_sell(...)`을 직접 호출하는데, `strategy`가 `None`이면 `AttributeError`로 크래시한다.

`SwingTrader`는 `_process_ai_sell()`을 통해 AI 경로로 매도를 처리하므로 부모의 `_process_sell()`이 정상 경로에서는 호출되지 않는다. 그러나 `FirefeetTrader.run_loop()`이나 `process_stock()`이 실수로 호출될 경우, 또는 향후 코드 변경 시 `strategy=None`이 크래시를 일으킨다.

**수정 방향**: `strategy=None`을 허용하려면 `SwingTrader`에서 `_process_sell`과 `_process_buy`를 명시적으로 오버라이드하여 부모 구현이 호출되지 않도록 보호한다.

```python
# swing_trader.py 수정 예시
def _process_sell(self, code, name, time_str, df, current_price):
    raise NotImplementedError(
        "SwingTrader는 process_stock_with_ai()를 통해 _process_ai_sell()을 사용합니다."
    )

def _process_buy(self, code, name, time_str, df, current_price):
    raise NotImplementedError(
        "SwingTrader는 process_stock_with_ai()를 통해 _process_ai_buy()를 사용합니다."
    )
```

---

## HIGH 이슈 (높은 확률의 운영 문제)

### H-1. 중복 `order_no` 체크 — 죽은 가드 코드

**파일**: `core/execution/trader.py:364-370`

```python
if not order_no:           # line 364 — 실패 시 return
    ...
    return

if order_no:               # line 370 — 항상 True (불필요한 가드)
    print(f"  -> Order Placed! No: {order_no}")
    sell_info = self.trade_logger.log_sell(...)
```

`line 364`에서 `order_no`가 없으면 `return`하므로, `line 370`의 `if order_no:` 가드는 항상 `True`다. 코드 자체는 올바르게 동작하지만, 향후 `return` 위치를 바꾸거나 로직을 수정할 때 이 패턴이 의도를 모호하게 만든다.

**수정 방향**: `if order_no:` 블록을 제거하고 하위 코드를 직접 실행한다.

---

### H-2. ATR 임포트가 함수 내부에 숨어 있음 — 숨겨진 의존성

**파일**: `core/execution/swing_trader.py:143`, `core/analysis/scoring_engine.py:257`

```python
# swing_trader.py:143 — _process_ai_sell 내부
from core.analysis.technical import VolatilityBreakoutStrategy
atr14 = VolatilityBreakoutStrategy.calculate_atr(ohlc, period=14)

# scoring_engine.py:257 — _score_contraction_bonus 내부
from core.analysis.technical import VolatilityBreakoutStrategy
ratio = VolatilityBreakoutStrategy().get_contraction_ratio(ohlc)
```

두 곳 모두 함수 내부에서 임포트하고 있어 파일 상단 임포트 목록만 보고는 의존성을 파악할 수 없다. `_process_ai_sell`은 보유 종목마다 매 루프(기본 10초)에 호출된다.

추가로 `scoring_engine.py:257`에서는 `VolatilityBreakoutStrategy()`를 인스턴스로 생성한다. `get_contraction_ratio`는 인스턴스 메서드이지만 `self`를 전혀 사용하지 않으므로 불필요한 객체 생성이다. `calculate_atr`는 `@staticmethod`인데 `get_contraction_ratio`는 인스턴스 메서드인 것도 일관성 없다.

**수정 방향**: 임포트를 파일 상단으로 이동한다. `get_contraction_ratio`를 `@staticmethod`로 변환하거나, `calculate_atr`처럼 호출할 수 있도록 정리한다.

---

### H-3. VisionAnalyst 에러 시 `REJECT` 반환 — 네트워크 오류가 매수를 차단

**파일**: `core/analysis/llms/vision_analyst.py:99-106`

```python
except Exception as e:
    logger.error(f"[{name}({code})] VisionAnalyst error: {e}")
    return {
        "action": "REJECT",
        "confidence": 0,
        "risk_level": "HIGH",
        "reason": f"Vision check failed (안전 기각): {str(e)}"
    }
```

Vision API 호출 실패(네트워크 타임아웃, API 한도 초과, 임시 장애 등) 시 `REJECT`를 반환한다. 이 결과를 `ai_swing_agent.py:103`에서 `if vision_result.get("action") == "REJECT":`로 체크하여 이미 Analyst+Executor가 `BUY`로 결정한 종목을 `WAIT`으로 뒤집는다.

즉, **인프라 장애가 매수 기회 손실로 직결된다.** 반면 같은 파일의 mock 모드(API 키 미설정)는 `CONFIRM`을 반환하는 비대칭이 있다.

**수정 방향**: API 오류와 분석 기각을 구분한다. API 호출 실패는 `CONFIRM`(또는 `SKIP`) 반환하여 상위 파이프라인에서 Vision 단계를 건너뛰도록 한다. 분석 후 위험하다고 판단한 경우만 `REJECT`로 처리한다.

```python
except Exception as e:
    logger.warning(f"[{name}({code})] VisionAnalyst API 장애 — 검증 스킵: {e}")
    return {
        "action": "CONFIRM",   # REJECT가 아닌 CONFIRM으로 패스스루
        "confidence": 0,
        "risk_level": "UNKNOWN",
        "reason": f"Vision API 일시 불가: {str(e)}"
    }
```

---

### H-4. 쿼터 파일을 `"a+"` 모드로 열고 `truncate` — 파일 내용 오염 가능

**파일**: `core/analysis/ai_swing_agent.py:177-202`

```python
with open(self.usage_file, "a+", encoding="utf-8") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    try:
        f.seek(0)
        content = f.read().strip()
        ...
        f.seek(0)
        f.truncate()
        json.dump(usage_data, f)
```

`"a+"` 모드로 파일을 열면 일부 OS/파일시스템에서 쓰기 포인터가 항상 파일 끝에 고정되어, `f.seek(0)` + `f.truncate()`를 해도 `json.dump`가 파일 끝에 추가될 수 있다. 쿼터 파일이 오염되면 JSON 파싱 실패로 이어지고, 예외 처리(`line 206-208`)가 쿼터를 허용(`return True`)하므로 일일 한도가 무력화된다.

**수정 방향**: `tempfile` + `os.replace()`로 원자적 쓰기를 사용한다.

```python
import tempfile

tmp_path = self.usage_file + ".tmp"
with open(tmp_path, "w", encoding="utf-8") as f:
    json.dump(usage_data, f)
os.replace(tmp_path, self.usage_file)
```

---

## MEDIUM 이슈 (유지보수성 문제)

### M-1. 죽은 코드 — `copy` import

**파일**: `core/execution/swing_trader.py:1`, `core/execution/trader.py:1`

```python
import copy  # swing_trader.py:1 — 사용처 없음
import copy  # trader.py:1 — 사용처 없음
```

두 파일 모두 `copy`를 import하지만 `copy.copy()`, `copy.deepcopy()` 등 어디에서도 사용하지 않는다.

**수정 방향**: 두 파일에서 `import copy`를 제거한다.

---

### M-2. 죽은 코드 — `yaml` import (swing_trader.py)

**파일**: `core/execution/swing_trader.py:4`

```python
import yaml  # 사용되지 않음
```

`swing_trader.py`에서 `yaml`은 한 번도 사용되지 않는다. YAML 로딩은 부모 클래스 `FirefeetTrader`에서 처리한다.

**수정 방향**: 제거한다.

---

### M-3. 파라미터명 오타 — `discard_client`

**파일**: `core/execution/trader.py:10`

```python
def __init__(self, manager, strategy, discard_client=None, ...):
    self.discord = discard_client
```

파라미터명이 `discard_client`(버리다)로 오타가 나 있다. `discord_client`여야 한다. `SwingTrader`는 `discord_client=discord`로 올바르게 전달하지만 부모의 시그니처에서 `discard_client`로 받는다. 현재는 위치 인자가 아닌 키워드 인자로 전달하지 않으면 동작하지만, 부모를 직접 사용하는 코드에서 `discord_client=` 키워드 인자를 쓰면 `TypeError`가 발생한다.

**수정 방향**: `discard_client` → `discord_client`로 수정한다.

---

### M-4. `_process_ai_buy`와 `_process_ai_sell`에서 `time_str` 미사용

**파일**: `core/execution/swing_trader.py:67, 126`

```python
def _process_ai_buy(self, code, name, time_str, ai_data, current_price):
def _process_ai_sell(self, code, name, time_str, ai_data, current_price, held_qty):
```

두 메서드 모두 `time_str`을 파라미터로 받지만 함수 내부에서 전혀 사용하지 않는다.

**수정 방향**: 실제 사용하거나 제거한다. 제거 시 `process_stock_with_ai` 호출부도 함께 정리한다.

---

### M-5. 함수 내부 임포트 — `ai_swing_agent.py`

**파일**: `core/analysis/ai_swing_agent.py:24, 100`

```python
def __init__(self, ...):
    import yaml         # __init__ 내부

# Phase 3에서:
from utils.chart_renderer import render_chart_to_bytes   # line 100
```

`yaml`은 `__init__` 내부에서만 사용된다. 파일 상단에 임포트가 없어서 이 클래스가 yaml에 의존한다는 것을 상단에서 파악할 수 없다. `render_chart_to_bytes` 역시 BUY 결정 시마다 동적 임포트된다.

**수정 방향**: 모든 임포트를 파일 상단으로 이동한다. 선택적 의존성(`chart_renderer` 등)은 `try/except ImportError`로 상단에서 처리한다.

```python
# 파일 상단
import yaml

try:
    from utils.chart_renderer import render_chart_to_bytes
    _CHART_RENDERER_AVAILABLE = True
except ImportError:
    _CHART_RENDERER_AVAILABLE = False
```

---

### M-6. `_safe_fallback_json`과 `_fallback_json`의 스키마 불일치

**파일**: `core/analysis/ai_swing_agent.py:154-163`, `core/analysis/llms/claude_executor.py:145-154`

`AISwingAgent._safe_fallback_json()` 반환값:
```python
{
    "decision": "WAIT",
    "confidence": 0,
    "strategy_type": "NONE",
    "stop_loss": 0,
    "qty_ratio": 0.0,
    "reasoning": "Fallback Triggered."
    # target_price 키 없음
}
```

`ClaudeExecutor._fallback_json()` 반환값:
```python
{
    "decision": "HOLD",       # WAIT이 아닌 HOLD
    "confidence": 0,
    "strategy_type": "WAITING",  # "NONE"이 아닌 "WAITING"
    "target_price": 0,
    "stop_loss": 0,
    "reasoning": "Fallback triggered..."
    # qty_ratio 키 없음
}
```

두 폴백이 서로 다른 `decision` 값(`"WAIT"` vs `"HOLD"`)을 반환하며 키 집합도 다르다. 현재 `swing_trader.py`의 매수 로직은 `ai_decision != 'BUY'`로 체크하므로 둘 다 차단하지만, 나중에 `"HOLD"`와 `"WAIT"`을 구분하는 로직이 추가되면 이 불일치가 버그가 된다. `target_price`가 없는 `_safe_fallback_json`을 `_sanity_check`에 전달하면 `float(decision.get("target_price", 0))`로 0을 처리하므로 현재는 우연히 작동한다.

**수정 방향**: 단일 `_build_fallback(decision="WAIT")`으로 통합하고 스키마를 표준화한다.

---

### M-7. `_process_sell`에서 `buy_price == 0`일 때 현재가로 대체

**파일**: `core/execution/trader.py:336-338`

```python
buy_price = self.portfolio[code]['buy_price']
if buy_price == 0:
    buy_price = current_price
```

매입가가 0이면 현재가로 대체하여 수익률을 항상 0%로 만든다. 이 경우 손절(SELL_STOP_LOSS) 조건이 절대 발동하지 않으며 익절도 발동하지 않는다. 실제로 매입가 데이터가 손실된 포지션은 영원히 보유 상태로 남을 수 있다.

**수정 방향**: `buy_price == 0`이면 `sync_portfolio()`를 재시도하거나 경고 로그를 남기고 해당 종목을 스킵한다. 현재가로 대체하는 것은 논리적으로 위험하다.

---

### M-8. `screener_data_provider`가 MA120 필터와 스코어링에서 이중 호출됨

**파일**: `run_ai_swing_bot.py:242-254`, `core/analysis/scoring_engine.py:330-363`

`screen()` 내부에서 MA120 필터(step 1.5)와 스코어링(step 2) 각각에서 `data_provider_fn(code)`를 호출한다. 종목당 최소 **2회** `screener_data_provider`가 호출되며, 각 호출은 KIS API를 3번씩 호출한다(`get_daily_ohlc`, `get_investor_trend`, `get_current_price`). 종목 15개 기준 최대 **90회 API 호출**이 단일 스크리닝 사이클에 발생한다.

**수정 방향**: `screen()` 내에서 결과를 딕셔너리로 캐싱한다.

```python
# scoring_engine.py screen() 내부 수정 예시
data_cache = {}
def cached_provider(code):
    if code not in data_cache:
        data_cache[code] = data_provider_fn(code)
    return data_cache[code]
```

---

### M-9. `check_buy_signal`에 주석 번호가 건너뜀

**파일**: `core/analysis/technical.py:79-86`

```python
# 1. Get Target Price
target_info = self.get_target_price(code, df)
...
# 3. Check Signal    ← 2번이 없음
```

주석 번호가 1에서 3으로 건너뛴다. 과거 로직이 삭제되면서 남겨진 잔존 주석이다.

**수정 방향**: `# 2.`를 삭제하거나 번호를 재정렬한다.

---

### M-10. `_dart_holdings_sync` 스레드가 종료 조건 없음

**파일**: `run_ai_swing_bot.py:212-216`

```python
def _dart_holdings_sync():
    while True:
        dart_handler.holdings = trader.portfolio.copy() ...
        time.sleep(10)
```

`daemon=True`이므로 메인 프로세스 종료 시 함께 종료되어 실질적 문제는 없다. 그러나 `while True` + `time.sleep(10)`은 종료 신호를 받아도 최대 10초간 블로킹된다.

**수정 방향**: `threading.Event`를 사용하면 즉시 종료 가능하다.

```python
_stop_event = threading.Event()

def _dart_holdings_sync():
    while not _stop_event.is_set():
        dart_handler.holdings = trader.portfolio.copy() ...
        _stop_event.wait(10)  # time.sleep 대신
```

---

### M-11. 스코어 가중치 합계 검증 없음

**파일**: `core/analysis/scoring_engine.py:22-31`, `score_stock():291`

기본 가중치 합계는 100으로 정확하다(20+10+20+20+15+5+10=100). 그러나 YAML에서 가중치를 오버라이드할 때 합계가 100이 되는지 검증하는 코드가 없다. 잘못된 설정이 들어오면 최종 점수가 100을 초과하거나 크게 미달할 수 있다.

**수정 방향**: `_load_settings()` 또는 `score_stock()` 시작 부분에서 가중치 합계를 검증한다.

```python
total_weight = sum(weights.values())
if abs(total_weight - 100) > 0.1:
    print(f"[Screener] 경고: 가중치 합계={total_weight} (100이 아님) — 점수가 왜곡될 수 있음")
```

---

## LOW 이슈 (소규모 개선)

### L-1. `_score_breakout_proximity`에서 `today`, `yesterday` 변수 미사용

**파일**: `core/analysis/scoring_engine.py:171-172`

```python
today = ohlc.iloc[0]
yesterday = ohlc.iloc[1]
```

두 변수를 선언하고 나서 실제로는 사용하지 않는다. `target_info`는 `strategy.get_target_price(code, ohlc)`에서 직접 계산되므로 이 두 줄은 죽은 코드다.

**수정 방향**: 두 줄을 제거한다.

---

### L-2. `compact_prompt` 조건이 Analyst와 Executor 사이에서 비대칭

**파일**: `core/analysis/llms/claude_analyst.py:109`, `core/analysis/llms/claude_executor.py:66`

```python
# claude_analyst.py:109 — compact_prompt만 체크
if self.compact_prompt:
    return self._build_compact_prompt(...)

# claude_executor.py:66 — compact_prompt AND use_cli 둘 다 요구
if self.compact_prompt and self.use_cli:
    return self._build_compact_executor_prompt(...)
```

`compact_prompt=True`이고 `use_cli=False`(API 직접 사용)이면 Analyst는 compact 프롬프트를 쓰지만 Executor는 풀 프롬프트를 쓴다. 이 비대칭은 의도인지 버그인지 명확하지 않다.

**수정 방향**: 동일한 조건으로 통일하고 주석으로 의도를 명확히 한다.

---

### L-3. `time_str` 형식 불일치

**파일**: `run_ai_swing_bot.py:292`, `core/execution/trader.py:212`

```python
# run_ai_swing_bot.py:292
time_str = now.strftime("%H%M%S")  # 6자리 "HHMMSS"

# trader.py:212
time_str = now.strftime("%H%M")    # 4자리 "HHMM"
```

`should_sell()`(`technical.py:163`)은 `int(current_time_str.replace(":", "")[:4])`로 앞 4자리만 취하므로 6자리를 전달해도 동작한다. 그러나 두 곳에서 서로 다른 형식을 사용하는 것은 혼란스럽다. docstring(`swing_trader.py:35`)은 `"HHMMSS"`로 명시하고 있어 의도는 6자리이나, 실제 `should_sell()`은 4자리를 기대한다.

**수정 방향**: 전체에서 `"%H%M"` (4자리)로 통일하거나, `should_sell()`이 6자리를 명시적으로 처리하도록 수정한다.

---

## 긍정적 관찰

1. **의존성 주입(DI) 설계** — `AISwingAgent`가 `IAnalystLLM`, `IExecutorLLM` 인터페이스를 통해 구체 구현과 분리되어 있어 모킹과 교체가 용이하다. 테스트 코드에서 `MockAnalyst`를 주입하는 구조가 잘 구현되어 있다.

2. **3단계 폴백 체인** — Analyst가 API → CLI → Mock 순으로 폴백하는 구조는 가용성을 높인다. 무엇이 실패해도 봇이 멈추지 않는다.

3. **파일 락 기반 쿼터 관리** — `fcntl.flock`을 활용한 멀티프로세스 안전 쿼터 구현은 단순하지만 의도가 올바르다.

4. **ATR 기반 구조적 손절** — 고정 % 손절을 floor로, ATR이 더 넓으면 ATR을 사용하는 `min(hard_stop, atr_sl_pct)` 로직은 변동성이 큰 종목을 과도한 노이즈 청산으로부터 보호하는 좋은 설계다 (`swing_trader.py:139-147`).

5. **LLM 환각 방어** — LLM이 비논리적 가격(target < 현재가, stop > 현재가)을 반환하는 것을 Python 레벨에서 차단하는 `_sanity_check`는 실무적으로 중요한 안전장치다 (`ai_swing_agent.py:130-152`).

6. **체결 미확인 시 임시 기록 패턴** — 주문 접수 후 체결 미확인 시 임시 포트폴리오 기록을 남겨 다음 동기화에서 실제가로 보정하는 패턴은 KIS API의 비동기 체결 특성을 잘 다루고 있다 (`trader.py:319-327`).

7. **MA120 이중 조건 추세 필터** — Stage 2 확인을 위해 가격 > MA120 + MA120 기울기 > 0(20일 전 대비)을 모두 체크하는 조건은 단순 MA 크로스보다 강인하다 (`scoring_engine.py:222-244`).

8. **중복 실행 방지 PID 락** — `_acquire_lock()` / `_release_lock()`을 통해 봇이 중복 실행되는 것을 막고, SIGTERM 핸들러를 통해 `finally` 블록에서 락을 해제하는 구조가 잘 구현되어 있다 (`run_ai_swing_bot.py:39-65`).

---

## 수정 우선순위 요약

| 우선순위 | 심각도 | 이슈 | 파일:라인 | 영향 |
|---------|-------|------|----------|------|
| 1 | CRITICAL | screener_score 항상 0 | `run_ai_swing_bot.py:275` | AI 판단 품질 체계적 오염 |
| 2 | CRITICAL | strategy=None 잠재 크래시 | `run_ai_swing_bot.py:202` | 향후 리팩토링 시 런타임 오류 |
| 3 | HIGH | Vision 에러 → REJECT | `vision_analyst.py:99` | 인프라 장애로 매수 기회 손실 |
| 4 | HIGH | 쿼터 파일 a+ 모드 | `ai_swing_agent.py:177` | 쿼터 파일 오염 시 한도 무력화 |
| 5 | MEDIUM | discard_client 오타 | `trader.py:10` | 키워드 인자 사용 시 TypeError |
| 6 | MEDIUM | 폴백 스키마 불일치 | `ai_swing_agent.py:154`, `claude_executor.py:145` | 향후 분기 로직 추가 시 버그 |
| 7 | MEDIUM | buy_price==0 현재가 대체 | `trader.py:336` | 데이터 손실 포지션 영구 보유 |
| 8 | MEDIUM | 이중 API 호출 | `scoring_engine.py:330` | 스크리닝당 최대 90회 API 호출 |
| 9 | MEDIUM | 미사용 import (copy, yaml) | `swing_trader.py:1,4`, `trader.py:1` | 가독성 |
| 10 | HIGH | 함수 내부 임포트 (ATR) | `swing_trader.py:143`, `scoring_engine.py:257` | 숨겨진 의존성 |
