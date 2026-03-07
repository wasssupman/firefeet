import math
import yaml
import os

class ScalpScreener:
    """스캘핑용 종목 필터: 수수료 대비 유리한 가격대 + 유동성 필터"""

    def __init__(self, manager, settings_path="config/scalping_settings.yaml"):
        self.manager = manager
        self.settings = self._load_settings(settings_path)
        screener_cfg = self.settings.get("screener", {})
        self.min_price = self.settings.get("min_price", 10000)
        self.max_price = self.settings.get("max_price", 500000)
        self.min_volume_ratio = screener_cfg.get("min_volume_ratio", 2.0)
        self.max_spread_bps = screener_cfg.get("max_spread_bps", 30)
        self.optimal_price_min = screener_cfg.get("optimal_price_min", 50000)
        self.optimal_price_max = screener_cfg.get("optimal_price_max", 200000)
        # 거래대금 필터: price × volume >= min_trading_value (기본 500억)
        self.min_trading_value = screener_cfg.get("min_trading_value", 50_000_000_000)
        # 급락 종목 차단: 이미 -3% 이상 하락한 종목은 스캘핑 대상 제외
        self.max_decline_pct = screener_cfg.get("max_decline_pct", -3.0)

    def _load_settings(self, path):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[ScalpScreener] Settings load failed: {e}")
        return {}

    def filter_stocks(self, stocks, orderbook_analyzer=None):
        """
        스캘핑 적합 종목 필터링.
        stocks: Scanner 결과 [{"code", "name", "price", "volume", "change_rate"}, ...]
        Returns: 우선순위순 필터링된 종목 리스트
        """
        candidates = []

        for stock in stocks:
            price = stock.get("price", 0)
            code = stock.get("code", "")

            # 1. 가격 필터
            if price < self.min_price or price > self.max_price:
                continue

            # 2. 변동성 필터 (상한가 제외)
            change_rate = abs(stock.get("change_rate", 0))
            if change_rate >= 30:
                continue

            # 2-1. 급락 종목 차단: 이미 -3% 이상 하락 중인 종목은 스캘핑 불적합
            raw_change_rate = stock.get("change_rate", 0)
            if raw_change_rate <= self.max_decline_pct:
                continue

            # 3. 거래대금 필터 (price × volume >= 500억, P2 원칙)
            volume = stock.get("volume", 0)
            trading_value = price * volume
            if self.min_trading_value > 0 and trading_value < self.min_trading_value:
                continue

            # 4. 스프레드 필터 (호가 데이터가 있을 때만 적용)
            if orderbook_analyzer:
                spread = orderbook_analyzer.get_spread_bps(code)
                if spread != float('inf') and spread > self.max_spread_bps:
                    continue

            # 5. 스코어 계산
            score = self._score_stock(stock)
            candidates.append({
                **stock,
                "scalp_score": score,
            })

        # 스코어 내림차순 정렬
        candidates.sort(key=lambda x: x["scalp_score"], reverse=True)

        print(f"[ScalpScreener] {len(stocks)}종목 → {len(candidates)}종목 필터링 완료")
        return candidates

    def _score_stock(self, stock):
        """스캘핑 적합도 스코어 (0~100)
        - 가격대:    0~30 (최적 가격대 보너스)
        - 틱사이즈:  0~25 (수수료 대비 효율)
        - 거래량:    0~25 (절대 거래량)
        - RVOL 프록시: 0~20 (변동률 × log(거래량) → 종목 활성도, P1 원칙)
        """
        price = stock.get("price", 0)
        volume = stock.get("volume", 0)
        change_rate = stock.get("change_rate", 0)
        score = 0

        # 가격대 점수 (최적 가격대 보너스) — 0~30
        if self.optimal_price_min <= price <= self.optimal_price_max:
            score += 30
        elif price >= 20000:
            score += 20
        else:
            score += 8

        # 틱사이즈 대비 가격 비율 점수 — 0~25
        from core.providers.kis_api import KISManager
        tick_size = KISManager.get_tick_size(price)
        tick_pct = (tick_size / price) * 100  # 1틱 = 몇 %?
        # 수수료(0.21%) 커버에 필요한 틱 수
        ticks_to_cover = 0.21 / tick_pct if tick_pct > 0 else float('inf')
        if ticks_to_cover <= 3:
            score += 25  # 2-3틱으로 수수료 커버 가능
        elif ticks_to_cover <= 5:
            score += 16
        elif ticks_to_cover <= 10:
            score += 8

        # 거래량 점수 — 0~25
        if volume >= 5000000:
            score += 25
        elif volume >= 2000000:
            score += 20
        elif volume >= 1000000:
            score += 15
        elif volume >= 500000:
            score += 8

        # RVOL 프록시 — 0~20 (P1: 상대 거래량 2배+ 원칙 근사)
        # abs(change_rate) × log(volume): 활성도 높을수록 큰 값
        rvol_proxy = abs(change_rate) * math.log(max(volume, 1))
        if rvol_proxy >= 200:
            score += 20
        elif rvol_proxy >= 140:
            score += 15
        elif rvol_proxy >= 80:
            score += 10
        elif rvol_proxy >= 40:
            score += 5

        return min(100, score)

    def get_priority_codes(self, stocks, max_codes=10, orderbook_analyzer=None):
        """
        우선순위순 종목 코드 리스트 반환.
        WebSocket 구독 로테이션에 사용.
        """
        filtered = self.filter_stocks(stocks, orderbook_analyzer)
        return [s["code"] for s in filtered[:max_codes]]
