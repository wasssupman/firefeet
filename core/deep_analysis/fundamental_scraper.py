import re
import requests
from bs4 import BeautifulSoup


class FundamentalScraper:
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    # ──────────────────────────────────────────────────────────────────────────
    # Public methods
    # ──────────────────────────────────────────────────────────────────────────

    def get_company_overview(self, code: str) -> dict:
        """
        네이버 금융 종목 메인 페이지에서 기업 개요 데이터를 수집.
        시가총액, 상장주식수, 액면가, PER, PBR, 배당수익률, 52주 최고/최저,
        업종명, 업종 PER, 현재가, 전일대비 변화 등을 반환.
        """
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        try:
            res = self.session.get(url, timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "lxml")

            result = {"code": code}

            # 현재가 파싱 (blind span 사용 — 가장 정확)
            price_tag = soup.find("p", class_="no_today")
            if price_tag:
                blind = price_tag.find("span", class_="blind")
                if blind:
                    result["current_price"] = self._safe_float(
                        self._parse_number(blind.get_text(strip=True))
                    )

            # 전일대비 (절대값, 등락률)
            exday_tag = soup.find("p", class_="no_exday")
            if exday_tag:
                blinds = exday_tag.find_all("span", class_="blind")
                if len(blinds) >= 2:
                    result["change"] = self._safe_float(
                        self._parse_number(blinds[0].get_text(strip=True))
                    )
                    result["change_rate"] = self._safe_float(
                        self._parse_number(blinds[1].get_text(strip=True))
                    )
                    # 하락 여부 → 부호 보정
                    em_tag = exday_tag.find("em")
                    if em_tag and "no_down" in em_tag.get("class", []):
                        result["change"] = -abs(result.get("change", 0))
                        result["change_rate"] = -abs(result.get("change_rate", 0))

            # 시가총액 / 상장주식수 / 액면가
            mktcap_table = soup.find("table", attrs={"summary": "시가총액 정보"})
            if mktcap_table:
                for row in mktcap_table.find_all("tr"):
                    th = row.find("th")
                    td = row.find("td")
                    if not th or not td:
                        continue
                    label = th.get_text(strip=True)
                    value = td.get_text(separator=" ", strip=True)

                    if "시가총액" in label and "순위" not in label:
                        result["market_cap"] = self._parse_korean_amount(value)
                    elif "상장주식수" in label:
                        result["shares_outstanding"] = self._safe_float(
                            self._parse_number(value.split()[0])
                        )
                    elif "액면가" in label:
                        # "100원 l 1주" 형태 → 숫자만 추출
                        nums = re.findall(r"[\d,]+", value)
                        if nums:
                            result["par_value"] = self._safe_float(
                                self._parse_number(nums[0])
                            )

            # 52주 최고/최저 (투자의견 테이블)
            rwidth_table = soup.find("table", class_="rwidth")
            if rwidth_table:
                for row in rwidth_table.find_all("tr"):
                    th = row.find("th")
                    if th and "52주최고" in th.get_text():
                        # <td>에 <em>태그로 최고/최저가 두 개 존재
                        ems = row.find("td").find_all("em") if row.find("td") else []
                        if len(ems) >= 2:
                            result["week52_high"] = self._safe_float(
                                self._parse_number(ems[0].get_text(strip=True))
                            )
                            result["week52_low"] = self._safe_float(
                                self._parse_number(ems[1].get_text(strip=True))
                            )
                        break

            # 업종명 — em 태그 안에 "(업종명 :XXX)" 패턴
            for em in soup.find_all("em"):
                text = em.get_text(strip=True)
                if "업종명" in text:
                    m = re.search(r"업종명\s*[:：]\s*([^｜|]+)", text)
                    if m:
                        result["sector"] = m.group(1).strip()
                    break

            # PER, PBR, 배당수익률 — PER/EPS 정보 테이블
            per_table = soup.find("table", attrs={"summary": "PER/EPS 정보"})
            if per_table:
                rows = per_table.find_all("tr")
                for row in rows:
                    th = row.find("th")
                    td = row.find("td")
                    if not th or not td:
                        continue
                    label = th.get_text(strip=True)
                    value = td.get_text(strip=True)
                    if "PER" in label and "추정" not in label and "PBR" not in label:
                        m = re.search(r"([\d.]+)배", value)
                        if m:
                            result["per"] = self._safe_float(m.group(1))
                    elif "추정PER" in label:
                        m = re.search(r"([\d.]+)배", value)
                        if m:
                            result["estimated_per"] = self._safe_float(m.group(1))
                    elif "PBR" in label:
                        m = re.search(r"([\d.]+)배", value)
                        if m:
                            result["pbr"] = self._safe_float(m.group(1))
                    elif "배당수익률" in label:
                        m = re.search(r"([\d.]+)%", value)
                        if m:
                            result["dividend_yield"] = self._safe_float(m.group(1))

            # 동일업종 PER — 주요재무정보 아래 있는 업종 비교 영역
            for tag in soup.find_all(string=lambda s: s and "동일업종 PER" in s):
                parent = tag.parent.find_parent("table") or tag.parent.find_parent("div")
                if parent:
                    text = parent.get_text(strip=True)
                    m = re.search(r"동일업종 PER\s*([\d.]+)배", text)
                    if m:
                        result["sector_per"] = self._safe_float(m.group(1))
                    break

            # 기업실적분석 테이블에서 최신 PER, PBR 보완 (per_table에서 못 찾은 경우)
            if "per" not in result or "pbr" not in result:
                fin_table = soup.find(
                    "table",
                    attrs={"summary": lambda s: s and "기업실적분석" in s},
                )
                if fin_table:
                    for row in fin_table.find_all("tr"):
                        th = row.find("th")
                        if not th:
                            continue
                        label = th.get_text(strip=True)
                        tds = row.find_all("td")
                        # 연간 실적 기준 가장 최근 컬럼 (4번째 = 현재 연도 추정치 제외, 3번째 사용)
                        if tds:
                            # 실제 확정 값 = 4번째 열 이전 중 마지막 (추정 열 제외)
                            confirmed_tds = [
                                td for td in tds if "cell_strong" not in td.get("class", [])
                            ]
                            latest_val = (
                                confirmed_tds[-1].get_text(strip=True) if confirmed_tds else ""
                            )
                            if "PER" in label and "per" not in result:
                                result["per"] = self._safe_float(
                                    self._parse_number(latest_val)
                                )
                            elif "PBR" in label and "pbr" not in result:
                                result["pbr"] = self._safe_float(
                                    self._parse_number(latest_val)
                                )
                            elif "주당배당금" in label:
                                result["dps"] = self._safe_float(
                                    self._parse_number(latest_val)
                                )
                            elif "시가배당률" in label:
                                result["dividend_yield"] = self._safe_float(
                                    self._parse_number(latest_val)
                                )

            return result

        except Exception as e:
            print(f"[FundamentalScraper] get_company_overview Error: {e}")
            return {}

    def get_financial_statements(self, code: str, period: str = "annual") -> dict:
        """
        네이버 금융 기업실적분석 테이블에서 재무제표 데이터를 수집.
        period: "annual" (연간) 또는 "quarterly" (분기)
        반환: {periods, revenue, operating_profit, net_income,
                op_margin, net_margin, roe, debt_ratio, eps, bps, dps}
        """
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        try:
            res = self.session.get(url, timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "lxml")

            fin_table = soup.find(
                "table",
                attrs={"summary": lambda s: s and "기업실적분석" in s},
            )
            if not fin_table:
                print(f"[FundamentalScraper] 기업실적분석 테이블 미발견 (code={code})")
                return {}

            # 헤더에서 기간 목록 파싱
            # thead의 두 번째 tr에 연도/분기 컬럼
            header_rows = fin_table.find("thead").find_all("tr")
            # header_rows[0] = "최근 연간 실적 / 최근 분기 실적" colspan 행
            # header_rows[1] = 각 기간 (2022.12, 2023.12, ...)
            # header_rows[2] = IFRS연결 표기

            period_row = header_rows[1] if len(header_rows) > 1 else None
            if not period_row:
                return {}

            all_periods = [th.get_text(strip=True) for th in period_row.find_all("th")]
            # 첫 번째 colspan 행에서 연간/분기 컬럼 수 파악
            group_row = header_rows[0]
            group_ths = group_row.find_all("th")
            annual_count = 0
            quarterly_count = 0
            for gth in group_ths:
                if not gth.get("colspan"):
                    continue
                n = int(gth.get("colspan", 1))
                text = gth.get_text(strip=True)
                if "연간" in text:
                    annual_count = n
                elif "분기" in text:
                    quarterly_count = n

            if period == "annual":
                target_periods = all_periods[:annual_count]
                col_start = 0
                col_end = annual_count
            else:
                target_periods = all_periods[annual_count : annual_count + quarterly_count]
                col_start = annual_count
                col_end = annual_count + quarterly_count

            # 각 행에서 데이터 파싱
            row_map = {
                "매출액": "revenue",
                "영업이익": "operating_profit",
                "당기순이익": "net_income",
                "영업이익률": "op_margin",
                "순이익률": "net_margin",
                "ROE": "roe",
                "ROA": "roa",
                "부채비율": "debt_ratio",
                "당좌비율": "quick_ratio",
                "EPS": "eps",
                "BPS": "bps",
                "주당배당금": "dps",
                "PER": "per",
                "PBR": "pbr",
                "배당성향": "payout_ratio",
            }

            result: dict = {"periods": target_periods}
            for key in row_map.values():
                result[key] = []

            # 긴 키 우선 정렬 — "영업이익률"이 "영업이익"보다 먼저 매칭되도록
            sorted_row_map = sorted(row_map.items(), key=lambda x: -len(x[0]))

            for row in fin_table.find("tbody").find_all("tr"):
                th = row.find("th")
                if not th:
                    continue
                label = th.get_text(strip=True)

                # 매핑 키 탐색 (부분 일치, 긴 키 우선)
                matched_key = None
                for kr_label, en_key in sorted_row_map:
                    if kr_label in label:
                        matched_key = en_key
                        break
                if not matched_key:
                    continue

                tds = row.find_all("td")
                values = [self._safe_float(self._parse_number(td.get_text(strip=True)))
                          for td in tds]
                result[matched_key] = values[col_start:col_end]

            return result

        except Exception as e:
            print(f"[FundamentalScraper] get_financial_statements Error: {e}")
            return {}

    def get_profitability(self, code: str) -> dict:
        """
        수익성 지표(ROE, ROA, 영업이익률) 트렌드를 반환.
        재무제표 데이터에서 파생.
        """
        try:
            data = self.get_financial_statements(code, period="annual")
            if not data:
                return {}

            return {
                "periods": data.get("periods", []),
                "roe": data.get("roe", []),
                "roa": data.get("roa", []),
                "op_margin": data.get("op_margin", []),
                "net_margin": data.get("net_margin", []),
            }
        except Exception as e:
            print(f"[FundamentalScraper] get_profitability Error: {e}")
            return {}

    def get_stability(self, code: str) -> dict:
        """
        안정성 지표(부채비율, 당좌비율) 트렌드를 반환.
        재무제표 데이터에서 파생.
        """
        try:
            data = self.get_financial_statements(code, period="annual")
            if not data:
                return {}

            return {
                "periods": data.get("periods", []),
                "debt_ratio": data.get("debt_ratio", []),
                "quick_ratio": data.get("quick_ratio", []),
            }
        except Exception as e:
            print(f"[FundamentalScraper] get_stability Error: {e}")
            return {}

    # ──────────────────────────────────────────────────────────────────────────
    # Helper methods
    # ──────────────────────────────────────────────────────────────────────────

    def _parse_number(self, text: str):
        """
        한국식 숫자 표기를 float으로 변환.
        예: "1,234" → 1234.0 / "14.35" → 14.35 / "-" → None
        """
        if not text:
            return None
        text = text.strip().replace(",", "").replace(" ", "")
        if text in ("-", "N/A", "", "—"):
            return None
        # % 기호 제거 (값은 그대로 사용)
        text = text.replace("%", "").replace("배", "").replace("원", "")
        try:
            return float(text)
        except ValueError:
            return None

    def _parse_korean_amount(self, text: str):
        """
        한국식 단위(조, 억)를 포함한 금액을 억원 단위 float으로 변환.
        예: "1,126조 5,071억원" → 11265071.0 (억원 단위)
            "5,071억원" → 5071.0
        """
        if not text:
            return None
        text = text.replace(",", "").replace(" ", "")
        result = 0.0
        # 조 단위
        m = re.search(r"([\d.]+)조", text)
        if m:
            result += float(m.group(1)) * 10000  # 1조 = 10,000억
        # 억 단위
        m = re.search(r"([\d.]+)억", text)
        if m:
            result += float(m.group(1))
        if result == 0.0:
            # 단순 숫자
            parsed = self._parse_number(text)
            return parsed
        return result

    def _safe_float(self, val) -> float:
        """None이나 변환 실패 시 None을 반환하는 안전한 float 변환."""
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None


# ──────────────────────────────────────────────────────────────────────────────
# 단독 실행 테스트
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    scraper = FundamentalScraper()
    code = "005930"  # 삼성전자

    print(f"\n{'='*60}")
    print(f"[테스트] 종목코드: {code} (삼성전자)")
    print(f"{'='*60}")

    print("\n--- 기업 개요 ---")
    overview = scraper.get_company_overview(code)
    print(json.dumps(overview, ensure_ascii=False, indent=2))

    print("\n--- 재무제표 (연간) ---")
    statements = scraper.get_financial_statements(code, period="annual")
    print(json.dumps(statements, ensure_ascii=False, indent=2))

    print("\n--- 재무제표 (분기) ---")
    statements_q = scraper.get_financial_statements(code, period="quarterly")
    print(json.dumps(statements_q, ensure_ascii=False, indent=2))

    print("\n--- 수익성 ---")
    profitability = scraper.get_profitability(code)
    print(json.dumps(profitability, ensure_ascii=False, indent=2))

    print("\n--- 안정성 ---")
    stability = scraper.get_stability(code)
    print(json.dumps(stability, ensure_ascii=False, indent=2))
