import yfinance as yf
import pandas as pd
import numpy as np


class TechnicalAnalyzer:
    def __init__(self):
        pass

    def analyze(self, code: str, period: str = "1y") -> dict:
        """전체 기술적 분석 실행"""
        try:
            hist = self._get_history(code, period)
            if hist.empty:
                return {}

            current_price = float(hist["Close"].iloc[-1])

            moving_averages = self.get_moving_averages(code)
            rsi = self.get_rsi(code)
            macd = self.get_macd(code)
            bollinger = self.get_bollinger_bands(code)
            volume = self.get_volume_analysis(code)
            support_resistance = self.get_support_resistance(code)

            trend_summary = self._generate_trend_summary(
                current_price, moving_averages, rsi, macd, bollinger, volume
            )

            return {
                "current_price": current_price,
                "moving_averages": moving_averages,
                "rsi": rsi,
                "macd": macd,
                "bollinger": bollinger,
                "volume": volume,
                "support_resistance": support_resistance,
                "trend_summary": trend_summary,
            }
        except Exception as e:
            print(f"[TechnicalAnalyzer] Error: {e}")
            return {}

    def get_moving_averages(self, code: str) -> dict:
        """이동평균선 분석"""
        try:
            hist = self._get_history(code, "1y")
            if hist.empty or len(hist) < 5:
                return {}

            close = hist["Close"]
            current_price = float(close.iloc[-1])

            def safe_ma(series, window):
                if len(series) >= window:
                    return float(series.rolling(window).mean().iloc[-1])
                return None

            ma5 = safe_ma(close, 5)
            ma20 = safe_ma(close, 20)
            ma50 = safe_ma(close, 50)
            ma200 = safe_ma(close, 200)

            price_vs_ma50 = ((current_price - ma50) / ma50 * 100) if ma50 else None
            price_vs_ma200 = ((current_price - ma200) / ma200 * 100) if ma200 else None
            golden_cross = (ma50 > ma200) if (ma50 and ma200) else None

            # 정배열: 단기 MA가 순서대로 정렬 (ma5 > ma20 > ma50)
            if ma5 and ma20 and ma50:
                if ma5 > ma20 > ma50:
                    alignment = "정배열"
                elif ma5 < ma20 < ma50:
                    alignment = "역배열"
                else:
                    alignment = "혼조"
            else:
                alignment = "혼조"

            return {
                "ma5": ma5,
                "ma20": ma20,
                "ma50": ma50,
                "ma200": ma200,
                "price_vs_ma50": price_vs_ma50,
                "price_vs_ma200": price_vs_ma200,
                "golden_cross": golden_cross,
                "alignment": alignment,
            }
        except Exception as e:
            print(f"[TechnicalAnalyzer] Error: {e}")
            return {}

    def get_rsi(self, code: str, window: int = 14) -> float:
        """RSI (Relative Strength Index) 계산 — Wilder's smoothing"""
        try:
            hist = self._get_history(code, "6mo")
            if hist.empty or len(hist) < window + 1:
                return None

            close = hist["Close"]
            delta = close.diff()

            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)

            # Wilder's smoothing: ewm with com = window - 1
            avg_gain = gain.ewm(com=window - 1, min_periods=window).mean()
            avg_loss = loss.ewm(com=window - 1, min_periods=window).mean()

            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

            return float(rsi.iloc[-1])
        except Exception as e:
            print(f"[TechnicalAnalyzer] Error: {e}")
            return None

    def get_macd(self, code: str) -> dict:
        """MACD 분석 (12/26/9 파라미터)"""
        try:
            hist = self._get_history(code, "1y")
            if hist.empty or len(hist) < 35:
                return {}

            close = hist["Close"]

            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            histogram = macd_line - signal_line

            macd_val = float(macd_line.iloc[-1])
            signal_val = float(signal_line.iloc[-1])
            hist_val = float(histogram.iloc[-1])

            # 골든/데드 크로스 판단 (직전 대비 현재 교차 여부)
            if len(macd_line) >= 2:
                prev_macd = float(macd_line.iloc[-2])
                prev_signal = float(signal_line.iloc[-2])
                if prev_macd <= prev_signal and macd_val > signal_val:
                    cross = "golden"
                elif prev_macd >= prev_signal and macd_val < signal_val:
                    cross = "dead"
                else:
                    cross = "none"
            else:
                cross = "none"

            return {
                "macd": macd_val,
                "signal": signal_val,
                "histogram": hist_val,
                "cross": cross,
            }
        except Exception as e:
            print(f"[TechnicalAnalyzer] Error: {e}")
            return {}

    def get_bollinger_bands(self, code: str, window: int = 20) -> dict:
        """볼린저 밴드 (20일 SMA, ±2 표준편차)"""
        try:
            hist = self._get_history(code, "6mo")
            if hist.empty or len(hist) < window:
                return {}

            close = hist["Close"]
            middle = close.rolling(window).mean()
            std = close.rolling(window).std()

            upper = middle + 2 * std
            lower = middle - 2 * std

            upper_val = float(upper.iloc[-1])
            middle_val = float(middle.iloc[-1])
            lower_val = float(lower.iloc[-1])
            current_price = float(close.iloc[-1])

            band_range = upper_val - lower_val
            if band_range > 0:
                position = (current_price - lower_val) / band_range
                width = band_range / middle_val * 100
            else:
                position = 0.5
                width = 0.0

            return {
                "upper": upper_val,
                "middle": middle_val,
                "lower": lower_val,
                "position": float(position),
                "width": float(width),
            }
        except Exception as e:
            print(f"[TechnicalAnalyzer] Error: {e}")
            return {}

    def get_volume_analysis(self, code: str) -> dict:
        """거래량 분석"""
        try:
            hist = self._get_history(code, "3mo")
            if hist.empty or len(hist) < 2:
                return {}

            volume = hist["Volume"]
            current_volume = int(volume.iloc[-1])

            avg_20d = float(volume.iloc[-20:].mean()) if len(volume) >= 20 else float(volume.mean())
            volume_ratio = current_volume / avg_20d if avg_20d > 0 else 1.0

            # 최근 5일 추세로 거래량 흐름 판단
            if len(volume) >= 5:
                recent = volume.iloc[-5:]
                slope = np.polyfit(range(len(recent)), recent.values, 1)[0]
                if slope > avg_20d * 0.02:
                    trend = "증가"
                elif slope < -avg_20d * 0.02:
                    trend = "감소"
                else:
                    trend = "보통"
            else:
                trend = "보통"

            return {
                "current_volume": current_volume,
                "avg_20d": avg_20d,
                "volume_ratio": float(volume_ratio),
                "trend": trend,
            }
        except Exception as e:
            print(f"[TechnicalAnalyzer] Error: {e}")
            return {}

    def get_support_resistance(self, code: str) -> dict:
        """지지/저항선 계산 (최근 3개월 피벗 포인트 기반)"""
        try:
            hist = self._get_history(code, "1y")
            if hist.empty or len(hist) < 20:
                return {}

            close = hist["Close"]
            high = hist["High"]
            low = hist["Low"]

            high_52w = float(high.max())
            low_52w = float(low.min())

            # 최근 3개월 데이터로 지지/저항 계산
            recent = hist.iloc[-63:]  # 약 3개월 (63 거래일)
            recent_close = recent["Close"]
            recent_high = recent["High"]
            recent_low = recent["Low"]

            # 로컬 고점 (저항): window=5 기준 지역 최대값
            local_highs = []
            local_lows = []
            w = 5
            for i in range(w, len(recent_high) - w):
                if recent_high.iloc[i] == recent_high.iloc[i - w:i + w + 1].max():
                    local_highs.append(float(recent_high.iloc[i]))
                if recent_low.iloc[i] == recent_low.iloc[i - w:i + w + 1].min():
                    local_lows.append(float(recent_low.iloc[i]))

            current_price = float(close.iloc[-1])

            # 현재가 기준 아래 지지선, 위 저항선 정렬
            supports = sorted([v for v in local_lows if v < current_price], reverse=True)
            resistances = sorted([v for v in local_highs if v > current_price])

            support_1 = supports[0] if len(supports) > 0 else float(recent_low.min())
            support_2 = supports[1] if len(supports) > 1 else float(recent_low.min())
            resistance_1 = resistances[0] if len(resistances) > 0 else float(recent_high.max())
            resistance_2 = resistances[1] if len(resistances) > 1 else float(recent_high.max())

            return {
                "support_1": support_1,
                "support_2": support_2,
                "resistance_1": resistance_1,
                "resistance_2": resistance_2,
                "52w_high": high_52w,
                "52w_low": low_52w,
            }
        except Exception as e:
            print(f"[TechnicalAnalyzer] Error: {e}")
            return {}

    def _get_ticker(self, code: str) -> str:
        """종목코드 → yfinance 티커 변환 (.KS 우선, 없으면 .KQ)"""
        try:
            ks_ticker = f"{code}.KS"
            test = yf.download(ks_ticker, period="5d", auto_adjust=True, progress=False)
            if not test.empty:
                return ks_ticker
        except Exception:
            pass

        return f"{code}.KQ"

    def _get_history(self, code: str, period: str = "1y") -> pd.DataFrame:
        """주가 히스토리 조회"""
        try:
            ticker = self._get_ticker(code)
            hist = yf.download(ticker, period=period, auto_adjust=True, progress=False)
            # yfinance가 멀티인덱스 컬럼을 반환하는 경우 단순화
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            return hist
        except Exception as e:
            print(f"[TechnicalAnalyzer] Error: {e}")
            return pd.DataFrame()

    def _generate_trend_summary(
        self,
        current_price: float,
        moving_averages: dict,
        rsi: float,
        macd: dict,
        bollinger: dict,
        volume: dict,
    ) -> str:
        """기술적 지표 종합 추세 요약 문자열 생성"""
        signals = []

        # 이동평균 정배열/역배열
        if moving_averages:
            alignment = moving_averages.get("alignment", "혼조")
            signals.append(f"MA {alignment}")
            if moving_averages.get("golden_cross") is True:
                signals.append("골든크로스")
            elif moving_averages.get("golden_cross") is False:
                signals.append("데드크로스")

        # RSI
        if rsi is not None:
            if rsi >= 70:
                signals.append(f"RSI 과매수({rsi:.1f})")
            elif rsi <= 30:
                signals.append(f"RSI 과매도({rsi:.1f})")
            else:
                signals.append(f"RSI 중립({rsi:.1f})")

        # MACD
        if macd:
            cross = macd.get("cross", "none")
            if cross == "golden":
                signals.append("MACD 골든크로스")
            elif cross == "dead":
                signals.append("MACD 데드크로스")

        # 볼린저 밴드 위치
        if bollinger:
            pos = bollinger.get("position")
            if pos is not None:
                if pos >= 0.8:
                    signals.append("볼린저 상단 근접")
                elif pos <= 0.2:
                    signals.append("볼린저 하단 근접")

        # 거래량 추세
        if volume:
            trend = volume.get("trend", "보통")
            ratio = volume.get("volume_ratio", 1.0)
            if trend == "증가" or ratio >= 1.5:
                signals.append(f"거래량 증가({ratio:.1f}x)")

        if not signals:
            return "분석 데이터 부족"

        return " | ".join(signals)
