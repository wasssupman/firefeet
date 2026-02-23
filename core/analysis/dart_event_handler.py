"""
core/analysis/dart_event_handler.py

DART 공시 이벤트 핸들러.
DartAPIClient가 감지한 신규 공시를 받아 LLM으로 심층 분석 후
즉각적인 매매 액션(아직 인터페이스 정의 수준)을 결정합니다.
"""

import logging
import os
import subprocess
import json
from core.providers.dart_api import DartAnnouncement

logger = logging.getLogger("DartEventHandler")


class DartEventHandler:
    """
    DART 이벤트 라우터.
    
    핵심 역할:
    1. 등록된 보유 포지션 종목에 악재 공시가 뜨면 즉각 패닉셀 지시
    2. 호재 공시가 뜨면 스캘핑/스윙 큐에 추가
    """

    def __init__(self, trader=None, holdings: dict = None):
        """
        Args:
            trader: SwingTrader 인스턴스 (패닉셀 / 매수큐 연동용)
            holdings: fallback용 보유 종목 딕셔너리 {code: {'name': ..., 'qty': ...}}
        """
        self.trader = trader
        self.holdings = holdings or {}

    def on_announcement(self, ann: DartAnnouncement, sentiment: int):
        """
        DartAPIClient의 콜백으로 등록되는 진입점.
        
        Args:
            ann: DartAnnouncement 객체
            sentiment: +1 (호재), -1 (악재)
        """
        corp_code = ann.corp_code

        logger.info(f"[DartEventHandler] 공시 처리 시작: {ann} (sentiment={sentiment:+d})")

        # --- LLM 심층 분석 (호재/악재 세부 내용 파악) ---
        llm_result = self._llm_classify(ann)
        logger.info(f"[DartEventHandler] LLM 분류 결과: {llm_result}")

        action = llm_result.get("action", "IGNORE")
        reason = llm_result.get("reason", "")

        if action == "PANIC_SELL":
            # trader.portfolio 또는 self.holdings에서 보유 여부 확인
            trader_portfolio = getattr(self.trader, 'portfolio', {}) if self.trader else {}
            is_held = corp_code in self.holdings or corp_code in trader_portfolio
            if is_held:
                logger.critical(
                    f"🚨 PANIC SELL 발동! [{ann.corp_name}({corp_code})] — {reason}"
                )
                self._trigger_panic_sell(corp_code, ann.corp_name, reason)
            else:
                logger.info(f"[{ann.corp_name}] 악재 공시지만 보유 없음. 무시.")

        elif action == "WATCH_BUY":
            logger.info(
                f"✅ 호재 공시 감지! [{ann.corp_name}({corp_code})] → 매수 후보 등록. 이유: {reason}"
            )
            self._register_buy_candidate(corp_code, ann.corp_name, ann, reason)
        else:
            logger.info(f"[{ann.corp_name}] 액션 없음 (IGNORE). 이유: {reason}")

    def _llm_classify(self, ann: DartAnnouncement) -> dict:
        """
        Claude CLI를 통해 공시 내용을 심층 분류합니다.
        Returns: {"action": "PANIC_SELL"|"WATCH_BUY"|"IGNORE", "reason": "..."}
        """
        prompt = f"""한국 주식 자동매매 시스템의 리스크 관리자입니다.
아래 전자공시(DART) 내용을 분석해 매매 액션을 결정하세요.

[공시 정보]
- 기업명: {ann.corp_name}
- 공시 제목: {ann.report_nm}
- 공시 일시: {ann.rcept_dt}

판단 기준:
- PANIC_SELL: 유상증자(주주배정/일반공모), 횡령/배임, 부도, 관리종목 지정, 상장폐지 위기
- WATCH_BUY: 대규모 수주/계약(시총 5% 이상 추정), 특별 배당, 무상증자, 자사주 취득
- IGNORE: 실적 발표, 정기 공시, 소액 계약 등 영향 미미한 공시

반드시 아래 JSON 형식으로만 답하세요:
{{"action": "PANIC_SELL" 또는 "WATCH_BUY" 또는 "IGNORE", "reason": "핵심 사유 1문장"}}
"""
        try:
            env = os.environ.copy()
            env.pop("CLAUDECODE", None)
            result = subprocess.run(
                ["claude", "-p", "--output-format", "text"],
                input=prompt,
                capture_output=True, text=True, timeout=20, env=env
            )
            raw = result.stdout.strip()
            if "```" in raw:
                raw = raw.replace("```json", "").replace("```", "").strip()
            if "{" in raw:
                raw = raw[raw.find("{"):raw.rfind("}") + 1]
                return json.loads(raw)
        except Exception as e:
            logger.warning(f"LLM 공시 분류 실패: {e}")

        # 키워드 기반 폴백
        if any(k in ann.report_nm for k in ["유상증자", "횡령", "부도", "관리종목"]):
            return {"action": "PANIC_SELL", "reason": "키워드 기반 악재 판정 (LLM 불가)"}
        if any(k in ann.report_nm for k in ["수주", "계약체결", "무상증자"]):
            return {"action": "WATCH_BUY", "reason": "키워드 기반 호재 판정 (LLM 불가)"}
        return {"action": "IGNORE", "reason": "분류 불가 — 무시"}

    def _trigger_panic_sell(self, corp_code: str, corp_name: str, reason: str):
        """
        보유 포지션 즉각 청산 요청 — SwingTrader 연동.
        """
        logger.critical(
            f"🔴 DART PANIC SELL → {corp_name}({corp_code}) 전량 시장가 청산 요청\n"
            f"   사유: {reason}"
        )
        if self.trader:
            try:
                self.trader.emergency_sell_all(corp_code, reason=f"DART 악재: {reason}")
                logger.info(f"[{corp_name}] emergency_sell_all 호출 완료.")
            except AttributeError:
                logger.warning("SwingTrader에 emergency_sell_all 미구현 — 로그만 기록합니다.")
            except Exception as e:
                logger.error(f"패닉셀 실행 오류: {e}")

    def _register_buy_candidate(self, corp_code: str, corp_name: str,
                                ann: DartAnnouncement, reason: str):
        """
        스윙 봇의 target_codes에 DART 호재 종목을 우선 추가합니다.
        """
        logger.info(
            f"🟢 DART 매수 후보 등록 → {corp_name}({corp_code})\n"
            f"   공시: {ann.report_nm}\n"
            f"   사유: {reason}"
        )
        if self.trader:
            try:
                if corp_code not in self.trader.target_codes:
                    self.trader.target_codes.insert(0, corp_code)  # 최우선순위로 삽입
                    self.trader.stock_names[corp_code] = corp_name
                    logger.info(f"[{corp_name}({corp_code})] target_codes 최선두 등록 완료.")
            except Exception as e:
                logger.error(f"매수 후보 등록 오류: {e}")
