import os
import json
import time
import zipfile
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests
from core.config_loader import ConfigLoader


class DartClient:
    BASE_URL = "https://opendart.fss.or.kr/api"
    CACHE_DIR = ".cache/dart"
    CACHE_TTL = 86400  # 24시간

    def __init__(self, api_key: str = None):
        if api_key:
            self.api_key = api_key
        else:
            loader = ConfigLoader()
            try:
                config = loader.load_config()
                self.api_key = config.get("DART_API_KEY", "")
            except Exception as e:
                print(f"[DartClient] 설정 로드 실패: {e}")
                self.api_key = ""

        self.available = bool(self.api_key)
        if not self.available:
            print("[DartClient] DART_API_KEY not found — DART features disabled")

        os.makedirs(self.CACHE_DIR, exist_ok=True)
        self._corp_code_map = {}  # stock_code -> corp_code 매핑

    def get_corp_code(self, stock_code: str) -> str:
        """종목코드(6자리) → DART 고유번호 변환"""
        if not self.available:
            return None

        # 메모리 캐시 확인
        if self._corp_code_map:
            return self._corp_code_map.get(stock_code)

        # 디스크 캐시 확인
        cache_key = "corp_code_map"
        cached = self._get_cache(cache_key)
        if cached:
            self._corp_code_map = cached
            return self._corp_code_map.get(stock_code)

        # DART에서 ZIP 다운로드
        try:
            url = f"{self.BASE_URL}/corpCode.xml"
            params = {"crtfc_key": self.api_key}
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()

            # ZIP 파일 압축 해제
            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                xml_filename = next(
                    name for name in z.namelist() if name.upper() == "CORPCODE.XML"
                )
                with z.open(xml_filename) as f:
                    tree = ET.parse(f)

            root = tree.getroot()
            mapping = {}
            for item in root.findall("list"):
                code = item.findtext("stock_code", "").strip()
                corp = item.findtext("corp_code", "").strip()
                if code:
                    mapping[code] = corp

            self._corp_code_map = mapping
            self._set_cache(cache_key, mapping)
            return mapping.get(stock_code)

        except Exception as e:
            print(f"[DartClient] Error: {e}")
            return None

    def get_financial_statements(self, corp_code: str, year: str, report_code: str = "11011") -> dict:
        """재무제표 조회
        report_code: 11011(사업보고서), 11012(반기), 11013(1분기), 11014(3분기)
        """
        if not self.available or not corp_code:
            return {}

        cache_key = f"financial_{corp_code}_{year}_{report_code}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        try:
            data = self._api_get(
                "/fnlttSinglAcntAll.json",
                {
                    "corp_code": corp_code,
                    "bsns_year": year,
                    "reprt_code": report_code,
                    "fs_div": "CFS",  # 연결재무제표
                },
            )

            if not data or data.get("status") == "013":
                # 연결재무제표 없으면 별도재무제표 시도
                data = self._api_get(
                    "/fnlttSinglAcntAll.json",
                    {
                        "corp_code": corp_code,
                        "bsns_year": year,
                        "reprt_code": report_code,
                        "fs_div": "OFS",
                    },
                )

            if not data or data.get("status") != "000":
                return {}

            # 계정명 → {당기, 전기} 구조로 정리
            result = {}
            for item in data.get("list", []):
                account_nm = item.get("account_nm", "").strip()
                if not account_nm:
                    continue
                result[account_nm] = {
                    "this_year": item.get("thstrm_amount", ""),
                    "last_year": item.get("frmtrm_amount", ""),
                    "fs_div": item.get("fs_div", ""),
                    "sj_div": item.get("sj_div", ""),  # BS(재무상태표), IS(손익계산서) 등
                }

            self._set_cache(cache_key, result)
            return result

        except Exception as e:
            print(f"[DartClient] Error: {e}")
            return {}

    def get_recent_disclosures(self, corp_code: str, months: int = 6) -> list:
        """최근 N개월 공시 목록 조회"""
        if not self.available or not corp_code:
            return []

        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=months * 30)
        bgn_de = start_dt.strftime("%Y%m%d")
        end_de = end_dt.strftime("%Y%m%d")

        cache_key = f"disclosures_{corp_code}_{bgn_de}_{end_de}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        try:
            data = self._api_get(
                "/list.json",
                {
                    "corp_code": corp_code,
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                    "page_count": 20,
                },
            )

            if not data or data.get("status") not in ("000",):
                return []

            disclosures = []
            for item in data.get("list", []):
                disclosures.append(
                    {
                        "report_nm": item.get("report_nm", ""),
                        "rcept_no": item.get("rcept_no", ""),
                        "rcept_dt": item.get("rcept_dt", ""),
                        "flr_nm": item.get("flr_nm", ""),
                    }
                )

            self._set_cache(cache_key, disclosures)
            return disclosures

        except Exception as e:
            print(f"[DartClient] Error: {e}")
            return []

    def get_company_info(self, corp_code: str) -> dict:
        """기업 기본 정보 (설립일, 직원수, 대표이사 등)"""
        if not self.available or not corp_code:
            return {}

        cache_key = f"company_{corp_code}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        try:
            data = self._api_get("/company.json", {"corp_code": corp_code})

            if not data or data.get("status") != "000":
                return {}

            info = {
                "corp_name": data.get("corp_name", ""),
                "corp_name_eng": data.get("corp_name_eng", ""),
                "stock_name": data.get("stock_name", ""),
                "stock_code": data.get("stock_code", ""),
                "ceo_nm": data.get("ceo_nm", ""),
                "corp_cls": data.get("corp_cls", ""),  # Y(유가증권), K(코스닥) 등
                "jurir_no": data.get("jurir_no", ""),
                "bizr_no": data.get("bizr_no", ""),
                "adres": data.get("adres", ""),
                "hm_url": data.get("hm_url", ""),
                "phn_no": data.get("phn_no", ""),
                "est_dt": data.get("est_dt", ""),   # 설립일
                "acc_mt": data.get("acc_mt", ""),   # 결산월
            }

            self._set_cache(cache_key, info)
            return info

        except Exception as e:
            print(f"[DartClient] Error: {e}")
            return {}

    # ──────────────────── 캐시 헬퍼 ────────────────────

    def _get_cache(self, cache_key: str):
        """캐시 조회 (24시간 TTL)"""
        path = os.path.join(self.CACHE_DIR, f"{cache_key}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                entry = json.load(f)
            if time.time() - entry.get("ts", 0) > self.CACHE_TTL:
                return None
            return entry.get("data")
        except Exception:
            return None

    def _set_cache(self, cache_key: str, data):
        """캐시 저장"""
        path = os.path.join(self.CACHE_DIR, f"{cache_key}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "data": data}, f, ensure_ascii=False)
        except Exception as e:
            print(f"[DartClient] 캐시 저장 실패: {e}")

    def _api_get(self, endpoint: str, params: dict) -> dict:
        """DART API GET 요청 공통"""
        if not self.available:
            return {}
        try:
            params = dict(params)
            params["crtfc_key"] = self.api_key
            url = f"{self.BASE_URL}{endpoint}"
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[DartClient] Error: {e}")
            return {}
