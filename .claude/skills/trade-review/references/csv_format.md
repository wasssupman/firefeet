# Trade Log CSV Format

## 파일 위치
- 스윙: `logs/trades_swing.csv`
- 스캘핑: `logs/trades_scalp.csv`
- 데이트레이딩: `logs/trades_main.csv`

## 컬럼 (30개)
```
timestamp, date, code, name, action, signal,
qty, price, amount, fee, net_amount,
buy_price, realized_pnl, pnl_rate,
strategy, composite, threshold, temperature,
sig_vwap, sig_ob, sig_mom, sig_vol, sig_trend,
spread_bps, penalty, tp_pct, sl_pct, vwap_dist,
hold_seconds, peak_profit_pct
```

## 수수료 구조
- 매수: 0.015% (BUY_FEE_RATE = 0.00015)
- 매도: 0.015% + 거래세 0.18% (합산 0.195%)
- 왕복: ~0.21%
- 소스: `core/trade_logger.py` TradeLogger 클래스

## 청산 시그널 (signal 컬럼)
| 값 | 의미 |
|----|------|
| TP | Take Profit 도달 |
| SL | Stop Loss 도달 |
| TRAILING | 트레일링 스탑 발동 |
| SIGNAL | 시그널 반전 청산 (현재 비활성화) |
| EOD | 장 마감 청산 |
| TIMEOUT | 최대 보유 시간 초과 |
