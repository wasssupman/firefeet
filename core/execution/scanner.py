import requests
import time
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

# ETF 브랜드명 접두사 (네이버 금융 스크래핑 시 필터용)
ETF_PREFIXES = (
    "KODEX", "TIGER", "KBSTAR", "KOSEF", "ARIRANG", "SOL",
    "HANARO", "ACE", "PLUS", "BNK", "TIMEFOLIO", "WOORI",
)


class StockScanner:
    MIN_PRICE = 1000  # 저가주 필터 (1,000원 미만 제외)

    def __init__(self, primary_fetcher=None):
        self.primary_fetcher = primary_fetcher

    @staticmethod
    def _is_market_hours():
        """한국 장 운영시간 여부 (09:00~15:30 KST, 주말 제외)"""
        kst = timezone(timedelta(hours=9))
        now = datetime.now(kst)
        if now.weekday() >= 5:  # 토/일
            return False
        t = now.hour * 100 + now.minute
        return 900 <= t <= 1530

    def get_top_stocks(self, limit=10):
        """
        거래량 상위 종목 조회.
        장중: KIS API (1차) → 네이버 (fallback)
        장외: 네이버 (1차) → KIS API (fallback)
        """
        if self._is_market_hours() and self.primary_fetcher:
            stocks = self.primary_fetcher(limit=limit, min_price=self.MIN_PRICE)
            if stocks:
                return stocks
            print("[StockScanner] Primary fetcher failed, falling back to Naver...")

        stocks = self._scrape_naver(limit)
        if stocks:
            return stocks

        # 장외인데 KIS도 시도해볼 경우
        if not self._is_market_hours() and self.primary_fetcher:
            return self.primary_fetcher(limit=limit, min_price=self.MIN_PRICE)

        return []

    # ──────────────────── 네이버 금융 스크래핑 ────────────────────

    def _scrape_naver(self, limit=10):
        """네이버 금융 거래량 순위 (KOSPI + KOSDAQ 병합)"""
        kospi = self._scrape_naver_market(sosok=0)
        kosdaq = self._scrape_naver_market(sosok=1)

        merged = kospi + kosdaq
        merged.sort(key=lambda s: s['volume'], reverse=True)

        result = merged[:limit]
        if result:
            print(f"[StockScanner] Naver: {len(result)} stocks selected "
                  f"(KOSPI {len(kospi)}, KOSDAQ {len(kosdaq)})")
        return result

    def _scrape_naver_market(self, sosok=0):
        """
        네이버 금융 거래량 상위 종목 스크래핑.
        sosok: 0 (KOSPI), 1 (KOSDAQ)
        """
        url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
        market_name = "KOSPI" if sosok == 0 else "KOSDAQ"

        try:
            res = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            res.raise_for_status()

            soup = BeautifulSoup(res.text, "lxml")
            table = soup.find("table", class_="type_2")
            if not table:
                print(f"[StockScanner] Naver {market_name}: table not found")
                return []

            stocks = []
            for row in table.find_all("tr"):
                cols = row.find_all("td")
                if len(cols) < 6:
                    continue

                name_tag = cols[1].find("a")
                if not name_tag:
                    continue

                name = name_tag.text.strip()

                # ETF 제외
                if name.startswith(ETF_PREFIXES):
                    continue

                # 종목코드 추출
                href = name_tag.get("href", "")
                code = href.split("code=")[-1] if "code=" in href else ""
                if not code or len(code) != 6:
                    continue

                price = self._parse_int(cols[2].text)
                volume = self._parse_int(cols[5].text)

                # 저가주 / 거래량 0 필터
                if price < self.MIN_PRICE or volume <= 0:
                    continue

                # 등락률 파싱
                change_rate = self._parse_float(cols[4].text)

                stocks.append({
                    "code": code,
                    "name": name,
                    "price": price,
                    "volume": volume,
                    "change_rate": change_rate,
                })

            return stocks

        except Exception as e:
            print(f"[StockScanner] Naver {market_name} scrape failed: {e}")
            return []

    # ──────────────────── 유틸리티 ────────────────────

    @staticmethod
    def _parse_int(text):
        try:
            return int(text.strip().replace(",", ""))
        except (ValueError, AttributeError):
            return 0

    @staticmethod
    def _parse_float(text):
        try:
            return float(text.strip().replace(",", "").replace("%", ""))
        except (ValueError, AttributeError):
            return 0.0

    def get_top_volume_stocks(self, limit=10):
        return self.get_top_stocks(limit)


if __name__ == "__main__":
    from core.config_loader import ConfigLoader
    from core.kis_auth import KISAuth
    from core.providers.kis_api import KISManager

    loader = ConfigLoader()
    config = loader.get_kis_config(mode="REAL")
    auth = KISAuth(config)
    
    account_info = loader.get_account_info(mode="REAL")
    manager = KISManager(auth, account_info, mode="REAL")

    scanner = StockScanner(primary_fetcher=manager.get_top_volume_stocks)
    results = scanner.get_top_volume_stocks(10)
    print(f"\n=== 거래량 TOP {len(results)} ===")
    for i, s in enumerate(results, 1):
        print(f"{i:2d}. {s['name']}({s['code']}) "
              f"현재가: {s['price']:,}원  거래량: {s['volume']:,}  등락률: {s['change_rate']:+.2f}%")
