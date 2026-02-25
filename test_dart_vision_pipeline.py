"""
test_dart_vision_pipeline.py

DART 공시 감지 → Vision AI 차트 분석 → 최종 매매 판정 파이프라인 E2E 테스트.

사용법:
  python3 test_dart_vision_pipeline.py              # 목 공시로 테스트 (API 불필요)
  python3 test_dart_vision_pipeline.py --live       # 실제 DART API 폴링 1회
  python3 test_dart_vision_pipeline.py --code 005930  # 특정 종목 코드로 차트 분석
"""

import argparse
import logging
import time
import sys
from PIL import Image, ImageDraw
import io

from core.encoding_setup import setup_utf8_stdout
setup_utf8_stdout()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("Pipeline")


# ──────────────────────────────────────────────
# STEP 1: DART 공시 감지
# ──────────────────────────────────────────────

def step1_dart(live: bool = False) -> list:
    """DART에서 신규 호재 공시 감지. live=False면 목 데이터 사용."""
    from core.providers.dart_api import DartAPIClient, DartAnnouncement

    print("\n" + "="*60)
    print("📡 STEP 1: DART 공시 조회")
    print("="*60)

    if live:
        logger.info("실제 DART API 폴링 중...")
        dart = DartAPIClient()
        announcements = dart.fetch_recent_announcements(days_back=1)
        # 호재/악재만 필터
        results = []
        for ann in announcements:
            s = dart.quick_classify(ann.report_nm)
            if s != 0:
                results.append((ann, s))
                logger.info(f"  [{s:+d}] {ann.corp_name}: {ann.report_nm}")
        if not results:
            logger.info("  감지된 유의미 공시 없음 (주말/장 외 시간)")
    else:
        logger.info("목 공시 데이터 사용 (--live 플래그로 실제 API 호출 가능)")
        # 수주 공시 시뮬레이션
        mock_ann = DartAnnouncement(
            corp_code="005930",
            corp_name="삼성전자",
            report_nm="단일판매·공급계약체결",
            rcept_no="20260222999999",
            rcept_dt="20260222",
            url="https://dart.fss.or.kr"
        )
        results = [(mock_ann, +1)]  # +1 = 호재
        logger.info(f"  목 공시: {mock_ann}")

    print(f"  → 유의미 공시 {len(results)}건 감지됨")
    return results


# ──────────────────────────────────────────────
# STEP 2: LLM 공시 심층 분류
# ──────────────────────────────────────────────

def step2_classify(announcements: list) -> list:
    """Claude를 통해 공시를 PANIC_SELL / WATCH_BUY / IGNORE 분류."""
    from core.analysis.dart_event_handler import DartEventHandler

    print("\n" + "="*60)
    print("🧠 STEP 2: LLM 공시 심층 분류")
    print("="*60)

    handler = DartEventHandler()
    buy_targets = []

    for ann, sentiment in announcements:
        logger.info(f"  분류 중: {ann.corp_name} — {ann.report_nm}")
        result = handler._llm_classify(ann)
        action = result.get("action")
        reason = result.get("reason")
        logger.info(f"  → {action}: {reason}")

        if action == "WATCH_BUY":
            buy_targets.append((ann.corp_code, ann.corp_name, reason))
        elif action == "PANIC_SELL":
            logger.warning(f"  🔴 PANIC SELL 신호 — {ann.corp_name}")

    print(f"  → 매수 후보: {len(buy_targets)}건")
    return buy_targets


# ──────────────────────────────────────────────
# STEP 3: 차트 렌더링
# ──────────────────────────────────────────────

def step3_render_chart(code: str, name: str) -> bytes:
    """종목 캔들차트를 PNG 바이트로 렌더링."""
    print("\n" + "="*60)
    print(f"📊 STEP 3: 차트 렌더링 — {name}({code})")
    print("="*60)

    try:
        from utils.chart_renderer import render_chart_to_bytes
        logger.info("  KIS API에서 OHLCV 데이터 조회 중...")
        chart_bytes = render_chart_to_bytes(code, period_days=60)
        if chart_bytes:
            logger.info(f"  차트 렌더링 완료 ({len(chart_bytes):,} bytes)")
            return chart_bytes
        else:
            raise ValueError("OHLCV 데이터 없음")
    except Exception as e:
        logger.warning(f"  실제 차트 조회 실패 ({e}) → 더미 차트 사용")
        return _make_dummy_chart(name)


def _make_dummy_chart(name: str) -> bytes:
    """KIS API 없이도 테스트할 수 있도록 임의 차트 생성."""
    img = Image.new("RGB", (800, 400), color=(18, 18, 24))
    draw = ImageDraw.Draw(img)
    prices = [200, 215, 198, 235, 222, 258, 242, 272, 262, 285]
    for i in range(len(prices)-1):
        x1 = int(i * 800 / (len(prices)-1))
        y1 = 360 - int(prices[i] * 320 / 320)
        x2 = int((i+1) * 800 / (len(prices)-1))
        y2 = 360 - int(prices[i+1] * 320 / 320)
        draw.line([(x1, y1), (x2, y2)], fill=(100, 220, 120), width=2)
        cx = (x1+x2)//2
        color = (50, 180, 80) if prices[i+1] > prices[i] else (200, 60, 60)
        draw.rectangle([cx-7, min(y1,y2), cx+7, max(y1,y2)], fill=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    logger.info(f"  더미 차트 생성 완료")
    return buf.getvalue()


# ──────────────────────────────────────────────
# STEP 4: Vision AI 차트 분석
# ──────────────────────────────────────────────

def step4_vision(chart_bytes: bytes, code: str, name: str) -> dict:
    """Gemini 2.5 Flash Lite Vision API로 차트 패턴 분석."""
    from core.analysis.llms.vision_analyst import VisionAnalyst

    print("\n" + "="*60)
    print(f"👁️  STEP 4: Vision AI 차트 분석 — {name}({code})")
    print("="*60)

    v = VisionAnalyst()
    logger.info(f"  모델: {v.model_name}")

    t0 = time.time()
    result = v.validate(chart_bytes, code, name)
    elapsed = time.time() - t0

    logger.info(f"  응답 시간: {elapsed:.2f}s")
    logger.info(f"  action    : {result['action']}")
    logger.info(f"  confidence: {result['confidence']}%")
    logger.info(f"  risk_level: {result['risk_level']}")
    logger.info(f"  reason    : {result['reason']}")
    return result


# ──────────────────────────────────────────────
# STEP 5: 최종 판정
# ──────────────────────────────────────────────

def step5_final_decision(ann_reason: str, vision: dict, code: str, name: str):
    """DART 분류 + Vision 결과를 종합해 최종 액션 출력."""
    print("\n" + "="*60)
    print(f"⚡ STEP 5: 최종 판정 — {name}({code})")
    print("="*60)

    action = vision.get("action")
    confidence = vision.get("confidence", 0)
    risk = vision.get("risk_level", "UNKNOWN")

    if action == "CONFIRM" and confidence >= 60 and risk in ("LOW", "MEDIUM"):
        final = "✅ BUY 진입 승인"
        detail = f"DART 호재 공시 확인 + Vision AI 차트 안전 판정 ({confidence}% / {risk})"
    elif action == "REJECT":
        final = "🔴 BUY 기각"
        detail = f"Vision AI 차트 위험 판정으로 진입 차단 — {vision.get('reason')}"
    else:
        final = "⚠️  WAIT (조건 미충족)"
        detail = f"confidence 부족 ({confidence}%) 또는 high risk"

    print(f"\n  📌 DART 근거 : {ann_reason}")
    print(f"  📌 Vision 근거: {vision.get('reason')}")
    print(f"\n  🎯 최종 판정 : {final}")
    print(f"  📋 상세      : {detail}\n")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DART → Vision 파이프라인 테스트")
    parser.add_argument("--live", action="store_true", help="실제 DART API 폴링 사용")
    parser.add_argument("--code", default=None, help="특정 종목 코드 지정 (기본: 목 데이터 종목)")
    args = parser.parse_args()

    print("\n🚀 Firefeet DART → Vision Pipeline 테스트 시작")
    print(f"   모드: {'LIVE' if args.live else 'MOCK'}\n")

    t_start = time.time()

    # Step 1: DART 공시 감지
    announcements = step1_dart(live=args.live)
    if not announcements:
        print("\n⚠️  처리할 공시 없음. 종료.")
        sys.exit(0)

    # Step 2: LLM 분류
    buy_targets = step2_classify(announcements)
    if not buy_targets:
        print("\n⚠️  WATCH_BUY 대상 없음. 종료.")
        sys.exit(0)

    # 지정 코드가 있으면 해당 종목만, 없으면 첫 번째 호재 종목
    if args.code:
        targets = [(args.code, args.code, "CLI에서 직접 지정")]
    else:
        targets = buy_targets

    for code, name, dart_reason in targets[:1]:  # 첫 번째만 처리
        # Step 3: 차트 렌더링
        chart_bytes = step3_render_chart(code, name)

        # Step 4: Vision AI 분석
        vision_result = step4_vision(chart_bytes, code, name)

        # Step 5: 최종 판정
        step5_final_decision(dart_reason, vision_result, code, name)

    print(f"⏱️  총 소요 시간: {time.time()-t_start:.1f}s\n")


if __name__ == "__main__":
    main()
