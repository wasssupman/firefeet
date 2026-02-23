import pandas as pd

class VolatilityBreakoutStrategy:
    def __init__(self, k=0.5):
        self.k = k # Volatility constant (usually 0.5)
        self.take_profit = 3.0
        self.stop_loss = -3.0
        self.max_position_pct = 0.25
        self.min_screen_score = 30
        self.temperature_level = "NEUTRAL"

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
            
        return {
            "signal": signal,
            "current_price": current_price,
            "target_price": target_price,
            "volatility_k": self.k,
            "profit_potential": (current_price - target_price) / target_price * 100 if signal else 0
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

        print(f"[Strategy] 온도 적용 ({level}): "
              f"k={old_k}→{self.k}, TP={old_tp:+.1f}%→{self.take_profit:+.1f}%, "
              f"SL={old_sl:.1f}%→{self.stop_loss:.1f}%")

    def should_sell(self, current_price, buy_price, current_time_str):
        """
        Determines if we should sell based on:
        1. Take Profit (dynamic)
        2. Stop Loss (dynamic)
        3. End of Day: After 15:20 (Market Closes at 15:30)
        """
        if buy_price <= 0:
            return None

        profit_rate = (current_price - buy_price) / buy_price * 100

        if profit_rate >= self.take_profit:
            return "SELL_TAKE_PROFIT"

        if profit_rate <= self.stop_loss:
            return "SELL_STOP_LOSS"

        # End of Day — 15:20 이후 무조건 청산 (상한 제거: 15:30 이후에도 매도 시도)
        time_int = int(current_time_str.replace(":", "")[:4])
        if time_int >= 1520:
            return "SELL_EOD"

        return None
