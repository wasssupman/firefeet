import re
import time

import requests
from bs4 import BeautifulSoup


class PeerAnalyzer:
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    # ────────────────────── Public API ──────────────────────

    def get_sector_peers(self, code: str, limit: int = 10) -> list:
        """동일 업종 종목 추출

        Step 1: 네이버 금융 종목 메인 페이지에서 업종 정보 획득
        Step 2: 업종 페이지에서 상위 N개 종목 추출 (시가총액 기준)

        Returns: [
            {"code": "005930", "name": "삼성전자", "price": 72000, "market_cap": "430조",
             "per": 12.5, "pbr": 1.2, "roe": 9.8},
            ...
        ]
        """
        try:
            sector_code, sector_name = self._get_sector_code(code)
            if not sector_code:
                print(f"[PeerAnalyzer] 업종 코드를 찾을 수 없음: {code}")
                return []

            url = (
                "https://finance.naver.com/sise/sise_group_detail.naver"
                f"?type=upjong&no={sector_code}"
            )
            res = self.session.get(url, timeout=10)
            res.raise_for_status()
            res.encoding = "euc-kr"
            soup = BeautifulSoup(res.text, "lxml")

            # 업종 종목 테이블 파싱
            peers = []
            table = soup.select_one("table.type_5")
            if not table:
                print(f"[PeerAnalyzer] 업종 테이블을 찾을 수 없음: sector={sector_code}")
                return []

            rows = table.select("tr")
            for row in rows:
                cols = row.select("td")
                if len(cols) < 4:
                    continue

                # 종목명/코드 링크
                name_tag = cols[0].select_one("a")
                if not name_tag:
                    continue

                name = name_tag.get_text(strip=True)
                href = name_tag.get("href", "")
                m = re.search(r"code=(\d{6})", href)
                if not m:
                    continue
                peer_code = m.group(1)

                price_text = cols[1].get_text(strip=True)
                price = self._parse_number(price_text)

                # 시가총액은 테이블에 없으므로 빈 값으로 초기화; 개별 조회로 보완
                peers.append({
                    "code": peer_code,
                    "name": name,
                    "price": price,
                    "market_cap": "",
                    "per": None,
                    "pbr": None,
                    "roe": None,
                })

                if len(peers) >= limit:
                    break

            # 각 종목의 PER/PBR/ROE 및 시가총액을 개별 페이지에서 보완
            enriched = []
            for peer in peers:
                detailed = self._fetch_stock_metrics(peer["code"])
                peer.update(detailed)
                enriched.append(peer)
                time.sleep(0.15)  # 네이버 요청 간격

            return enriched

        except Exception as e:
            print(f"[PeerAnalyzer] Error: {e}")
            return []

    def compare_metrics(self, code: str, peers: list = None) -> dict:
        """지표별 순위/백분위 비교

        peers가 None이면 get_sector_peers 자동 호출.

        Returns: {
            "target": {"code": str, "name": str, ...metrics},
            "peer_count": int,
            "metrics": {
                "per": {"value": float, "rank": int, "percentile": float, "sector_avg": float},
                "pbr": {"value": float, "rank": int, "percentile": float, "sector_avg": float},
                "roe": {"value": float, "rank": int, "percentile": float, "sector_avg": float},
                "operating_margin": {"value": float, "rank": int, "percentile": float, "sector_avg": float},
                "market_cap": {"value": str, "rank": int}
            },
            "position": str  # "상위" / "중위" / "하위"
        }
        """
        try:
            if peers is None:
                peers = self.get_sector_peers(code, limit=15)

            # 대상 종목 지표 조회
            target_metrics = self._fetch_stock_metrics(code)
            target_name = self._fetch_stock_name(code)
            target = {"code": code, "name": target_name, **target_metrics}

            if not peers:
                return {
                    "target": target,
                    "peer_count": 0,
                    "metrics": {},
                    "position": "N/A",
                }

            # 동일 업종 전체 = 대상 + 피어 (중복 제거)
            all_stocks = [target] + [p for p in peers if p["code"] != code]
            peer_count = len(all_stocks)

            result_metrics = {}

            # PER — 낮을수록 좋음 (적자 제외)
            result_metrics["per"] = self._rank_metric(
                target, all_stocks, "per", lower_is_better=True, exclude_negative=True
            )

            # PBR — 낮을수록 좋음 (음수 제외)
            result_metrics["pbr"] = self._rank_metric(
                target, all_stocks, "pbr", lower_is_better=True, exclude_negative=True
            )

            # ROE — 높을수록 좋음
            result_metrics["roe"] = self._rank_metric(
                target, all_stocks, "roe", lower_is_better=False, exclude_negative=False
            )

            # 영업이익률 — 높을수록 좋음
            result_metrics["operating_margin"] = self._rank_metric(
                target, all_stocks, "operating_margin", lower_is_better=False, exclude_negative=False
            )

            # 시가총액 — 단순 순위만 제공 (문자열 값이므로 숫자 변환 필요)
            result_metrics["market_cap"] = self._rank_market_cap(target, all_stocks)

            # 종합 포지션: 주요 지표 평균 백분위로 판단
            position = self._determine_position(result_metrics)

            return {
                "target": target,
                "peer_count": peer_count,
                "metrics": result_metrics,
                "position": position,
            }

        except Exception as e:
            print(f"[PeerAnalyzer] Error: {e}")
            return {}

    # ────────────────────── Private Helpers ──────────────────────

    def _get_sector_code(self, code: str) -> tuple:
        """종목 코드에서 업종 코드 추출
        Returns: (sector_code, sector_name)
        """
        try:
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            res = self.session.get(url, timeout=10)
            res.raise_for_status()
            res.encoding = "euc-kr"
            soup = BeautifulSoup(res.text, "lxml")

            # 업종 링크: /sise/sise_group_detail.naver?type=upjong&no=XXX
            sector_link = soup.select_one(
                "a[href*='sise_group_detail.naver?type=upjong']"
            )
            if not sector_link:
                return (None, None)

            href = sector_link.get("href", "")
            m = re.search(r"no=(\d+)", href)
            if not m:
                return (None, None)

            sector_code = m.group(1)
            sector_name = sector_link.get_text(strip=True)
            return (sector_code, sector_name)

        except Exception as e:
            print(f"[PeerAnalyzer] Error: {e}")
            return (None, None)

    def _fetch_stock_metrics(self, code: str) -> dict:
        """네이버 금융 종목 메인 페이지에서 PER/PBR/ROE/영업이익률/시가총액 추출"""
        defaults = {
            "market_cap": "",
            "per": None,
            "pbr": None,
            "roe": None,
            "operating_margin": None,
        }
        try:
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            res = self.session.get(url, timeout=10)
            res.raise_for_status()
            res.encoding = "euc-kr"
            soup = BeautifulSoup(res.text, "lxml")

            result = dict(defaults)

            # ── 시가총액 ──
            market_cap_tag = soup.select_one("em#_market_sum")
            if market_cap_tag:
                result["market_cap"] = market_cap_tag.get_text(strip=True)

            # ── 투자지표 테이블 (PER, PBR, ROE) ──
            # 네이버 금융 메인의 투자정보 section
            invest_table = soup.select_one("table.tb_type1_ifrs")
            if not invest_table:
                invest_table = soup.select_one("table.tb_type1")

            if invest_table:
                rows = invest_table.select("tr")
                for row in rows:
                    th = row.select_one("th")
                    td_list = row.select("td")
                    if not th or not td_list:
                        continue
                    label = th.get_text(strip=True)
                    # 첫 번째 TD가 최신 실적 값
                    val_text = td_list[0].get_text(strip=True) if td_list else ""
                    val = self._parse_number(val_text)

                    if "PER" in label:
                        result["per"] = val
                    elif "PBR" in label:
                        result["pbr"] = val
                    elif "ROE" in label:
                        result["roe"] = val

            # ── 영업이익률: 네이버 금융 실적 탭 별도 파싱 ──
            result["operating_margin"] = self._fetch_operating_margin(code, soup)

            return result

        except Exception as e:
            print(f"[PeerAnalyzer] Error: {e}")
            return defaults

    def _fetch_operating_margin(self, code: str, soup: BeautifulSoup):
        """영업이익률 추출 — 네이버 금융 메인 페이지 실적 테이블에서 시도"""
        try:
            # 네이버 금융 종목 메인의 실적 요약 테이블
            # 영업이익률 행을 찾아 가장 최근 값 반환
            tables = soup.select("table.tb_type1_ifrs, table.tb_type1")
            for table in tables:
                rows = table.select("tr")
                for row in rows:
                    th = row.select_one("th")
                    if not th:
                        continue
                    label = th.get_text(strip=True)
                    if "영업이익률" in label or "영업이익" in label and "%" in label:
                        tds = row.select("td")
                        for td in tds:
                            val = self._parse_number(td.get_text(strip=True))
                            if val is not None:
                                return val
            return None
        except Exception:
            return None

    def _fetch_stock_name(self, code: str) -> str:
        """종목명 조회"""
        try:
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            res = self.session.get(url, timeout=10)
            res.raise_for_status()
            res.encoding = "euc-kr"
            soup = BeautifulSoup(res.text, "lxml")
            name_tag = soup.select_one("div.wrap_company h2 a")
            if name_tag:
                return name_tag.get_text(strip=True)
            # fallback
            title_tag = soup.select_one("title")
            if title_tag:
                return title_tag.get_text(strip=True).split(":")[0].strip()
            return code
        except Exception as e:
            print(f"[PeerAnalyzer] Error: {e}")
            return code

    def _rank_metric(
        self,
        target: dict,
        all_stocks: list,
        metric: str,
        lower_is_better: bool,
        exclude_negative: bool,
    ) -> dict:
        """지표별 순위/백분위/평균 계산

        - lower_is_better: True면 낮은 값이 1위
        - exclude_negative: True면 음수/None 제외 후 비교
        """
        target_val = target.get(metric)

        # 유효 값 목록 (None/NaN 제외)
        valid_vals = []
        for s in all_stocks:
            v = s.get(metric)
            if v is None:
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if exclude_negative and v < 0:
                continue
            valid_vals.append(v)

        sector_avg = (sum(valid_vals) / len(valid_vals)) if valid_vals else None

        # 대상 값이 없거나 유효하지 않으면 순위 계산 불가
        if target_val is None:
            return {
                "value": None,
                "rank": None,
                "percentile": None,
                "sector_avg": sector_avg,
            }

        try:
            target_val = float(target_val)
        except (TypeError, ValueError):
            return {
                "value": None,
                "rank": None,
                "percentile": None,
                "sector_avg": sector_avg,
            }

        if exclude_negative and target_val < 0:
            return {
                "value": target_val,
                "rank": None,
                "percentile": None,
                "sector_avg": sector_avg,
            }

        # 순위: 비교 대상에서 몇 번째인지
        if lower_is_better:
            rank = sum(1 for v in valid_vals if v < target_val) + 1
        else:
            rank = sum(1 for v in valid_vals if v > target_val) + 1

        total = len(valid_vals)
        # 백분위: 100 = 최상위 (1등)
        percentile = round((1 - (rank - 1) / max(total, 1)) * 100, 1) if total > 0 else None

        return {
            "value": target_val,
            "rank": rank,
            "percentile": percentile,
            "sector_avg": round(sector_avg, 2) if sector_avg is not None else None,
        }

    def _rank_market_cap(self, target: dict, all_stocks: list) -> dict:
        """시가총액 순위 (문자열 → 숫자 변환 후 내림차순)"""
        def cap_to_number(cap_str: str) -> float:
            """'430조', '1,200억' 등을 float으로 변환"""
            if not cap_str:
                return 0.0
            cap_str = cap_str.replace(",", "").strip()
            m = re.search(r"([\d.]+)\s*조", cap_str)
            if m:
                return float(m.group(1)) * 1_000_000_000_000
            m = re.search(r"([\d.]+)\s*억", cap_str)
            if m:
                return float(m.group(1)) * 100_000_000
            try:
                return float(re.sub(r"[^\d.]", "", cap_str))
            except ValueError:
                return 0.0

        target_cap_num = cap_to_number(target.get("market_cap", ""))
        all_cap_nums = [cap_to_number(s.get("market_cap", "")) for s in all_stocks]

        # 시가총액 높을수록 좋은 순위
        rank = sum(1 for v in all_cap_nums if v > target_cap_num) + 1

        return {
            "value": target.get("market_cap", ""),
            "rank": rank,
        }

    def _determine_position(self, metrics: dict) -> str:
        """주요 지표 평균 백분위로 종합 포지션 결정
        상위 33% → "상위", 중간 33% → "중위", 하위 33% → "하위"
        """
        percentiles = []
        for key in ("per", "pbr", "roe", "operating_margin"):
            m = metrics.get(key, {})
            if m and m.get("percentile") is not None:
                percentiles.append(m["percentile"])

        if not percentiles:
            return "N/A"

        avg_pct = sum(percentiles) / len(percentiles)
        if avg_pct >= 67:
            return "상위"
        elif avg_pct >= 34:
            return "중위"
        else:
            return "하위"

    def _parse_number(self, text: str):
        """숫자 파싱 — 콤마/공백 제거 후 float 변환. 변환 불가 시 None 반환"""
        if not text:
            return None
        cleaned = text.replace(",", "").replace(" ", "").strip()
        # N/A, -, -- 등 처리
        if cleaned in ("", "-", "--", "N/A", "n/a", "해당없음"):
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
