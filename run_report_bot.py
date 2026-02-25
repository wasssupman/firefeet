"""
Firefeet 정기 리포트 데몬
특정 시간에 자동으로 각 분석 기능을 실행하고 디스코드로 전송합니다.

스케줄:
  08:00  글로벌 시장 브리핑 (MacroAnalyzer)
  08:30  관심 종목 프리마켓 분석 (ReportGenerator)
  12:00  Reddit 감성 분석 (RedditAnalyzer)
  15:40  장 마감 종합 리포트 (All)
  SUN 20:00  주간 리포트 (All)

사용법:
  python3 run_report_bot.py          # 데몬 모드 (대기)
  python3 run_report_bot.py --now    # 즉시 전체 리포트 1회 실행
"""
import datetime
import schedule
import yaml
import sys
import time

from core.encoding_setup import setup_utf8_stdout
setup_utf8_stdout()

from core.config_loader import ConfigLoader
from core.kis_auth import KISAuth
from core.providers.kis_api import KISManager
from core.analysis.supply import SupplyAnalyzer
from core.analysis.technical import VolatilityBreakoutStrategy
from core.report_generator import ReportGenerator
from core.analysis.macro import MacroAnalyzer
from core.econ_calendar import EconCalendar
from core.discord_client import DiscordClient


# ──────────────────────────── 유틸리티 ────────────────────────────

def load_watchlist(path="config/watchlist.yaml"):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f).get("watchlist", [])
    except FileNotFoundError:
        return [{"code": "005930", "name": "삼성전자"}]


def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")


# ──────────────────────────── 개별 작업 ────────────────────────────

def job_macro():
    """🌍 글로벌 시장 브리핑"""
    log("🌍 글로벌 시장 브리핑 시작")
    try:
        ma = MacroAnalyzer()
        report = ma.generate_report_section()
        DiscordClient().send(report)
        log("🌍 글로벌 시장 브리핑 전송 완료 ✅")
    except Exception as e:
        log(f"🌍 브리핑 실패: {e}")


def job_econ():
    """📅 경제 지표 일정 및 결과 분석"""
    log("📅 경제 지표 일정 분석 시작")
    try:
        ec = EconCalendar()
        report = ec.generate_report_section()
        DiscordClient().send(report)
        log("📅 경제 지표 전송 완료 ✅")
    except Exception as e:
        log(f"📅 경제 지표 실패: {e}")


def job_watchlist():
    """📊 관심 종목 분석"""
    log("📊 관심 종목 분석 시작")
    try:
        loader = ConfigLoader()
        config = loader.get_kis_config(mode="REAL")
        account_info = loader.get_account_info()

        auth = KISAuth(config)
        manager = KISManager(auth, account_info, mode="REAL")
        supply = SupplyAnalyzer()
        strategy = VolatilityBreakoutStrategy()

        generator = ReportGenerator(strategy, supply_analyzer=supply)
        watchlist = load_watchlist()

        def data_provider(code):
            ohlc = manager.get_daily_ohlc(code)
            time.sleep(0.5)
            investor_trend = manager.get_investor_trend(code)
            time.sleep(0.5)
            current_data = manager.get_current_price(code)
            return ohlc, investor_trend, current_data

        report = generator.generate_full_report(watchlist, data_provider_fn=data_provider, include_macro=False)
        DiscordClient().send(report)
        log("📊 관심 종목 분석 전송 완료 ✅")
    except Exception as e:
        log(f"📊 종목 분석 실패: {e}")


def job_reddit():
    """🗣️ Reddit 감성 분석"""
    log("🗣️ Reddit 감성 분석 시작")
    try:
        loader = ConfigLoader()
        config = loader.load_config()
        reddit_cfg = config.get("REDDIT", {})

        if not reddit_cfg.get("CLIENT_ID"):
            log("🗣️ Reddit API 키 미설정 — 건너뜀")
            return

        from core.reddit_analyzer import RedditAnalyzer
        analyzer = RedditAnalyzer(
            client_id=reddit_cfg["CLIENT_ID"],
            client_secret=reddit_cfg["CLIENT_SECRET"],
        )
        report = analyzer.generate_report_section()
        DiscordClient().send(report)
        log("🗣️ Reddit 감성 분석 전송 완료 ✅")
    except Exception as e:
        log(f"🗣️ Reddit 분석 실패: {e}")


def job_full_report():
    """📝 종합 리포트 (매크로 + 경제 + 종목 + Reddit)"""
    log("📝 종합 리포트 시작")
    try:
        # 매크로
        ma = MacroAnalyzer()
        # 경제
        ec = EconCalendar()

        # KIS
        loader = ConfigLoader()
        config = loader.get_kis_config(mode="REAL")
        account_info = loader.get_account_info()

        auth = KISAuth(config)
        manager = KISManager(auth, account_info, mode="REAL")
        supply = SupplyAnalyzer()
        strategy = VolatilityBreakoutStrategy()

        generator = ReportGenerator(strategy, supply_analyzer=supply, macro_analyzer=ma, econ_calendar=ec)
        watchlist = load_watchlist()

        def data_provider(code):
            ohlc = manager.get_daily_ohlc(code)
            time.sleep(0.5)
            investor_trend = manager.get_investor_trend(code)
            time.sleep(0.5)
            current_data = manager.get_current_price(code)
            return ohlc, investor_trend, current_data

        report = generator.generate_full_report(watchlist, data_provider_fn=data_provider, include_macro=True)

        # Reddit (선택적)
# ... (rest stays same)
        try:
            reddit_cfg = loader.load_config().get("REDDIT", {})
            if reddit_cfg.get("CLIENT_ID"):
                from core.reddit_analyzer import RedditAnalyzer
                ra = RedditAnalyzer(reddit_cfg["CLIENT_ID"], reddit_cfg["CLIENT_SECRET"])
                report += "\n\n---\n\n" + ra.generate_report_section()
        except Exception:
            pass

        DiscordClient().send(report)
        log("📝 종합 리포트 전송 완료 ✅")
    except Exception as e:
        log(f"📝 종합 리포트 실패: {e}")


# ──────────────────────────── 스케줄러 ────────────────────────────

def register_schedules():
    """시간대별 스케줄 등록"""
    # 장 시작 전
    schedule.every().day.at("08:00").do(job_macro)
    schedule.every().day.at("08:15").do(job_econ)
    schedule.every().day.at("08:30").do(job_watchlist)

    # 점심 시간
    schedule.every().day.at("12:00").do(job_reddit)

    # 장 마감 후
    schedule.every().day.at("15:40").do(job_full_report)

    # 주간 리포트 (일욕일)
    schedule.every().sunday.at("20:00").do(job_full_report)


def print_status():
    print("=" * 50)
    print("🚀 Firefeet Report Daemon")
    print(f"⏰ 현재 시간: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    print()
    print("📅 등록된 스케줄:")
    print("  08:00  🌍 글로벌 시장 브리핑 (나스닥/S&P/다우/환율/VIX)")
    print("  08:30  📊 관심 종목 프리마켓 분석")
    print("  12:00  🗣️ Reddit 해외 커뮤니티 감성 분석")
    print("  15:40  📝 장 마감 종합 리포트")
    print("  SUN    📝 주간 종합 리포트")
    print()
    print("대기 중... (Ctrl+C로 종료)")
    print()


if __name__ == "__main__":
    # --now 옵션: 즉시 실행
    if "--now" in sys.argv:
        job_full_report()
        sys.exit(0)

    # 데몬 모드
    register_schedules()
    print_status()

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n👋 Report Daemon 종료")
