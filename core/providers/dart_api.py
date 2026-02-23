"""
core/providers/dart_api.py

DART (전자공시시스템) 실시간 공시 파서.
OpenDART API를 주기적으로 폴링하여 신규 공시를 감지하고
LLM에게 호재/악재 분류를 요청한 뒤 이벤트 핸들러에 전달합니다.
"""

import os
import time
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Callable, Optional
from core.config_loader import ConfigLoader

logger = logging.getLogger("DartAPI")

DART_RSS_URL = "https://opendart.fss.or.kr/api/list.xml"

# 이벤트 레벨 공시 키워드 (호재/악재 분류용 선행 필터)
HIGH_PRIORITY_KEYWORDS_BUY = [
    "단일판매", "공급계약체결", "수주", "합병", "피합병",
    "자기주식 취득", "전환사채", "특허", "무상증자",
]
HIGH_PRIORITY_KEYWORDS_SELL = [
    "유상증자", "횡령", "배임", "부도", "관리종목",
    "상장폐지", "영업정지", "투자주의", "감사의견",
]


class DartAnnouncement:
    """단일 공시 데이터 모델"""
    def __init__(self, corp_code: str, corp_name: str, report_nm: str,
                 rcept_no: str, rcept_dt: str, url: str):
        self.corp_code = corp_code
        self.corp_name = corp_name
        self.report_nm = report_nm
        self.rcept_no = rcept_no
        self.rcept_dt = rcept_dt
        self.url = url

    def __repr__(self):
        return f"[{self.corp_name}] {self.report_nm} ({self.rcept_dt})"


class DartAPIClient:
    """
    DART 공시 실시간 폴링 클라이언트.
    
    Usage:
        dart = DartAPIClient(api_key="YOUR_KEY")
        dart.start_polling(on_new_announcement=my_handler, interval_sec=30)
    """

    def __init__(self, api_key: Optional[str] = None, poll_interval_sec: int = 30):
        # Prefer explicitly passed key, then secrets.yaml, then env var
        if not api_key:
            try:
                secrets = ConfigLoader().load_config()
                api_key = secrets.get("DART_API_KEY", "")
            except Exception:
                api_key = os.environ.get("DART_API_KEY", "")
        self.api_key = api_key
        self.poll_interval = poll_interval_sec
        self._seen: set = set()
        self._running = False

    def fetch_recent_announcements(self, days_back: int = 1) -> list[DartAnnouncement]:
        """오늘 또는 최근 N일 이내의 공시 목록을 조회합니다."""
        if not self.api_key:
            logger.warning("DART_API_KEY 미설정 — 실제 API 호출 불가.")
            return []

        today = datetime.now()
        bgn_date = (today - timedelta(days=days_back)).strftime("%Y%m%d")
        end_date = today.strftime("%Y%m%d")

        params = {
            "crtfc_key": self.api_key,
            "bgn_de": bgn_date,
            "end_de": end_date,
            "page_count": "100",
            "sort": "date",
            "sort_mth": "desc",
        }

        try:
            resp = requests.get(DART_RSS_URL, params=params, timeout=10)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            announcements = []
            for item in root.findall(".//list"):
                a = DartAnnouncement(
                    corp_code=item.findtext("corp_code", ""),
                    corp_name=item.findtext("corp_name", ""),
                    report_nm=item.findtext("report_nm", ""),
                    rcept_no=item.findtext("rcept_no", ""),
                    rcept_dt=item.findtext("rcept_dt", ""),
                    url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.findtext('rcept_no', '')}",
                )
                announcements.append(a)
            return announcements
        except Exception as e:
            logger.error(f"DART API 호출 오류: {e}")
            return []

    def quick_classify(self, report_nm: str) -> int:
        """
        LLM 없이 키워드 기반으로 공시 타입을 빠르게 분류합니다.
        Returns: +1 (호재), -1 (악재), 0 (중립)
        """
        for kw in HIGH_PRIORITY_KEYWORDS_SELL:
            if kw in report_nm:
                return -1
        for kw in HIGH_PRIORITY_KEYWORDS_BUY:
            if kw in report_nm:
                return +1
        return 0

    def start_polling(self, on_new_announcement: Callable[[DartAnnouncement, int], None],
                      interval_sec: Optional[int] = None):
        """
        백그라운드 루프로 새로운 공시를 감지하면 on_new_announcement(announcement, sentiment)를 호출합니다.
        sentiment: +1 호재, -1 악재, 0 중립
        
        Args:
            on_new_announcement: 콜백 함수 (DartAnnouncement, int) -> None
            interval_sec: 폴링 주기 (초). None 이면 초기화 시 설정값 사용.
        """
        interval = interval_sec or self.poll_interval
        self._running = True
        logger.info(f"DART 공시 폴링 시작 (주기: {interval}초)")

        # 초기 이미 존재하는 공시는 seen에 넣어 중복 트리거 방지
        for a in self.fetch_recent_announcements():
            self._seen.add(a.rcept_no)

        while self._running:
            time.sleep(interval)
            try:
                fresh = self.fetch_recent_announcements(days_back=1)
                for ann in fresh:
                    if ann.rcept_no not in self._seen:
                        self._seen.add(ann.rcept_no)
                        sentiment = self.quick_classify(ann.report_nm)
                        if sentiment != 0:  # 중립 공시는 무시
                            logger.info(f"신규 공시 감지! {ann} → sentiment={sentiment:+d}")
                            try:
                                on_new_announcement(ann, sentiment)
                            except Exception as cb_err:
                                logger.error(f"공시 핸들러 오류: {cb_err}")
            except Exception as e:
                logger.error(f"폴링 루프 오류: {e}")

    def stop(self):
        """Gracefully stop polling."""
        self._running = False
        logger.info("DART 공시 폴링 중지.")
