# Config Schema Reference

## 검증 대상 파일과 필수 키

### config/scalping_settings.yaml
- `scalping_budget`: int > 0
- `default_confidence_threshold`: float 0.0~1.0
- `take_profit_pct`: float > 0.21 (수수료 바닥선)
- `stop_loss_pct`: float < 0
- `max_hold_seconds`: int > 0
- `max_simultaneous_positions`: int 1~5
- `max_position_value`: int > 0
- `eod_exit_time`: str "HHMM"

### config/scalping_strategies.yaml
- `lunch_block_start`: str "HHMM"
- `lunch_block_end`: str "HHMM", > lunch_block_start
- `strategies`: list of:
  - `name`: str
  - `confidence_threshold`: float 0.0~1.0
  - `take_profit`: float > 0.21
  - `stop_loss`: float < 0
  - `signal_weights`: dict (vwap_reversion, orderbook_pressure, momentum_burst, volume_surge, micro_trend)

### config/scalping_rules.yaml
- `mode.real.per_trade.max_loss_pct`: float, should align with stop_loss
- `mode.real.daily_limits.max_daily_loss`: int > 0
- `mode.real.daily_limits.max_consecutive_losses`: int 3~10
- `mode.paper.per_trade.max_loss_pct`: should be >= real mode (paper is more lenient)

### config/temperature_config.yaml
- `strategy_profiles`: must have all 5 levels (HOT, WARM, NEUTRAL, COOL, COLD)
- Each profile: k, take_profit, stop_loss, max_position_pct, atr_sl_multiplier, atr_tp_multiplier
- k: monotonically increasing HOT→COLD
- take_profit: monotonically decreasing HOT→COLD
- `level_thresholds`: HOT > WARM > NEUTRAL > COOL

### config/trading_settings.yaml
- `total_budget`: int > 0
- `max_concurrent_targets`: int > 0

### config/secrets.yaml
- 존재 여부만 확인, 값은 읽지 않음
- 필수 키: PROD.APP_KEY, PROD.APP_SECRET, PAPER.APP_KEY, PAPER.APP_SECRET, CANO
