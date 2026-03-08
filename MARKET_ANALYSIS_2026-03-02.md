# 🔥 Firefeet Trading Strategy Analysis
## Market Open Preparation — 2026-03-02 (Monday)

---

## 📋 Executive Summary

**Last Updated:** 2026-03-02
**Data Period:** 2026-02-20 to 2026-02-27 (6 trading days)
**Systems Active:** AI Swing Trading + Scalping Bot
**Market Status:** Closed (Monday morning prep)

### Key Metrics
- **Scalping (275 trades):** -1,084,720 KRW (-98% from fees)
- **Swing Trading (50 trades):** Mixed performance (TP: +3-5%, SL: -3%)
- **Fee Impact:** 98.1% of losses attributable to transaction fees
- **Confidence Filter Impact:** conf≥0.35 reduces losses by 88%

---

## 🎯 CURRENT STRATEGY CONFIGURATION

### 1. AI SWING TRADING (Main System)
**File:** `run_ai_swing_bot.py`

#### Market Hours
- **Active:** 09:00-15:20 KST (weekdays only)
- **Health Check:** Claude CLI, Config, Discord Webhook, KIS API keys
- **Instance Lock:** PID file prevents duplicate runs (`/tmp/firefeet_ai_swing.pid`)

#### Core Principle
> "추세 안에서, 수축 이후의 확장을 산다."
> "Buy expansion after contraction within an uptrend"

**4-Pillar Architecture:**
1. **TREND (MA120 Filter)** — Stage 2 only (price > MA120, slope positive)
2. **CONTRACTION (ATR Ratio)** — ATR(5)/ATR(20) < 0.5 signals compression
3. **EXPANSION (Breakout)** — Volatility breakout = Open + Range×K
4. **RISK ANCHORING (ATR-based SL/TP)** — Structural stops tied to ATR(14)×Multiplier

#### Dual-LLM Pipeline (Analyst → Executor → Vision)

**Phase 1: Analyst (Claude Sonnet)**
- Inputs: OHLC, Supply/Demand, News, Market Temperature, Screener Score
- Output: Markdown analysis memo

**Phase 2: Executor (Claude Sonnet, temp=0.0)**
- Role: CRO (Chief Risk Officer)
- Sanity Check: Target ∈ [current×1.05, current×1.30], SL ∈ [current×0.90, current×0.95]
- Output: JSON {decision, confidence, target, stop, reasoning}

**Phase 3: Vision AI (Optional, BUY signals only)**
- Input: Price chart image
- Role: Visual cross-validation

#### Decision Schema
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

#### Screener: 7-Factor Composite Score

| Factor | Weight | 100pt | 0pt |
|--------|--------|-------|-----|
| Volume Surge | 20% | 5× daily avg | Below avg |
| Price Momentum | 10% | +3% (sweet spot) | ≤0% or ≥13% |
| MA Alignment | 20% | P > MA5 > MA20 wide | Reverse order |
| Supply/Demand | 20% | Foreign+Institution buy | Double sell |
| Breakout Proximity | 15% | Already broken | 5%+ away |
| **Contraction Bonus** | 10% | ATR(5)/ATR(20) < 0.5 | Already expanded >1.0 |
| Intraday Strength | 5% | Within -0.5% of HI | -3%+ below HI |

**Pre-Filter (no API needed):**
- Min volume: 500,000 shares
- Max price: 500,000 KRW
- Change rate: -2% to +15%

**AI Thematic Filter (Claude Sonnet):**
- Top 15 candidates by quant score
- Evaluates narrative + theme relevance
- Max workers: 5 (API rate limit safe)

---

### 2. TEMPERATURE-BASED STRATEGY ADAPTATION

**File:** `config/temperature_config.yaml`

#### Temperature Levels & Strategy Profiles

| Level | Range | k | TP | SL | Max% | ATR_SL×M | ATR_TP×M | Notes |
|-------|-------|-----|------|------|---------|----------|----------|---------|
| **HOT** | 70+ | 0.3 | 4.0% | -3.0% | 35% | 2.0 | 3.5 | Aggressive (tight SL, wide TP) |
| **WARM** | 40-69 | 0.4 | 3.5% | -3.0% | 30% | 2.0 | 3.0 | Balanced |
| **NEUTRAL** | -20-39 | 0.5 | 3.0% | -3.0% | 25% | 2.5 | 3.0 | Default |
| **COOL** | -60--21 | 0.6 | 2.5% | -2.5% | 20% | 2.5 | 2.5 | Defensive |
| **COLD** | <-60 | 0.7 | 2.0% | -2.0% | 15% | 3.0 | 2.0 | Very defensive |

#### Temperature Calculation
- **Macro (40%):** US Index, VIX, FX, Bond trends (3-day)
- **Sentiment (35%):** Naver news + Global news keywords (3-day weighted)
- **Econ (25%):** Economic surprise + uncertainty (high:2x, medium:1x, low:0.5x)

**Active Modules:**
- ✅ AI Macro Sentinel (Claude Sonnet) — News override capability
- ✅ Macro Trend — US Index, VIX, FX, Bond
- ✅ Sentiment Analysis — Naver Finance, Global News
- ✅ Economic Calendar — Surprises + Uncertainty

---

### 3. TRADING RULES (Risk Management)

**File:** `config/trading_rules.yaml`

#### Global Rules (All Temperatures)
| Rule | Setting | Effect |
|------|---------|--------|
| No Rebuy After Sell | Enabled | Cooldown: 0min (all day ban by default) |
| Scan Interval | 300 sec | 5-min stock discovery |
| Loop Interval | 10 sec | 10-sec trading loop |
| Max Holdings | Disabled | Unlimited |
| Consecutive SL Brake | 3× SL → 30 min cooldown | Circuit breaker |
| Max Position Amount | 150,000 KRW | Per-trade cap |
| Daily Loss Limit | -50,000 KRW | Stop trading if hit |

#### Temperature Overrides

**HOT (70+):**
- Rebuy after SL: ✅ (5 min cooldown)
- Scan: 180 sec (faster discovery)
- Loop: 7 sec (faster execution)
- Max holdings: 8 (aggressive)
- Circuit: 4× SL → 15 min cooldown
- Max position: 200,000 KRW
- Daily loss: -80,000 KRW

**WARM (40-69):**
- Rebuy after profitable sell: ✅ (10 min cooldown)
- Scan: 240 sec
- Max holdings: 6

**NEUTRAL (-20-39):**
- Rebuy after profit: ✅ (30 min cooldown for afternoon exhaustion)
- Max holdings: 15

**COOL/COLD:**
- Rebuy: ❌ (all day ban)
- Max holdings: 2-3 (very conservative)
- Daily loss: -30,000 KRW (tight)

---

### 4. SCALPING BOT (Secondary System)

**File:** `run_scalper.py`

#### Core Architecture
```
WebSocket (KIS)
  ├─ on_tick ──────→ TickBuffer (VWAP, momentum, volume accel)
  ├─ on_orderbook ─→ OrderbookAnalyzer (imbalance, spread, velocity)
  └─ on_notice ────→ 체결 통보 → positions update

Scanner (3-min rotation)
MarketTemperature (1× at market open)
ScalpEngine._eval_cycle() [1.5sec loop]
  ├─ Invariant checks (position/budget limits)
  ├─ EOD force-exit (15:28 PAPER / 15:20 REAL)
  ├─ Circuit breaker check
  ├─ Unfilled order mgmt (3sec timeout)
  ├─ Per-position: _eval_exit()
  └─ Per-target: _eval_entry()
```

#### 5 Signals (Composite Score 0-100)

| Signal | Weight | Input | Range |
|--------|--------|-------|-------|
| VWAP Reversion | 25% | VWAP distance + vol accel + 60s trend | 0-100 |
| Orderbook Pressure | 25% | Buy/sell imbalance + velocity + slope | 0-100 |
| Momentum Burst | 20% | Tick ratio + 10s momentum + volume | 0-100 |
| Volume Surge | 15% | 30s volume / 180s avg | 0-100 |
| Micro Trend | 15% | 10/30/60s momentum alignment | 0-100 |

**Composite = Weighted Sum (0-100), must exceed threshold to enter**

#### Entry Logic (_eval_entry)
1. Capacity check: open + pending < max_positions
2. Cooldown check: order (30s) + sell (600s default, 5min)
3. Data sufficiency: ≥30 ticks in buffer
4. Strategy selection: StrategySelector.select(time, temp) → StrategyProfile
5. Signal calc: ScalpStrategy.evaluate() → composite score
6. Penalty check: spread_penalty × volume_penalty < 0.5
7. Threshold: composite ≥ profile.confidence_threshold
8. Risk check: RiskManager.can_enter()
9. Order: place_order(BUY) → pending_orders

#### Exit Priority (by order)

| # | Condition | Signal | Type |
|---|-----------|--------|------|
| 1 | Loss limit exceeded | RISK | Market |
| 2 | Trailing stop (profit ≥ 0.5%, fallen 35%) | TRAILING | Market |
| 3 | Stop loss hit (profit ≤ SL%) | SL | Market |
| 4 | Take profit hit (profit ≥ TP%) | TP | Limit |
| 5 | Timeout (hold ≥ max_hold=180s) | TIMEOUT | Market |
| 6 | Signal reversal (hold≥90s, loss≥-0.15%, score<50%thr) | SIGNAL | Market |
| 7 | BB top (profit>0.25%, BB>0.9) | BB | Limit |
| 8 | Resistance (profit>0.25%, within 0.05%) | RESISTANCE | Limit |
| 9 | Sell wall detected (profit>0.25%, ask wall) | WALL | Limit |

**Key Issue (Critical):** SIGNAL exit 13건 전패 (0% win rate) → Logic bug suspected

#### Scalping Threshold 3-Level Override

**Current Hierarchy (after 2026-02-26 fix):**

```
1. StrategyProfile.confidence_threshold (highest priority)
   └─ momentum_scalp, orb, vwap_reversion: 0.40 (updated 2026-02-26)
   └─ adaptive: 0.35

2. Temperature override (scalping_rules.yaml)
   └─ HOT: 0.35, WARM: 0.38, NEUTRAL: 0.40, COOL: 0.45, COLD: 0.50

3. Global default (scalping_settings.yaml)
   └─ default_confidence_threshold: 0.40
```

**⚠️ Remaining Risk:** apply_temperature() still overwrites self.confidence_threshold for adaptive profiles. Non-profile paths get temperature values directly.

#### Temperature Impact on Scalping

| Level | Confidence | Max Pos | Mode | TP | SL |
|-------|------------|---------|------|----|----|
| HOT | 0.35 | 3 | aggressive | 2.0% | -0.8% |
| WARM | 0.38 | 2 | aggressive | 1.5% | -0.7% |
| NEUTRAL | 0.40 | 2 | aggressive | 1.2% | -0.5% |
| COOL | 0.45 | 2 | micro_swing | 1.0% | -0.5% |
| COLD | 0.50 | 1 | micro_swing | 0.8% | -0.4% |

#### Strategy Time Windows

| Strategy | Active | Temps | conf | TP | SL | Hold |
|----------|--------|-------|------|----|----|------|
| **ORB** | 09:00-09:30 | Any | 0.40 | 1.2% | -0.5% | 180s |
| **Momentum** | 09:30-12:00 | HOT/WARM/NEUTRAL | 0.40 | 1.2% | -0.5% | 180s |
| **VWAP** | 10:30-12:00 | NEUTRAL/COOL/COLD | 0.40 | 1.2% | -0.5% | 180s |
| **Adaptive** | (fallback) | Any | 0.35 | 1.2% | -0.5% | 180s |

**⚠️ Lunch Block:** 12:00-15:20 전체 차단 (오후장 제거)

#### Risk Rules (PAPER vs REAL)

| Item | PAPER | REAL |
|------|-------|------|
| Per-trade max loss | 10,000 KRW / 0.7% | 5,000 KRW / 0.5% |
| Per-trade max position | 2,000,000 KRW | 200,000 KRW |
| Daily max loss | 200,000 KRW | 30,000 KRW |
| Daily max trades | 20 | 50 |
| Circuit breaker | 5× loss → 300s cooldown | 5× loss → 600s cooldown |
| No entry before | 09:00 | 09:05 |
| No entry after | 15:25 | 15:10 |
| Force exit by | 15:28 | 15:20 |

#### WebSocket Rotation
- Tick slots: 15 (price subscriptions)
- Orderbook slots: 15 (depth subscriptions)
- Notice slots: 1
- Rotation interval: 180 sec (3 min)
- Max subscriptions: 31

#### Screener Config
- Min volume ratio: 2.0× daily avg
- Max spread: 30 bps
- Optimal price: 3,000-50,000 KRW
- Refresh: 3 min (slow changes)
- Min trading value: 100 billion KRW (100억)

---

## 📊 PERFORMANCE ANALYSIS (Feb 20-27, 2026)

### Scalping Deep Dive (275 Trades, 2 Days)

**Data:** Feb 23-26, 559 rows (buy-sell pairs)

#### Profitability Breakdown
- **Pre-fee P&L:** -20,254 KRW (near break-even)
- **Total Fees:** -1,064,466 KRW (KIS + tax)
- **Post-fee P&L:** -1,084,720 KRW
- **Fee Impact:** 98.1% of losses 🚨

#### Exit Type Performance

| Exit Type | Count | Win% | Avg P&L | Total P&L | Notes |
|-----------|-------|------|---------|-----------|-------|
| **SL** | 114 | 0% | -12,842 | -1,463,958 | All losses |
| **TP** | 87 | 100% | +6,138 | +533,995 | All wins |
| TIMEOUT | 24 | 21% | -2,896 | -69,513 | Barely positive |
| **SIGNAL** | 13 | **0%** | -7,076 | -91,993 | 🔴 Bug suspected |
| TRAILING | 13 | 100% | +4,827 | +62,745 | Perfect |
| WALL | 12 | 100% | +3,899 | +46,792 | Perfect |
| RISK | 4 | 0% | -30,278 | -121,113 | Risk limits |

#### Confidence Impact (Critical Discovery)

| Confidence | Count | Win% | Total P&L | PF |
|------------|-------|------|-----------|-----|
| < 0.35 | 219 | 43.4% | -1,043,907 | 0.34 |
| ≥ 0.35 | 56 | 51.8% | -127,113 | 0.55 |
| ≥ 0.40 | 33 | 60.6% | ? | 0.92 |
| ≥ 0.50 | 5 | ? | +16K | N/A |

**Finding:** 87.7% of SL exits (114 total) come from conf<0.35 entries
→ **Confidence filter is single most impactful control**

#### "D-Strategy" Backtest (Incremental Improvements)

| Stage | Trades | Win% | Total P&L | PF | Insight |
|-------|--------|------|-----------|-----|---------|
| **Baseline** | 275 | 45.5% | -1,084,720 | 0.38 | Current |
| +conf≥0.35 | 56 | 51.8% | -127,113 | 0.55 | 88% loss reduction ✅ |
| +12pm cutoff | 49 | 53.1% | **-58,726** | **0.70** | Best found |
| +20-trade daily | 35 | 45.7% | -83,593 | 0.53 | Worse (overconstrained) |

**Conclusion:** Confidence≥0.35 + afternoon block = optimal
(Daily trade limit 20 paradoxically *worsens* performance)

#### Stock-Level Analysis

| Stock | Trades | Win% | P&L | Notes |
|-------|--------|------|-----|-------|
| 포바이포(389140) | 16 | 25% | -145K | Toxic stock |
| 대원전선(006340) | 10 | 0% | -45K | p=0.001 statistically significant loss |
| 현대ADM(187660) | 15 | 60% | +18K | Best performer |
| DB(012030) | 11 | 73% | +48K | TP-heavy exits |

#### Time-of-Day Pattern

| Period | First 5 trades | Rest (270 trades) |
|--------|-----------------|-------------------|
| Win% | 70% | 44.5% |
| Implication | Slower pace → better analysis time early, then fatigue/rush |

#### Hold Duration Effect

| Duration | Win% | Count | Effect |
|----------|------|-------|--------|
| 10-30 min | 19% | High | Worst performance |
| 1-5 min | 45%+ | — | Better |
| <1 min | 80%+ | — | Best |

---

### Swing Trading Summary (50 Trades, Feb 20)

**File:** `logs/trades_main.csv`

**Overview:**
- Period: Feb 20 (1 day)
- Trades: 50 (25 buy-sell pairs approximately)
- Pattern: Mix of TP (3-6%) and SL (-3%) exits
- AI system active: ✅ (Analyst→Executor→Vision pipeline)

**Notable Trades:**
- Row 1-3: Early success (3-5% wins)
- Rows 39-50: Continued SL/TP cycling
- Frequency: High velocity (< 1 min intervals between trades)

**Strategy Evidence:**
- ✅ TP target setting in 1.05-1.30× range (sanity check working)
- ✅ SL anchoring around -3% (ATR×M working)
- ✅ Diversified holdings (multiple stocks per minute)
- ⚠️ High transaction count → High fee erosion

---

## 🔧 CONFIGURATION FILES SNAPSHOT

### Budget Allocation

| System | Budget | Mode | Status |
|--------|--------|------|--------|
| **Swing Trading** | 1,000,000 KRW | Live | Active |
| **Scalping** | 9,000,000 KRW | PAPER | Active |
| **Total** | 10,000,000 KRW | Mixed | Running |

**Whitelist (Manual Holdings):** 005930, 009150, 035720, 263750, 328130

### Fee Impact
- **Buy:** 0.015%
- **Sell:** 0.015% + 0.18% (tax)
- **Round-trip:** ~0.21%

### AI Models
- **Temperature:** Claude Sonnet 4 (claude-sonnet-4-20250514)
- **Swing Analyst:** Claude Sonnet
- **Swing Executor:** Claude Sonnet (temp=0.0)
- **Vision:** Claude Vision (BUY signals)
- **Deep Analysis:** Claude Sonnet 4.6

### Screener AI
- **Top candidates:** 15 (quant score based)
- **Workers:** 5 parallel threads
- **Model:** Claude Sonnet 4

---

## ⚠️ CRITICAL ISSUES & RECOMMENDATIONS

### 1. 🔴 SIGNAL Exit Bug (13건 전패)
**Status:** Unresolved
**Impact:** -91,993 KRW from signal reversals, 0% win rate
**Action:** Review `scalp_strategy.py::_eval_exit()` for SIGNAL logic
**Priority:** HIGH (next market day debug)

### 2. 🟡 Fee Erosion (98% of losses)
**Status:** Known
**Impact:** -1,064,466 KRW on 275 trades = 3,870 KRW/trade avg
**Root Cause:** High trade frequency + fee structure
**Solutions:**
- ✅ Increase confidence threshold (conf≥0.35 tested, -88% loss)
- ✅ Add time filters (12pm block working)
- ✅ Reduce daily trade count (paradoxically worsens: 20-trade limit filters good trades)
- ⏳ Consider order batching/bundling (not implemented)

### 3. 🟡 Threshold Configuration Complexity
**Status:** Partially fixed (2026-02-26)
**Issue:** Threshold split across 3 files (settings, rules, strategies)
**Fix Applied:** max() removed, profiles take direct precedence
**Remaining Risk:** apply_temperature() still overwrites self.confidence_threshold
**Action:** Add unit tests for override hierarchy

### 4. 🟡 Lunch Time Block Effectiveness
**Status:** Active (12:00-15:20 block)
**Rationale:** Afternoon performance degradation observed
**Data:** Should reduce low-confidence afternoon trades
**Monitor:** Track afternoon vs morning P&L post-implementation

### 5. 🟡 Confidence Threshold Inconsistency
**Current:** Strategic profiles 0.35-0.40, Temperature overrides 0.35-0.50
**Issue:** Too many threshold values, hard to maintain
**Recommendation:** Consolidate to: **conf≥0.35 + temperature adjustments only**

### 6. 🔵 Stock-Level Filtering
**Finding:** Some stocks (포바이포 -145K, 대원전선 -45K) consistently lose
**Action:** Consider adding stock-level blacklist after 2+ consecutive losses
**Caution:** Only 2-day data, need 20+ days for statistical significance

### 7. 🔵 Position Hold Duration
**Finding:** 10-30 min holds have 19% win rate (worst)
**Theory:** Stale signals, market turned against us
**Action:** Monitor max_hold_seconds effectiveness (currently 180s = 3min)

---

## 📅 NEXT STEPS FOR TOMORROW (2026-03-03)

### Pre-Market (08:30-09:00)
- [ ] Verify market temperature calculation (Macro, Sentiment, Econ modules)
- [ ] Check Discord webhook connectivity
- [ ] Validate KIS API authentication (token cache)
- [ ] Confirm PID locks cleared from last session
- [ ] Review overnight news impact on temperature

### Market Open (09:00-09:30)
- [ ] Monitor ORB strategy (09:00-09:30 window)
- [ ] Track initial confidence levels (should be >0.35 filtered)
- [ ] Validate MA120 filter is working (Stage 2 only)
- [ ] Check WebSocket rotations for scalper (every 3 min)

### Mid-Session (09:30-12:00)
- [ ] Monitor Momentum + VWAP strategies
- [ ] Track confidence progression throughout session
- [ ] Watch for circuit breaker activations (3 consecutive SL)
- [ ] Verify no re-buys violating rules
- [ ] Check daily loss accumulation

### Afternoon (12:00-15:20)
- [ ] Verify lunch block is active (12:00-15:20 no entry)
- [ ] Monitor EOD force-exit preparation (15:28 PAPER, 15:20 REAL)
- [ ] Check position consolidation

### Post-Market (15:20+)
- [ ] Generate trade report (CSV analysis)
- [ ] Review SIGNAL exit errors (if any)
- [ ] Analyze confidence distribution vs outcomes
- [ ] Update memory with day's performance

---

## 📈 KEY METRICS TO TRACK TODAY

### Swing Trading
- Win% (target: >50%)
- Avg TP% (target: >2%)
- Avg SL% (target: >-3%)
- Fee per trade
- Total P&L

### Scalping
- Entry confidence distribution (>0.35: ✅, <0.35: ❌)
- Exit type distribution (TP/TRAILING > SL/SIGNAL)
- Hourly P&L (expect morning > afternoon)
- Circuit breaker activations
- Stock diversity (avoid toxic ones)

### Temperature
- Level (HOT/WARM/NEUTRAL/COOL/COLD)
- Component scores (Macro, Sentiment, Econ)
- Parameter adjustments (k, TP, SL, positions)

---

## 📚 FILE REFERENCE

| File | Purpose | Last Update |
|------|---------|------------|
| `run_ai_swing_bot.py` | Swing bot entry (359 lines) | Active |
| `run_scalper.py` | Scalper entry (336 lines) | Active |
| `run_firefeet.py` | Main bot entry (233 lines) | Active |
| `config/temperature_config.yaml` | Temp profiles + modules | ✅ |
| `config/trading_settings.yaml` | Budget, whitelist | ✅ |
| `config/trading_rules.yaml` | Risk rules, overrides | ✅ |
| `config/screener_settings.yaml` | 7-factor weights | ✅ |
| `config/scalping_settings.yaml` | Scalp budget, signals | ✅ |
| `config/scalping_rules.yaml` | REAL/PAPER risk | ✅ |
| `config/scalping_strategies.yaml` | Strat profiles, time windows | ⚠️ (lunch block added) |
| `config/deep_analysis.yaml` | AI analyst settings | ✅ |
| `config/agent_settings.yaml` | Model weights | ✅ |
| `docs/swing_trading.md` | Strategy deep-dive | ✅ |
| `docs/SCALPING.md` | Scalping architecture | ✅ |
| `logs/trades_scalp.csv` | Latest scalp trades | 2026-02-27 |
| `logs/trades_main.csv` | Latest swing trades | 2026-02-20 |
| `.claude/projects/.../memory/scalping-analysis.md` | 275-trade analysis | 2026-02-26 |
| `.claude/projects/.../memory/scalping-threshold.md` | Threshold hierarchy fix | 2026-02-26 |

---

## 🎓 KEY LEARNINGS

1. **Fee Impact >> Strategy Skill**
   98% of losses are fees, not bad trades. Reducing frequency > improving accuracy for scalping.

2. **Confidence is King**
   conf≥0.35 filter reduces losses by 88%. Should be primary gate, not temperature.

3. **Afternoon ≠ Morning**
   10-30 min holds (typical afternoon pattern) have 19% win rate. 12:00-15:20 block justified.

4. **Avoid Toxic Stocks**
   포바이포, 대원전선 statistically lose. Blacklist after pattern confirmation.

5. **Less is More**
   20-trade daily limit *worsens* performance (filters good trades). Let strategy breathe.

6. **Signal Logic Broken**
   SIGNAL exit 0% win rate = bot bug, not market issue. Debug immediately.

7. **Hold Duration Matters**
   1-5 min holds > 10-30 min holds. Scalping edge is speed, not duration patience.

---

**Generated:** 2026-03-02 (Pre-Market)
**Next Review:** 2026-03-03 (After Market Close)
**Data Source:** 6 trading days (Feb 20-27, 2026), 275 scalping trades, 50 swing trades
**Confidence:** Medium (only 2-day scalping sample, 1-day swing sample)
