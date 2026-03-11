import pandas as pd

class VolatilityBreakoutStrategy:
    def __init__(self, k=0.5):
        self.k = k # Volatility constant (usually 0.5)
        self.take_profit = 4.0        # floor TP (NEUTRAL 기준, RR 2:1)
        self.stop_loss = -2.0         # floor SL (NEUTRAL 기준)
        self.max_position_pct = 0.25
        self.min_screen_score = 30
        self.temperature_level = "NEUTRAL"
        self.atr_sl_multiplier = 1.0  # SL = ATR × 1.0 고정 (RR 비대칭 원칙)
        self.atr_tp_multiplier = 2.0  # TP = ATR × 2.0 (NEUTRAL, RR 2:1)

    @staticmethod
    def calculate_atr(df, period=14):
        """
        ATR(Average True Range) 계산.
        df: OHLC DataFrame, 날짜 내림차순 (index 0 = 최신).
        Returns: period 일간의 True Range 평균. 데이터 부족 시 None.
        """
        if df is None or (hasattr(df, 'empty') and df.empty) or len(df) < period + 1:
            return None

        true_ranges = []
        for i in range(period):
            high = float(df.iloc[i]['high'])
            low = float(df.iloc[i]['low'])
            prev_close = float(df.iloc[i + 1]['close'])
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)

        return sum(true_ranges) / len(true_ranges)

    def get_contraction_ratio(self, df):
        """
        수축 비율: ATR(5) / ATR(20).
        < 0.8 = 수축 중 (돌파 시 가치 있는 신호)
        0.8~1.2 = 보통
        > 1.2 = 이미 확장 중 (과열, 매수 위험)
        """
        atr5 = self.calculate_atr(df, period=5)
        atr20 = self.calculate_atr(df, period=20)
        if atr5 is None or atr20 is None or atr20 <= 0:
            return None
        return atr5 / atr20

    def get_target_price(self, code, df):
        """
        Calculates the target buy price for today based on yesterday's range.
        Target = Today's Open + (Yesterday's High - Yesterday's Low) * K
        """
        if df is None or (hasattr(df, 'empty') and df.empty) or len(df) < 2:
            return None
        
        # DataFrame is usually sorted by date desc (0 is today/latest, 1 is yesterday)
        today = df.iloc[0]
        yesterday = df.iloc[1]
        
        # Calculate Range (Volatility)
        volatility_range = (yesterday['high'] - yesterday['low']) * self.k
        
        # Target Price
        target_price = today['open'] + volatility_range
        
        return {
            "code": code,
            "today_open": today['open'],
            "yesterday_high": yesterday['high'],
            "yesterday_low": yesterday['low'],
            "volatility_range": volatility_range,
            "target_price": target_price
        }

    def check_buy_signal(self, code, df, current_price):
        """
        Checks if the current price has broken out the target price.
        Returns contraction & ATR context for downstream filtering.
        """
        # 1. Get Target Price
        target_info = self.get_target_price(code, df)
        if not target_info:
            return None

        # 3. Check Signal
        target_price = target_info['target_price']

        signal = None
        if current_price >= target_price:
            signal = "BUY"

        # Contraction & ATR context
        contraction_ratio = self.get_contraction_ratio(df)
        atr14 = self.calculate_atr(df, period=14)

        return {
            "signal": signal,
            "current_price": current_price,
            "target_price": target_price,
            "volatility_k": self.k,
            "profit_potential": (current_price - target_price) / target_price * 100 if signal else 0,
            "contraction_ratio": contraction_ratio,
            "atr14": atr14,
        }

    def apply_temperature(self, temp_result, profiles):
        """
        온도 결과 + strategy_profiles를 받아 파라미터 조절.
        profiles: temperature_config.yaml의 strategy_profiles 섹션.
        """
        level = temp_result["level"]
        self.temperature_level = level
        profile = profiles.get(level, profiles.get("NEUTRAL", {}))

        old_k = self.k
        old_tp = self.take_profit
        old_sl = self.stop_loss

        self.k = profile.get("k", self.k)
        self.take_profit = profile.get("take_profit", self.take_profit)
        self.stop_loss = profile.get("stop_loss", self.stop_loss)
        self.max_position_pct = profile.get("max_position_pct", self.max_position_pct)
        self.min_screen_score = profile.get("min_screen_score", self.min_screen_score)
        self.atr_sl_multiplier = profile.get("atr_sl_multiplier", self.atr_sl_multiplier)
        self.atr_tp_multiplier = profile.get("atr_tp_multiplier", self.atr_tp_multiplier)

        print(f"[Strategy] 온도 적용 ({level}): "
              f"k={old_k}→{self.k}, TP={old_tp:+.1f}%→{self.take_profit:+.1f}%, "
              f"SL={old_sl:.1f}%→{self.stop_loss:.1f}%")

    def should_sell(self, current_price, buy_price, current_time_str, atr=None):
        """
        Determines if we should sell based on:
        1. Take Profit (ATR-based with fixed % as floor)
        2. Stop Loss (ATR-based with fixed % as floor)
        3. End of Day: After 15:20 (Market Closes at 15:30)

        atr: ATR(14) value. If provided, enables structural SL/TP.
             Fixed % serves as floor (최소 보호), ATR overrides if wider.
        """
        if buy_price <= 0:
            return None

        profit_rate = (current_price - buy_price) / buy_price * 100

        # Determine effective TP/SL (ATR-based with fixed % as floor)
        effective_tp = self.take_profit
        effective_sl = self.stop_loss

        if atr and atr > 0 and buy_price > 0:
            atr_tp_pct = (atr * self.atr_tp_multiplier) / buy_price * 100
            atr_sl_pct = -(atr * self.atr_sl_multiplier) / buy_price * 100
            # Fixed % = floor. ATR이 더 넓으면 ATR 사용.
            effective_tp = max(self.take_profit, atr_tp_pct)
            effective_sl = min(self.stop_loss, atr_sl_pct)

        if profit_rate >= effective_tp:
            return "SELL_TAKE_PROFIT"

        if profit_rate <= effective_sl:
            return "SELL_STOP_LOSS"

        # End of Day — 15:20 이후 무조건 청산 (상한 제거: 15:30 이후에도 매도 시도)
        time_int = int(current_time_str.replace(":", "")[:4])
        if time_int >= 1520:
            return "SELL_EOD"

        return None
