from datetime import datetime

import requests
from bs4 import BeautifulSoup


class ConsensusScraper:
    """증권사 컨센서스 데이터 수집

    데이터 소스:
    - wisereport c1010001: 기업개요 (현재가, 투자의견, 목표가 컨센서스, 증권사별 목표가)
    - wisereport c1050001_data (flag=2): 연간/분기 실적 추정치
    """

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    # 기업개요 페이지 (투자의견 + 증권사별 목표가 포함)
    OVERVIEW_URL = "https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx"
    # 컨센서스 실적 데이터 AJAX 엔드포인트
    CONSENSUS_DATA_URL = "https://navercomp.wisereport.co.kr/company/ajax/c1050001_data.aspx"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def get_target_prices(self, code: str) -> dict:
        """증권사별 목표가 조회

        Returns: {
            "average": float,           # 컨센서스 평균 목표가 (원)
            "high": float,              # 최고 목표가 (원)
            "low": float,               # 최저 목표가 (원)
            "current_price": float,     # 현재 주가 (원)
            "upside": float,            # 평균 목표가 대비 상승여력 (%)
            "brokers": [
                {"broker": str, "target": int, "prev_target": int,
                 "date": str, "opinion": str},
                ...
            ]
        }
        """
        try:
            r = self.session.get(
                self.OVERVIEW_URL,
                params={"cmp_cd": code, "target": "consensus_main"},
                timeout=10,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            tables = soup.find_all("table")

            # 현재 주가 파싱: 시세정보 테이블에서 "주가/전일대비/수익률" 행
            current_price = None
            for t in tables:
                if "시세정보" in (t.get("summary") or ""):
                    for row in t.find_all("tr"):
                        th = row.find("th")
                        if th and "주가/전일대비" in th.get_text():
                            td = row.find("td")
                            if td:
                                # 예: "181,200원 /+2,600원/+1.46%"
                                price_text = td.get_text(strip=True).split("원")[0]
                                current_price = self._parse_number(price_text)
                            break
                    break

            # 컨센서스 요약 테이블: 투자의견, 평균 목표가, EPS, PER, 추정기관수
            avg_target = None
            for t in tables:
                if "투자의견에 대한 컨센서스" in (t.get("summary") or ""):
                    rows = t.find_all("tr")
                    # 두 번째 행: [의견점수, 평균목표가, EPS, PER, 추정기관수]
                    if len(rows) >= 2:
                        cells = rows[1].find_all("td")
                        if len(cells) >= 2:
                            avg_target = self._parse_number(cells[1].get_text(strip=True))
                    break

            # 증권사별 목표가 테이블: 제공처, 최종일자, 목표가, 직전목표가, 변동률, 투자의견, 직전투자의견
            brokers = []
            targets = []
            for t in tables:
                if "제공처별로" in (t.get("summary") or ""):
                    for row in t.find_all("tr")[1:]:  # 헤더 제외
                        cells = row.find_all("td")
                        if len(cells) < 6:
                            continue
                        broker = cells[0].get_text(strip=True)
                        date = cells[1].get_text(strip=True)
                        target = self._parse_number(cells[2].get_text(strip=True))
                        prev_target = self._parse_number(cells[3].get_text(strip=True))
                        opinion = cells[5].get_text(strip=True)
                        if broker and target:
                            brokers.append({
                                "broker": broker,
                                "target": int(target),
                                "prev_target": int(prev_target) if prev_target else None,
                                "date": date,
                                "opinion": opinion,
                            })
                            targets.append(target)
                    break

            # avg_target 파싱 실패 시 brokers 목록으로 계산
            if not avg_target and targets:
                avg_target = sum(targets) / len(targets)

            upside = None
            if avg_target and current_price and current_price > 0:
                upside = round((avg_target - current_price) / current_price * 100, 2)

            return {
                "average": avg_target,
                "high": max(targets) if targets else None,
                "low": min(targets) if targets else None,
                "current_price": current_price,
                "upside": upside,
                "brokers": brokers,
            }

        except Exception as e:
            print(f"[ConsensusScraper] Error: {e}")
            return {}

    def get_ratings(self, code: str) -> dict:
        """투자의견 분포 조회

        Returns: {
            "buy": int,         # 매수 의견 수
            "hold": int,        # 보유(중립) 의견 수
            "sell": int,        # 매도 의견 수
            "total": int,       # 전체 추정기관 수
            "consensus": str    # "매수" / "중립" / "매도"
        }
        """
        try:
            r = self.session.get(
                self.OVERVIEW_URL,
                params={"cmp_cd": code, "target": "consensus_main"},
                timeout=10,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            tables = soup.find_all("table")

            # 투자의견 점수 및 추정기관수 (1=강력매도 ~ 5=강력매수)
            opinion_score = None
            total_count = None
            for t in tables:
                if "투자의견에 대한 컨센서스" in (t.get("summary") or ""):
                    rows = t.find_all("tr")
                    if len(rows) >= 2:
                        cells = rows[1].find_all("td")
                        if len(cells) >= 1:
                            opinion_score = self._parse_number(cells[0].get_text(strip=True))
                        if len(cells) >= 5:
                            total_count = int(
                                self._parse_number(cells[4].get_text(strip=True)) or 0
                            )
                    break

            # 증권사별 의견에서 매수/중립/매도 직접 집계
            buy_kw = {"buy", "strong buy", "outperform", "overweight", "매수", "accumulate", "add"}
            hold_kw = {
                "hold", "neutral", "marketperform", "market perform", "in-line",
                "중립", "보유", "equal weight", "sector perform",
            }
            sell_kw = {"sell", "underperform", "underweight", "매도", "reduce"}

            buy_count = hold_count = sell_count = 0
            for t in tables:
                if "제공처별로" in (t.get("summary") or ""):
                    for row in t.find_all("tr")[1:]:
                        cells = row.find_all("td")
                        if len(cells) < 6:
                            continue
                        opinion = cells[5].get_text(strip=True).lower()
                        if any(k in opinion for k in buy_kw):
                            buy_count += 1
                        elif any(k in opinion for k in sell_kw):
                            sell_count += 1
                        elif any(k in opinion for k in hold_kw):
                            hold_count += 1
                        else:
                            # 미분류 의견은 매수로 처리 (한국 시장 특성상 대부분 매수)
                            buy_count += 1
                    break

            # 투자의견 점수로 컨센서스 레이블 결정
            # 1=강력매도, 2=매도, 3=중립, 4=매수, 5=강력매수
            consensus_label = "알수없음"
            if opinion_score is not None:
                if opinion_score >= 3.5:
                    consensus_label = "매수"
                elif opinion_score >= 2.5:
                    consensus_label = "중립"
                else:
                    consensus_label = "매도"

            return {
                "buy": buy_count,
                "hold": hold_count,
                "sell": sell_count,
                "total": total_count or (buy_count + hold_count + sell_count),
                "consensus": consensus_label,
            }

        except Exception as e:
            print(f"[ConsensusScraper] Error: {e}")
            return {}

    def get_earnings_estimates(self, code: str) -> dict:
        """실적 추정치 (컨센서스)

        Returns: {
            "annual": [
                {
                    "year": str,                # 예: "2025.12(E)"
                    "is_estimate": bool,        # (E)이면 추정치, (A)이면 실적
                    "revenue": float,           # 매출액 (억원)
                    "revenue_yoy": float,       # 매출 YoY 성장률 (%)
                    "operating_profit": float,  # 영업이익 (억원)
                    "net_income": float,        # 당기순이익 (억원)
                    "eps": float,               # EPS (원)
                    "bps": float,               # BPS (원)
                    "per": float,               # PER (배)
                    "pbr": float,               # PBR (배)
                    "roe": float,               # ROE (%)
                    "ev_ebitda": float,         # EV/EBITDA (배)
                },
                ...
            ],
            "quarterly": [ ... ]  # 동일 구조, "year" 대신 "quarter" 키
        }
        """
        try:
            today = datetime.now().strftime("%Y%m%d")
            annual = self._fetch_estimates(code, frq=0, today=today)
            quarterly = self._fetch_estimates(code, frq=1, today=today)
            return {"annual": annual, "quarterly": quarterly}

        except Exception as e:
            print(f"[ConsensusScraper] Error: {e}")
            return {}

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _fetch_estimates(self, code: str, frq: int, today: str) -> list:
        """c1050001_data.aspx flag=2 로 연간(frq=0) 또는 분기(frq=1) 실적 추정치 반환"""
        params = {
            "flag": "2",
            "cmp_cd": code,
            "finGubun": "K-IFRS(연결)",
            "frq": str(frq),
            "sDT": today,
        }
        r = self.session.get(self.CONSENSUS_DATA_URL, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        period_key = "year" if frq == 0 else "quarter"
        records = []
        for item in data.get("JsonData", []):
            yymm = item.get("YYMM", "")
            records.append({
                period_key: yymm,
                "is_estimate": "(E)" in yymm,
                "revenue": self._parse_number(item.get("SALES")),
                "revenue_yoy": self._parse_number(item.get("YOY")),
                "operating_profit": self._parse_number(item.get("OP")),
                "net_income": self._parse_number(item.get("NP")),
                "eps": self._parse_number(item.get("EPS")),
                "bps": self._parse_number(item.get("BPS")),
                "per": self._parse_number(item.get("PER")),
                "pbr": self._parse_number(item.get("PBR")),
                "roe": self._parse_number(item.get("ROE")),
                "ev_ebitda": self._parse_number(item.get("EV")),
            })
        return records

    def _parse_number(self, text):
        """숫자 파싱 (콤마 제거, 음수 처리)

        Returns float 또는 None
        """
        if text is None:
            return None
        text = str(text).strip()
        if not text or text in ("-", "N/A", "--", "—"):
            return None
        # 단위 문자 제거
        text = text.replace(",", "").replace("원", "").replace("%", "").replace("배", "")
        # 괄호 음수: (1,234) → -1234
        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]
        try:
            return float(text)
        except ValueError:
            return None


if __name__ == "__main__":
    import json

    scraper = ConsensusScraper()
    code = "005930"  # 삼성전자

    print(f"\n{'='*60}")
    print(f"[테스트] 종목코드: {code} (삼성전자)")
    print(f"{'='*60}")

    print("\n--- 목표가 ---")
    targets = scraper.get_target_prices(code)
    print(json.dumps(targets, ensure_ascii=False, indent=2))

    print("\n--- 투자의견 분포 ---")
    ratings = scraper.get_ratings(code)
    print(json.dumps(ratings, ensure_ascii=False, indent=2))

    print("\n--- 실적 추정치 ---")
    estimates = scraper.get_earnings_estimates(code)
    print(json.dumps(estimates, ensure_ascii=False, indent=2))
