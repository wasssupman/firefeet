import time
import yaml
import os

from core.analysis.supply import SupplyAnalyzer


class StockScreener:
    """
    복합 스코어링 기반 종목 스크리너.
    Scanner(거래량 TOP 20) → Screener(스코어링) → Watchlist(TOP 10) → Trader
    """

    DEFAULT_SETTINGS_PATH = "config/screener_settings.yaml"

    def __init__(self, strategy, discord=None, settings_path=None):
        self.strategy = strategy
        self.discord = discord
        self.settings = self._load_settings(settings_path or self.DEFAULT_SETTINGS_PATH)

    def _load_settings(self, path):
        default = {
            "weights": {
                "volume_surge": 20,
                "price_momentum": 10,
                "ma_alignment": 20,
                "supply_demand": 20,
                "breakout_proximity": 15,
                "intraday_strength": 5,
                "contraction_bonus": 10,   # ATR 수축 보너스
            },
            "pre_filter": {
                "min_volume": 500000,
                "max_price": 500000,
                "min_change_rate": -2.0,
                "max_change_rate": 15.0,
            },
            "trend_filter": {
                "enabled": True,
                "min_ohlc_days": 120,  # MA120 계산에 필요한 최소 데이터
            },
            "output": {
                "min_score": 30,
                "max_stocks": 10,
            },
            "cache": {
                "ttl": 300,
            },
        }
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                    if loaded:
                        for key in default:
                            if key in loaded and isinstance(default[key], dict):
                                default[key].update(loaded[key])
        except Exception as e:
            print(f"[Screener] Settings load failed: {e}")
        return default

    # ────────────────────── Scoring Functions ──────────────────────

    def _score_volume_surge(self, stock, ohlc):
        """
        거래량 급증 (25점): 금일 거래량 / 5일 평균 거래량.
        5x↑→100, 3x→80, 2x→60, 1.5x→40, 1x→20, 미만→0
        """
        if ohlc is None or (hasattr(ohlc, 'empty') and ohlc.empty) or len(ohlc) < 6:
            return 0

        today_volume = stock["volume"]
        # OHLC is sorted latest first; indices 1-5 = past 5 trading days
        avg_5d = ohlc.iloc[1:6]["volume"].mean()
        if avg_5d <= 0:
            return 0

        ratio = today_volume / avg_5d

        if ratio >= 5.0:
            return 100
        elif ratio >= 3.0:
            return 80
        elif ratio >= 2.0:
            return 60
        elif ratio >= 1.5:
            return 40
        elif ratio >= 1.0:
            return 20
        else:
            return 0

    def _score_price_momentum(self, stock):
        """
        가격 모멘텀 (15점): 등락률 sweet spot.
        피크 +3% (100점), 0% 이하 or +13% 이상 → 0점.
        """
        cr = stock["change_rate"]

        if cr <= 0 or cr >= 13:
            return 0
        if cr <= 3:
            # 0 → 0, 3 → 100 (linear ramp up)
            return (cr / 3) * 100
        else:
            # 3 → 100, 13 → 0 (linear decay)
            return max(0, 100 - (cr - 3) * 10)

    def _score_ma_alignment(self, stock, ohlc):
        """
        이동평균 정배열 (20점): P > 5MA > 20MA → 60~100점.
        부분 정배열(P > 5MA만) → 30점. 역배열 → 0점.
        """
        if ohlc is None or (hasattr(ohlc, 'empty') and ohlc.empty) or len(ohlc) < 20:
            return 0

        price = stock["price"]
        ma5 = ohlc.iloc[:5]["close"].mean()
        ma20 = ohlc.iloc[:20]["close"].mean()

        if price > ma5 > ma20:
            # 정배열: MA 간격(spread)에 따라 60~100
            spread = (ma5 - ma20) / ma20 * 100
            bonus = min(40, spread * 10)
            return 60 + bonus
        elif price > ma5:
            # 부분 정배열
            return 30
        else:
            # 역배열
            return 0

    def _score_supply_demand(self, supply):
        """
        수급 (25점): 외국인+기관 3일 순매수.
        쌍끌이 매수 → 80~100, 한쪽만 → 50~55, 쌍끌이 매도 → 0.
        """
        if supply is None or (hasattr(supply, 'empty') and supply.empty) or (isinstance(supply, str) and supply == "No Data"):
            return 0

        sentiment = supply.get("sentiment", "NEUTRAL")
        foreign_3d = supply.get("foreign_3d", 0)
        inst_3d = supply.get("institution_3d", 0)

        if sentiment == "BULLISH (Double Buy)":
            total = abs(foreign_3d) + abs(inst_3d)
            if total > 100000:
                return 100
            elif total > 50000:
                return 90
            else:
                return 80
        elif foreign_3d > 0 or inst_3d > 0:
            return 55 if foreign_3d > 0 else 50
        elif sentiment == "BEARISH (Double Sell)":
            return 0
        else:
            return 25  # NEUTRAL

    def _score_breakout_proximity(self, stock, ohlc):
        """
        돌파 근접도 (15점): 현재가 vs 변동성 돌파 목표가.
        이미 돌파 → 85~100, 0.5% 이내 → 75, 5% 이상 → 0.
        OHLC 데이터를 재사용하여 추가 API 호출 없음.
        """
        if ohlc is None or (hasattr(ohlc, 'empty') and ohlc.empty) or len(ohlc) < 2:
            return 0

        price = stock["price"]
        code = stock["code"]
        today = ohlc.iloc[0]
        yesterday = ohlc.iloc[1]

        # 단독 스크리너 실행('deep_batch' 등 문자열로 들어오는 경우) 방어 로직
        if not hasattr(self.strategy, 'get_target_price'):
            return 0

        # ohlc 전달하여 get_target_price 활용 (API 호출 0)
        target_info = self.strategy.get_target_price(code, ohlc)
        if not target_info:
            return 0
            
        target = target_info['target_price']
        
        if target <= 0:
            return 0

        diff_pct = (target - price) / target * 100

        if price >= target:
            over_pct = (price - target) / target * 100
            return 100 if over_pct < 2 else 85
        elif diff_pct <= 0.5:
            return 75
        elif diff_pct <= 1.0:
            return 60
        elif diff_pct <= 2.0:
            return 40
        elif diff_pct <= 5.0:
            return 20
        else:
            return 0

    def _score_intraday_strength(self, stock, current_data):
        """장중 체력 (현재가 vs 장중고가). 고점 대비 -3% 이상 하락 → 0점"""
        if not current_data or current_data.get('high', 0) <= 0:
            return 50  # 데이터 없으면 중립
        high = current_data['high']
        price = stock['price']
        drop_pct = (high - price) / high * 100

        if drop_pct <= 0.5:
            return 100  # 고가 근처
        if drop_pct <= 1.0:
            return 80
        if drop_pct <= 2.0:
            return 50
        if drop_pct <= 3.0:
            return 20
        return 0  # 고점 대비 3%+ 하락 → 부적격

    def _check_ma120_trend(self, ohlc):
        """
        MA120 추세 필터: 개별 종목이 상승 추세(Stage 2)에 있는지 확인.
        Returns: (passes: bool, reason: str)
        - price > MA120 AND MA120 기울기 > 0 → 통과
        - 데이터 부족 시 통과 (필터 비활성화)
        """
        if ohlc is None or (hasattr(ohlc, 'empty') and ohlc.empty) or len(ohlc) < 120:
            return True, "데이터 부족 (MA120 필터 비활성)"

        price = float(ohlc.iloc[0]['close'])
        ma120 = ohlc.iloc[:120]['close'].astype(float).mean()

        if price <= ma120:
            return False, f"MA120 하회 (가격:{price:,.0f} < MA120:{ma120:,.0f})"

        # MA120 기울기: 현재 MA120 vs 20일 전 MA120
        if len(ohlc) >= 140:
            ma120_20d_ago = ohlc.iloc[20:140]['close'].astype(float).mean()
            if ma120 < ma120_20d_ago:
                return False, f"MA120 하락 중 (현재:{ma120:,.0f} < 20일전:{ma120_20d_ago:,.0f})"

        return True, "Stage 2 확인"

    def _score_contraction_bonus(self, ohlc):
        """
        ATR 수축 보너스: ATR(5)/ATR(20) 비율로 변동성 수축 정도 측정.
        < 0.5 = 극도의 수축 (100점)
        < 0.8 = 수축 중 (70점)
        0.8~1.0 = 보통 (30점)
        > 1.0 = 확장 중 (0점)
        """
        if ohlc is None or (hasattr(ohlc, 'empty') and ohlc.empty) or len(ohlc) < 21:
            return 0

        from core.analysis.technical import VolatilityBreakoutStrategy
        ratio = VolatilityBreakoutStrategy().get_contraction_ratio(ohlc)

        if ratio is None:
            return 0
        if ratio < 0.5:
            return 100  # 극도의 수축 → 폭발적 돌파 임박 가능
        if ratio < 0.8:
            return 70   # 수축 중 → 돌파 시 가치 있는 신호
        if ratio <= 1.0:
            return 30   # 보통 → 약간의 가산점
        return 0        # 이미 확장 중 → 보너스 없음

    # ────────────────────── Main Scoring ──────────────────────

    def score_stock(self, stock, ohlc, supply, current_data):
        """종목 종합 스코어 계산 (0~100점). 데이터는 외부에서 주입됨."""
        if ohlc is None or (hasattr(ohlc, 'empty') and ohlc.empty) or current_data is None:
            return None
        code = stock["code"]
        weights = self.settings["weights"]

        # Raw scores (0~100)
        scores = {
            "volume_surge": self._score_volume_surge(stock, ohlc),
            "price_momentum": self._score_price_momentum(stock),
            "ma_alignment": self._score_ma_alignment(stock, ohlc),
            "supply_demand": self._score_supply_demand(supply),
            "breakout_proximity": self._score_breakout_proximity(stock, ohlc),
            "intraday_strength": self._score_intraday_strength(stock, current_data),
            "contraction_bonus": self._score_contraction_bonus(ohlc),
        }

        # Weighted total (0~100)
        total = sum(raw * (weights.get(key, 0) / 100) for key, raw in scores.items())

        return {
            "code": code,
            "name": stock.get("name", "Unknown"),
            "price": stock["price"],
            "change_rate": stock["change_rate"],
            "total_score": round(total, 1),
            "detail": scores,
        }

    # ────────────────────── Screen Pipeline ──────────────────────

    def screen(self, stocks, data_provider_fn):
        """
        Full screening pipeline:
        1. Pre-filter (API 0회)
        2. Score each stock (데이터는 data_provider_fn(code) 콜백으로 요청)
        3. Sort by score → top N 선별
        4. Discord 리포트
        
        data_provider_fn(code) -> (ohlc, supply, current_data) 튜플 반환 기대
        """
        # 1. Pre-filter
        pf = self.settings["pre_filter"]
        candidates = []
        for s in stocks:
            if s["volume"] < pf["min_volume"] or s["price"] > pf["max_price"] or s["change_rate"] < pf["min_change_rate"] or s["change_rate"] > pf["max_change_rate"]:
                continue
            candidates.append(s)
            
        removed = len(stocks) - len(candidates)
        if removed > 0:
            print(f"[Screener] Pre-filter: {len(stocks)} → {len(candidates)} ({removed} removed)")

        if not candidates:
            print("[Screener] No candidates after pre-filter")
            return []

        # 1.5 MA120 Trend Filter (추세 확인)
        trend_cfg = self.settings.get("trend_filter", {})
        if trend_cfg.get("enabled", True):
            trend_passed = []
            trend_rejected = []
            for stock in candidates:
                try:
                    ohlc, _, _ = data_provider_fn(stock["code"])
                    passes, reason = self._check_ma120_trend(ohlc)
                    if passes:
                        trend_passed.append(stock)
                    else:
                        trend_rejected.append((stock.get("name", stock["code"]), reason))
                except Exception:
                    trend_passed.append(stock)  # 에러 시 통과 (보수적)
            if trend_rejected:
                print(f"[Screener] MA120 추세 필터: {len(trend_rejected)}종목 제외")
                for name, reason in trend_rejected[:5]:
                    print(f"  ❌ {name}: {reason}")
            candidates = trend_passed

            if not candidates:
                print("[Screener] No candidates after MA120 trend filter")
                return []

        # 2. Score
        print(f"[Screener] Scoring {len(candidates)} stocks...")
        results = []
        for i, stock in enumerate(candidates):
            name = stock.get("name", stock["code"])
            print(f"  ({i+1}/{len(candidates)}) {name}...")
            try:
                # 콜백을 통해 데이터 요청
                ohlc, supply, current_data = data_provider_fn(stock["code"])
                result = self.score_stock(stock, ohlc, supply, current_data)
                if result is not None:
                    results.append(result)
            except Exception as e:
                import traceback
                print(f"  [Screener] Error scoring {name}: {e}")
                traceback.print_exc()

        # --- Phase 2: AI Thematic Filter Override ---
        ai_config = self.settings.get("ai_thematic_filter", {})
        if ai_config.get("enabled", False):
            try:
                from core.analysis.ai_thematic_filter import AIThematicFilter
                ai_filter = AIThematicFilter(ai_config)
                print(f"[Screener] Applying AI Thematic Filter to Top {ai_config.get('top_n', 15)} candidates...")
                results = ai_filter.filter_candidates(results, top_n=ai_config.get("top_n", 15))
            except Exception as e:
                import traceback
                print(f"[Screener] AI Thematic Filter Error: {e}")
                traceback.print_exc()

        # 3. Sort & filter
        cfg = self.settings["output"]
        min_score = cfg["min_score"]
        max_stocks = cfg["max_stocks"]

        min_breakout = cfg.get("min_breakout_proximity", 0)

        results.sort(key=lambda r: r["total_score"], reverse=True)
        selected = [r for r in results
                    if r["total_score"] >= min_score
                    and r["detail"]["breakout_proximity"] >= min_breakout][:max_stocks]

        if min_breakout > 0:
            bp_filtered = sum(1 for r in results
                              if r["total_score"] >= min_score
                              and r["detail"]["breakout_proximity"] < min_breakout)
            if bp_filtered > 0:
                print(f"[Screener] {bp_filtered} stocks removed (breakout_proximity < {min_breakout})")
        print(f"[Screener] {len(selected)} stocks selected (score >= {min_score})")

        # 4. Discord report
        self._send_report(results, selected)

        return selected

    def get_screened_stocks(self, stocks, data_provider_fn):
        """
        Trader.update_target_codes() 에 전달할 형식으로 반환.
        Returns: [{"code": "005930", "name": "삼성전자"}, ...]
        """
        screened = self.screen(stocks, data_provider_fn)
        return [{"code": r["code"], "name": r["name"]} for r in screened]

    # ────────────────────── Discord Report ──────────────────────

    def _send_report(self, all_results, selected):
        """Discord 스크리닝 리포트 전송"""
        if not self.discord:
            return

        selected_codes = {r["code"] for r in selected}
        lines = ["📊 **[Screener] 종목 스크리닝 결과**\n"]

        for i, r in enumerate(all_results[:15], 1):
            mark = "✅" if r["code"] in selected_codes else "❌"
            lines.append(
                f"{mark} {i}. **{r['name']}**({r['code']}) "
                f"Score: **{r['total_score']}** | "
                f"{r['price']:,}원 ({r['change_rate']:+.1f}%)"
            )
            d = r["detail"]
            lines.append(
                f"   Vol:{d['volume_surge']} Mom:{d['price_momentum']:.0f} "
                f"MA:{d['ma_alignment']:.0f} Sup:{d['supply_demand']} "
                f"Brk:{d['breakout_proximity']} Ctr:{d.get('contraction_bonus', '-')} Str:{d.get('intraday_strength', '-')}"
            )

        lines.append(
            f"\n**선별: {len(selected)}종목** "
            f"(기준: {self.settings['output']['min_score']}점 이상)"
        )

        self.discord.send("\n".join(lines))


# ────────────────────── Standalone Test ──────────────────────

if __name__ == "__main__":
    from core.config_loader import ConfigLoader
    from core.kis_auth import KISAuth
    from core.providers.kis_api import KISManager
    from core.analysis.technical import VolatilityBreakoutStrategy
    from core.scanner import StockScanner

    print("=== StockScreener Standalone Test ===\n")

    loader = ConfigLoader()
    config = loader.get_kis_config(mode="REAL")
    account_info = loader.get_account_info()

    auth = KISAuth(config)
    manager = KISManager(auth, account_info, mode="REAL")
    strategy = VolatilityBreakoutStrategy(k=0.5)
    scanner = StockScanner(auth)
    screener = StockScreener(manager, strategy)

    # 1. Scan top 20 volume stocks
    print("[Test] Scanning top 20 volume stocks...")
    raw_stocks = scanner.get_top_volume_stocks(limit=20)
    print(f"[Test] Scanner found {len(raw_stocks)} stocks\n")

    if not raw_stocks:
        print("[Test] No stocks found. Exiting.")
        exit(1)

    # 2. Run screener
    results = screener.screen(raw_stocks)

    # 3. Print results
    print(f"\n{'='*60}")
    print(f"{'RANK':<5} {'NAME':<12} {'CODE':<8} {'SCORE':>6} {'PRICE':>10} {'CHG':>7}")
    print(f"{'='*60}")
    for i, r in enumerate(results, 1):
        print(
            f"{i:<5} {r['name']:<12} {r['code']:<8} "
            f"{r['total_score']:>6.1f} {r['price']:>10,} {r['change_rate']:>+6.1f}%"
        )
        d = r["detail"]
        print(
            f"      Vol:{d['volume_surge']:>3} Mom:{d['price_momentum']:>3.0f} "
            f"MA:{d['ma_alignment']:>3.0f} Sup:{d['supply_demand']:>3} "
            f"Brk:{d['breakout_proximity']:>3}"
        )
    print(f"{'='*60}")
    print(f"Total selected: {len(results)}")
