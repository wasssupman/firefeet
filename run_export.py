"""
각 분석 기능을 개별적으로 디스코드에 익스포트하는 CLI 도구.

사용법:
  python3 run_export.py macro      # 글로벌 시장 브리핑
  python3 run_export.py watchlist   # 관심 종목 리포트
  python3 run_export.py reddit      # Reddit 감성 분석
  python3 run_export.py all         # 전체 리포트
  python3 run_export.py deep 005930 삼성전자  # AI 딥 리서치
"""
import sys
import yaml

from core.encoding_setup import setup_utf8_stdout
setup_utf8_stdout()

from core.discord_client import DiscordClient


def export_macro():
    """글로벌 거시 지표 → 디스코드"""
    from core.analysis.macro import MacroAnalyzer
    print("🌍 글로벌 시장 브리핑 생성 중...")
    ma = MacroAnalyzer()
    report = ma.generate_report_section()
    print(report)
    print()

    discord = DiscordClient()
    discord.send(report)
    print("✅ 디스코드 전송 완료!")


def export_watchlist():
    """관심 종목 리포트 → 디스코드"""
    from core.config_loader import ConfigLoader
    from core.kis_auth import KISAuth
    from core.providers.kis_api import KISManager
    from core.analysis.supply import SupplyAnalyzer
    from core.analysis.technical import VolatilityBreakoutStrategy
    from core.report_generator import ReportGenerator

    print("📊 관심 종목 리포트 생성 중...")

    # 관심 종목 로드
    try:
        with open("config/watchlist.yaml", 'r', encoding='utf-8') as f:
            watchlist = yaml.safe_load(f).get("watchlist", [])
    except FileNotFoundError:
        watchlist = [{"code": "005930", "name": "삼성전자"}]

    loader = ConfigLoader()
    config = loader.get_kis_config(mode="REAL")
    account_info = loader.get_account_info()

    auth = KISAuth(config)
    manager = KISManager(auth, account_info, mode="REAL")
    supply_analyzer = SupplyAnalyzer(auth)
    strategy = VolatilityBreakoutStrategy()

    generator = ReportGenerator(manager, supply_analyzer, strategy)
    report = generator.generate_full_report(watchlist, include_macro=False)
    print(report)
    print()

    discord = DiscordClient()
    discord.send(report)
    print("✅ 디스코드 전송 완료!")


def export_reddit():
    """Reddit 감성 분석 → 디스코드"""
    from core.config_loader import ConfigLoader

    print("🗣️ Reddit 감성 분석 중...")

    try:
        loader = ConfigLoader()
        config = loader.load_config()
        reddit_cfg = config.get("REDDIT", {})

        if not reddit_cfg.get("CLIENT_ID"):
            print("⚠️  config/secrets.yaml에 REDDIT 설정이 없습니다.")
            print("   REDDIT:")
            print('     CLIENT_ID: "your_id"')
            print('     CLIENT_SECRET: "your_secret"')
            return

        from core.reddit_analyzer import RedditAnalyzer
        analyzer = RedditAnalyzer(
            client_id=reddit_cfg["CLIENT_ID"],
            client_secret=reddit_cfg["CLIENT_SECRET"],
        )
        report = analyzer.generate_report_section()
        print(report)
        print()

        discord = DiscordClient()
        discord.send(report)
        print("✅ 디스코드 전송 완료!")

    except Exception as e:
        print(f"❌ Reddit 분석 실패: {e}")


def export_all():
    """전체 리포트 (매크로 + 종목 + Reddit) → 디스코드"""
    from core.config_loader import ConfigLoader
    from core.kis_auth import KISAuth
    from core.providers.kis_api import KISManager
    from core.analysis.supply import SupplyAnalyzer
    from core.analysis.technical import VolatilityBreakoutStrategy
    from core.report_generator import ReportGenerator
    from core.analysis.macro import MacroAnalyzer
    from core.econ_calendar import EconCalendar

    print("📝 전체 리포트 생성 중...")

    try:
        with open("config/watchlist.yaml", 'r', encoding='utf-8') as f:
            watchlist = yaml.safe_load(f).get("watchlist", [])
    except FileNotFoundError:
        watchlist = [{"code": "005930", "name": "삼성전자"}]

    loader = ConfigLoader()
    config = loader.get_kis_config(mode="REAL")
    account_info = loader.get_account_info()

    auth = KISAuth(config)
    manager = KISManager(auth, account_info, mode="REAL")
    supply_analyzer = SupplyAnalyzer(auth)
    strategy = VolatilityBreakoutStrategy()
    macro_analyzer = MacroAnalyzer()
    econ_calendar = EconCalendar()

    generator = ReportGenerator(manager, supply_analyzer, strategy, macro_analyzer, econ_calendar)
    report = generator.generate_full_report(watchlist, include_macro=True)

    # Reddit 추가 (선택적)
    try:
        reddit_cfg = loader.load_config().get("REDDIT", {})
        if reddit_cfg.get("CLIENT_ID"):
            from core.reddit_analyzer import RedditAnalyzer
            ra = RedditAnalyzer(reddit_cfg["CLIENT_ID"], reddit_cfg["CLIENT_SECRET"])
            report += "\n\n---\n\n" + ra.generate_report_section()
    except Exception:
        pass

    print(report)
    print()

    discord = DiscordClient()
    discord.send(report)
    print("✅ 디스코드 전송 완료!")


def export_econ():
    """주요 경제 지표 일정 및 분석 → 디스코드"""
    from core.econ_calendar import EconCalendar
    print("📅 경제 지표 일정 및 분석 중...")
    ec = EconCalendar()
    report = ec.generate_report_section()
    print(report)
    print()

    discord = DiscordClient()
    discord.send(report)
    print("✅ 디스코드 전송 완료!")


def export_chat():
    """AI 에이전트 분석 (Claude) → 디스코드"""
    from core.config_loader import ConfigLoader
    from core.kis_auth import KISAuth
    from core.stock_agent import StockAgent

    if len(sys.argv) < 3:
        print("사용법: python3 run_export.py chat <stock_code> [stock_name]")
        return

    code = sys.argv[2]
    name = sys.argv[3] if len(sys.argv) > 3 else code

    print(f"🤖 AI 에이전트({name}) 분석 중...")

    try:
        loader = ConfigLoader()
        config = loader.get_kis_config(mode="REAL")
        auth = KISAuth(config)
        agent = StockAgent(auth, loader)

        report = agent.analyze(code, name)
        print(report)
        print()

        discord = DiscordClient()
        discord.send(report)
        print("✅ 디스코드 전송 완료!")
    except Exception as e:
        print(f"❌ AI 분석 실패: {e}")


def export_deep():
    """AI 딥 리서치 (장기투자 종목 분석) → 디스코드 + 파일"""
    from run_deep_analysis import run_single

    if len(sys.argv) < 3:
        print("사용법: python3 run_export.py deep <stock_code> [stock_name]")
        return

    code = sys.argv[2]
    name = sys.argv[3] if len(sys.argv) > 3 else code

    print(f"🔬 딥 리서치({name}) 분석 중...")
    try:
        run_single(code, name)
    except Exception as e:
        print(f"❌ 딥 리서치 실패: {e}")


COMMANDS = {
    "macro": export_macro,
    "watchlist": export_watchlist,
    "reddit": export_reddit,
    "econ": export_econ,
    "all": export_all,
    "chat": export_chat,
    "deep": export_deep,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("사용법: python3 run_export.py <command>")
        print()
        print("Commands:")
        print("  macro      글로벌 시장 브리핑 (나스닥/S&P/다우/환율/VIX)")
        print("  watchlist   관심 종목 분석 리포트")
        print("  reddit      Reddit 커뮤니티 감성 분석")
        print("  econ        주요 경제 지표 일정 및 결과 분석")
        print("  all         전체 리포트 (매크로 + 종목 + Reddit + 경제)")
        print("  chat        Claude 기반 AI 에이전트 종합 분석 (Usage: chat <코드> [이름])")
        print("  deep        AI 딥 리서치 장기투자 분석 (Usage: deep <코드> [이름])")
        sys.exit(1)

    COMMANDS[sys.argv[1]]()
