import yfinance as yf
import yaml
import os
from datetime import datetime, timezone, timedelta


KST = timezone(timedelta(hours=9))


class MacroAnalyzer:
    """
    글로벌 거시 지표 분석 시스템.
    Phase 1: 미 3대 지수 + 환율 + VIX
    Phase 2+: config/macro_config.yaml 설정에 따라 확장
    """

    # Phase 1 심볼
    US_INDICES = {
        "나스닥": "^IXIC",
        "S&P 500": "^GSPC",
        "다우존스": "^DJI",
    }
    FX = {"원/달러": "USDKRW=X"}
    RISK = {"VIX": "^VIX"}

    # Phase 2 심볼
    BONDS = {
        "미 10년물": "^TNX",
    }
    COMMODITIES = {
        "WTI 원유": "CL=F",
        "금": "GC=F",
        "구리": "HG=F",
    }

    # Phase 3 심볼
    CRYPTO = {
        "비트코인": "BTC-USD",
        "이더리움": "ETH-USD",
    }
    GLOBAL_INDICES = {
        "필라델피아 반도체": "^SOX",
        "닛케이 225": "^N225",
        "항셍": "^HSI",
    }

    def __init__(self, config_path="config/macro_config.yaml"):
        self.config = self._load_config(config_path)

    def _load_config(self, path):
        if os.path.exists(path):
            with open(path, 'r') as f:
                return yaml.safe_load(f)
        return {"phase1": {"us_indices": True, "fx_rate": True, "vix": True}}

    @staticmethod
    def is_us_market_open():
        """
        미국장이 열려 있는지 확인 (KST 기준)
        미장: 23:30 ~ 06:00 KST (서머타임: 22:30 ~ 05:00)
        """
        now_kst = datetime.now(KST)
        hour = now_kst.hour
        return hour >= 22 or hour < 7

    def _fetch_change(self, symbol):
        """yfinance로 전일 대비 등락률 조회 (일봉 기준)"""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")
            if hist.empty or len(hist) < 2:
                return None
            last_close = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2]
            change_pct = (last_close - prev_close) / prev_close * 100
            return {
                "price": round(float(last_close), 2),
                "change_pct": round(float(change_pct), 2),
                "is_live": False,
            }
        except Exception as e:
            print(f"[MacroAnalyzer] {symbol} 조회 실패: {e}")
            return None

    def _fetch_realtime(self, symbol):
        """
        실시간 가격 조회 (fast_info 사용)
        - fast_info: 시간외/프리마켓 포함 진짜 실시간 스냅샷
        - 1분봉은 정규장(9:30~16:00)만 커버하므로 부정확
        """
        try:
            ticker = yf.Ticker(symbol)
            fi = ticker.fast_info

            last_price = float(fi.get('lastPrice', fi.get('last_price', 0)))
            prev_close = float(fi.get('previousClose', fi.get('previous_close', 0)))

            if last_price == 0 or prev_close == 0:
                return None

            change_pct = (last_price - prev_close) / prev_close * 100
            now_kst = datetime.now(KST).strftime("%H:%M")

            return {
                "price": round(last_price, 2),
                "prev_close": round(prev_close, 2),
                "change_pct": round(float(change_pct), 2),
                "time": now_kst,
                "is_live": True,
            }
        except Exception as e:
            print(f"[MacroAnalyzer] {symbol} 실시간 조회 실패: {e}")
            return None

    def _fetch_group(self, symbol_map):
        """심볼 그룹의 데이터를 일괄 조회"""
        results = {}
        for name, symbol in symbol_map.items():
            data = self._fetch_change(symbol)
            if data:
                results[name] = data
        return results

    def _fetch_group_realtime(self, symbol_map):
        """심볼 그룹의 실시간 데이터를 일괄 조회"""
        results = {}
        for name, symbol in symbol_map.items():
            data = self._fetch_realtime(symbol)
            if data:
                results[name] = data
            else:
                # 실시간 실패 시 일봉 fallback
                data = self._fetch_change(symbol)
                if data:
                    results[name] = data
        return results

    # === Public API ===

    def get_us_indices(self):
        return self._fetch_group(self.US_INDICES)

    def get_us_indices_realtime(self):
        return self._fetch_group_realtime(self.US_INDICES)

    def get_fx_rates(self):
        return self._fetch_group(self.FX)

    def get_fx_rates_realtime(self):
        return self._fetch_group_realtime(self.FX)

    def get_vix(self):
        return self._fetch_group(self.RISK)

    def get_vix_realtime(self):
        return self._fetch_group_realtime(self.RISK)

    def get_bond_yields(self):
        return self._fetch_group(self.BONDS)

    def get_commodities(self):
        return self._fetch_group(self.COMMODITIES)

    def get_crypto(self):
        return self._fetch_group(self.CRYPTO)

    def get_global_indices(self):
        return self._fetch_group(self.GLOBAL_INDICES)

    def compute_market_score(self, us=None, fx=None, vix=None):
        """Phase 1 지표 기반 종합 시장 점수 (-100 ~ +100)"""
        us = us or self.get_us_indices()
        fx = fx or self.get_fx_rates()
        vix = vix or self.get_vix()

        score = 0.0

        if us:
            us_avg = sum(v['change_pct'] for v in us.values()) / len(us)
            score += us_avg * 10 * 0.4

        if fx and "원/달러" in fx:
            score -= fx["원/달러"]['change_pct'] * 10 * 0.3

        if vix and "VIX" in vix:
            score -= vix["VIX"]['change_pct'] * 3 * 0.3

        return max(-100, min(100, round(score, 1)))

    def generate_comment(self, score):
        """점수 기반 시장 코멘트 생성"""
        if score >= 60:
            return "🟢 **적극 매수** — 미장 강세, 환율 안정"
        elif score >= 20:
            return "🔵 **매수 우위** — 긍정적 분위기"
        elif score >= -20:
            return "⚪ **관망/중립** — 혼조세"
        elif score >= -60:
            return "🟡 **보수적** — 방어적 접근 권장"
        else:
            return "🔴 **위험** — 미장 급락, 매수 자제"

    def _format_indicator(self, name, data, emoji_fn):
        """지표를 포맷팅 (실시간이면 시간 표시)"""
        emoji = emoji_fn(data)
        base = f"- {emoji} **{name}**: {data['price']:,.2f} ({data['change_pct']:+.2f}%)"
        if data.get('is_live') and data.get('time'):
            base += f" ⏱️{data['time']}"
        return base

    def generate_report_section(self):
        """리포트에 삽입할 매크로 분석 섹션 생성"""
        cfg = self.config
        live = self.is_us_market_open()

        if live:
            lines = ["## 🌍 글로벌 시장 브리핑 (🔴 LIVE)\n"]
        else:
            lines = ["## 🌍 글로벌 시장 브리핑 (전일 종가)\n"]

        us_data = {}
        fx_data = {}
        vix_data = {}

        # Phase 1: US Indices
        if cfg.get('phase1', {}).get('us_indices'):
            us_data = self.get_us_indices_realtime() if live else self.get_us_indices()
            for name, data in us_data.items():
                lines.append(self._format_indicator(
                    name, data, lambda d: "📈" if d['change_pct'] >= 0 else "📉"))

        # Phase 1: FX
        if cfg.get('phase1', {}).get('fx_rate'):
            fx_data = self.get_fx_rates_realtime() if live else self.get_fx_rates()
            for name, data in fx_data.items():
                lines.append(self._format_indicator(
                    name, data, lambda d: "💵" if abs(d['change_pct']) < 0.5 else "⚠️"))

        # Phase 1: VIX
        if cfg.get('phase1', {}).get('vix'):
            vix_data = self.get_vix_realtime() if live else self.get_vix()
            for name, data in vix_data.items():
                emoji_fn = lambda d: "😰" if d['price'] > 25 else "😌"
                base = f"- {emoji_fn(data)} **{name}**: {data['price']:.2f} ({data['change_pct']:+.2f}%)"
                if data.get('is_live') and data.get('time'):
                    base += f" ⏱️{data['time']}"
                lines.append(base)

        # Phase 2
        if cfg.get('phase2', {}).get('bond_yields'):
            for name, data in self.get_bond_yields().items():
                lines.append(f"- 🏦 **{name}**: {data['price']:.3f}% ({data['change_pct']:+.2f}%)")

        if cfg.get('phase2', {}).get('commodities'):
            for name, data in self.get_commodities().items():
                lines.append(f"- 🛢️ **{name}**: ${data['price']:,.2f} ({data['change_pct']:+.2f}%)")

        # Phase 3
        if cfg.get('phase3', {}).get('crypto'):
            for name, data in self.get_crypto().items():
                lines.append(f"- ₿ **{name}**: ${data['price']:,.2f} ({data['change_pct']:+.2f}%)")

        if cfg.get('phase3', {}).get('global_indices'):
            for name, data in self.get_global_indices().items():
                emoji = "📈" if data['change_pct'] >= 0 else "📉"
                lines.append(f"- {emoji} **{name}**: {data['price']:,.2f} ({data['change_pct']:+.2f}%)")

        # 종합 점수
        score = self.compute_market_score(us_data, fx_data, vix_data)
        comment = self.generate_comment(score)
        lines.append(f"\n> **종합 점수: {score:+.1f}** → {comment}")

        return "\n".join(lines)

    # === Trend Analysis (for Market Temperature) ===

    def get_trend_data(self, symbol, days=3):
        """
        최근 N일간 일별 등락률 + 추세 방향.
        Returns: {
            "prices": [72100.0, 72500.0, 73200.0],
            "daily_changes": [+0.8, +0.55, +0.96],
            "avg_change": +0.77,
            "trend": "UP" | "DOWN" | "FLAT",
            "streak": 3,
            "current_price": 73200.0,
        }
        """
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=f"{days * 3}d")
            if hist.empty or len(hist) < days + 1:
                return None

            # 최근 days+1일 추출 (변화율 계산에 +1 필요)
            recent = hist.tail(days + 1)
            closes = recent['Close'].tolist()

            daily_changes = []
            for i in range(1, len(closes)):
                if closes[i - 1] != 0:
                    change = (closes[i] - closes[i - 1]) / closes[i - 1] * 100
                    daily_changes.append(round(change, 2))

            prices = [round(p, 2) for p in closes[1:]]  # days일분

            avg_change = sum(daily_changes) / len(daily_changes) if daily_changes else 0

            # 추세 판단
            if all(c > 0 for c in daily_changes):
                trend = "UP"
            elif all(c < 0 for c in daily_changes):
                trend = "DOWN"
            elif avg_change > 0.3:
                trend = "UP"
            elif avg_change < -0.3:
                trend = "DOWN"
            else:
                trend = "FLAT"

            # 연속 상승/하락 일수 (최근부터 역순)
            streak = 0
            if daily_changes:
                direction = 1 if daily_changes[-1] > 0 else -1
                for c in reversed(daily_changes):
                    if (c > 0 and direction > 0) or (c < 0 and direction < 0):
                        streak += 1
                    else:
                        break

            return {
                "prices": prices,
                "daily_changes": daily_changes,
                "avg_change": round(avg_change, 2),
                "trend": trend,
                "streak": streak,
                "current_price": prices[-1] if prices else 0,
            }
        except Exception as e:
            print(f"[MacroAnalyzer] {symbol} 추세 조회 실패: {e}")
            return None

    def get_trend_group(self, symbol_map, days=3):
        """심볼 그룹의 추세 데이터를 일괄 조회"""
        results = {}
        for name, symbol in symbol_map.items():
            data = self.get_trend_data(symbol, days)
            if data:
                results[name] = data
        return results
