"""
AI 딥 리서치 — 장기투자 종목 분석

사용법:
  python3 run_deep_analysis.py 005930 삼성전자
  python3 run_deep_analysis.py --watchlist
  python3 run_deep_analysis.py 005930 삼성전자 --sections financial,valuation
"""
import sys
import yaml
import time
from core.config_loader import ConfigLoader
from core.kis_auth import KISAuth
from core.providers.kis_api import KISManager
from core.deep_analysis.deep_agent import DeepAgent
from core.deep_analysis.report_builder import ReportBuilder
from core.discord_client import DiscordClient


def load_config():
    try:
        with open("config/deep_analysis.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def run_single(code: str, name: str, sections_filter: list = None):
    """단일 종목 딥 리서치"""
    config = load_config()
    agent = DeepAgent()
    builder = ReportBuilder(config)

    # Manager Initialization for Dependency Injection
    loader = ConfigLoader()
    kis_config = loader.get_kis_config(mode="REAL")
    account_info = loader.get_account_info()
    auth = KISAuth(kis_config)
    manager = KISManager(auth, account_info, mode="REAL")

    def data_provider(code):
        ohlc = manager.get_daily_ohlc(code)
        time.sleep(0.5)
        investor_trend = manager.get_investor_trend(code)
        time.sleep(0.5)
        current_data = manager.get_current_price(code)
        return ohlc, investor_trend, current_data

    # 분석 실행
    sections = agent.analyze(code, name, sections_filter, data_provider_fn=data_provider)

    # 리포트 조립
    report = builder.build(code, name, sections, model=agent.model)
    summary = builder.build_summary(code, name, sections)

    # 파일 저장
    output_cfg = config.get("output", {})
    if output_cfg.get("save_file", True):
        filepath = builder.save_to_file(report, code, name)
        print(f"📄 리포트 저장: {filepath}")

    # Discord 전송
    if output_cfg.get("discord_summary", True) or output_cfg.get("discord_full", False):
        try:
            discord = DiscordClient()
            send_full = output_cfg.get("discord_full", False)
            builder.send_to_discord(report, summary, discord, send_full=send_full)
            print("✅ 디스코드 전송 완료!")
        except Exception as e:
            print(f"⚠️ 디스코드 전송 실패: {e}")

    # 콘솔 출력
    print("\n" + "=" * 60)
    print(report)

    return report


def run_watchlist():
    """워치리스트 전체 종목 딥 리서치"""
    try:
        with open("config/watchlist.yaml", "r", encoding="utf-8") as f:
            watchlist = yaml.safe_load(f).get("watchlist", [])
    except FileNotFoundError:
        print("⚠️ config/watchlist.yaml 파일이 없습니다.")
        return

    if not watchlist:
        print("⚠️ 워치리스트가 비어 있습니다.")
        return

    print(f"📋 워치리스트 딥 리서치: {len(watchlist)}개 종목")
    for stock in watchlist:
        code = stock.get("code", "")
        name = stock.get("name", code)
        print(f"\n{'='*60}")
        print(f"🔍 {name}({code}) 분석 시작")
        print(f"{'='*60}")
        try:
            run_single(code, name)
        except Exception as e:
            print(f"❌ {name}({code}) 분석 실패: {e}")


def main():
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        sys.exit(1)

    # --watchlist 모드
    if "--watchlist" in args:
        run_watchlist()
        return

    # 단일 종목 모드
    if len(args) < 2 and not args[0].startswith("-"):
        print("사용법: python3 run_deep_analysis.py <종목코드> <종목명> [--sections a,b,c]")
        sys.exit(1)

    code = args[0]
    name = args[1] if len(args) > 1 else code

    # --sections 파싱
    sections_filter = None
    for i, arg in enumerate(args):
        if arg == "--sections" and i + 1 < len(args):
            sections_filter = [s.strip() for s in args[i + 1].split(",")]

    run_single(code, name, sections_filter)


if __name__ == "__main__":
    main()
