import sys
import os
import yaml
import time
import datetime
import threading
import logging
import tempfile
from datetime import timezone, timedelta

from core.encoding_setup import setup_utf8_stdout
setup_utf8_stdout()

# ── 로깅 설정 ──────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)

# 에러 전용 파일 핸들러
_error_handler = logging.FileHandler("logs/swing_errors.log", encoding="utf-8")
_error_handler.setLevel(logging.WARNING)
_error_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))
logging.getLogger().addHandler(_error_handler)

# Claude Analyst 노이즈 억제
logging.getLogger("ClaudeAnalyst").setLevel(logging.WARNING)

# ── 중복 실행 방지 (PID 파일 락) ──────────────────────────
_PID_FILE = os.path.join(tempfile.gettempdir(), "firefeet_ai_swing.pid")

def _acquire_lock():
    """이미 실행 중인 프로세스가 있으면 종료."""
    if os.path.exists(_PID_FILE):
        with open(_PID_FILE, "r") as f:
            old_pid = f.read().strip()
        if old_pid:
            # 해당 PID가 실제 돌고 있는지 확인
            try:
                os.kill(int(old_pid), 0)  # signal 0 = 존재 확인만
                print(f"[Error] AI 스윙 봇(PID: {old_pid})이 이미 실행 중입니다.")
                sys.exit(1)
            except (ProcessLookupError, ValueError, OSError):
                pass  # 프로세스 없음 또는 Windows os.kill 미지원 → 락 해제 후 계속
    
    with open(_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

def _release_lock():
    """종료 시 PID 파일 제거."""
    if os.path.exists(_PID_FILE):
        os.remove(_PID_FILE)

_acquire_lock()

from core.config_loader import ConfigLoader
from core.kis_auth import KISAuth
from core.providers.kis_api import KISManager
from core.discord_client import DiscordClient
from core.execution.scanner import StockScanner
from core.analysis.scoring_engine import StockScreener
from core.analysis.market_temperature import MarketTemperature
from core.analysis.ai_swing_agent import AISwingAgent
from core.execution.swing_trader import SwingTrader
from core.news_scraper import NewsScraper

def is_market_hours():
    """한국 장 운영시간 여부 (09:00~15:20 KST, 주말 제외)"""
    KST = timezone(timedelta(hours=9))
    now = datetime.datetime.now(KST)
    if now.weekday() >= 5:
        return False
    market_start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    market_end = now.replace(hour=15, minute=20, second=0, microsecond=0)
    return market_start <= now <= market_end

def _startup_health_check():
    """봇 시작 전 필수 의존성 점검"""
    import subprocess

    errors = []
    warnings = []

    # 1. Claude CLI 사용 가능 여부
    try:
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=10,
            env=env, encoding="utf-8", errors="replace"
        )
        if result.returncode != 0:
            warnings.append("Claude CLI가 설치되어 있지만 실행 불가")
    except FileNotFoundError:
        warnings.append("Claude CLI 미설치 — AI 분석이 API 전용 모드로 동작합니다")
    except subprocess.TimeoutExpired:
        warnings.append("Claude CLI 응답 없음")
    except Exception as e:
        warnings.append(f"Claude CLI 확인 실패: {e}")

    # 2. config 파일 존재 확인
    required_configs = [
        "config/secrets.yaml",
        "config/trading_settings.yaml",
    ]
    for cfg in required_configs:
        if not os.path.exists(cfg):
            errors.append(f"필수 설정 파일 누락: {cfg}")

    # 3. logs 디렉토리 쓰기 권한
    os.makedirs("logs", exist_ok=True)
    try:
        test_path = os.path.join("logs", ".health_check_test")
        with open(test_path, "w") as f:
            f.write("test")
        os.remove(test_path)
    except Exception as e:
        errors.append(f"logs/ 디렉토리 쓰기 불가: {e}")

    # 4. Discord webhook 확인 (선택)
    try:
        loader = ConfigLoader()
        secrets = loader.load_config()
        if not secrets.get("DISCORD_WEBHOOK_URL"):
            warnings.append("Discord Webhook URL 미설정 — 알림이 비활성화됩니다")
        if not secrets.get("ANTHROPIC_API_KEY") and not secrets.get("ANTHROPIC_API_KEY", ""):
            warnings.append("ANTHROPIC_API_KEY 미설정 — Claude CLI fallback 모드로 동작")
    except Exception as e:
        warnings.append(f"설정 파일 점검 중 오류: {e}")

    # 결과 출력
    if errors:
        print("\n" + "=" * 50)
        print("FATAL: 시작 불가")
        for err in errors:
            print(f"  [ERROR] {err}")
        print("=" * 50)
        _release_lock()
        sys.exit(1)

    if warnings:
        print("\n--- Health Check Warnings ---")
        for warn in warnings:
            print(f"  [WARN] {warn}")
        print("----------------------------\n")

    print("Health Check 통과.")


def main():
    print("🔥 Firefeet AI 스윙 봇 시동...")
    _startup_health_check()

    # Paper trading check
    is_paper = "--paper" in sys.argv
    if is_paper:
        print(">>> PAPER TRADING MODE ON <<<")
        
    loader = ConfigLoader()
    
    try:
        kis_config = loader.get_kis_config(mode="REAL" if not is_paper else "PAPER")
        account_info = loader.get_account_info(mode="REAL" if not is_paper else "PAPER")
    except Exception as e:
        print(f"설정 로드 실패: {e}")
        _release_lock()
        sys.exit(1)
        
    # ── 의존성 조립 (Dependency Injection) ──
    # 1. Data Provider
    auth = KISAuth(kis_config)
    manager = KISManager(auth, account_info, mode="REAL" if not is_paper else "PAPER")
    
    # 2. Helper Modules
    discord = DiscordClient() if not is_paper else None
    market_temp = MarketTemperature()
    news_scraper = NewsScraper()
    
    from core.analysis.technical import VolatilityBreakoutStrategy
    strategy = VolatilityBreakoutStrategy()
    
    # 3. AI Agent & Screener
    ai_agent = AISwingAgent()
    scanner = StockScanner(primary_fetcher=manager.get_top_volume_stocks)
    screener = StockScreener(strategy=strategy, discord=discord)
    
    # 4. Strategy & Trader
    trader = SwingTrader(manager, ai_agent, strategy=None, discord_client=discord)

    # 5. DART 실시간 공시 감지 (백그라운드 데몬 스레드)
    try:
        from core.providers.dart_api import DartAPIClient
        from core.analysis.dart_event_handler import DartEventHandler

        dart_handler = DartEventHandler(trader=trader)
        dart_client = DartAPIClient()

        def _dart_holdings_sync():
            """보유 포지션을 trader에서 실시간으로 읽어 handler에 동기화."""
            while True:
                dart_handler.holdings = trader.portfolio.copy() if hasattr(trader, 'portfolio') else {}
                time.sleep(10)

        # DART 폴링 스레드 (30초마다)
        dart_thread = threading.Thread(
            target=dart_client.start_polling,
            args=(dart_handler.on_announcement,),
            kwargs={"interval_sec": 30},
            daemon=True,
            name="DART-Poller"
        )
        # 보유 동기화 스레드 (10초마다)
        holdings_sync_thread = threading.Thread(
            target=_dart_holdings_sync,
            daemon=True,
            name="DART-HoldingsSync"
        )
        dart_thread.start()
        holdings_sync_thread.start()
        print("📡 DART 실시간 공시 감지 데몬 시작됨 (30초 폴링)")
    except Exception as dart_err:
        print(f"⚠️  DART 데몬 시작 실패 (무시하고 계속): {dart_err}")
    
    print("\n✅ AI 스윙 봇 초기화 완료. 메인 루프 진입.")
    
    # ── 데이터 콜백 함수 (Data Adapters) ──
    
    def screener_data_provider(code):
        """Screener용 데이터 제공기"""
        try:
            ohlc = manager.get_daily_ohlc(code)
            time.sleep(0.3)
            investor_trend = manager.get_investor_trend(code)
            time.sleep(0.3)
            current_data = manager.get_current_price(code)
            time.sleep(0.3)
            return ohlc, investor_trend, current_data
        except Exception as e:
            print(f"[{code}] Data Fetch Error: {e}")
            return None, None, None

    def ai_data_provider(code):
        """AI Agent용 데이터 제공기 (뉴스, 온도 등 포함)"""
        try:
            ohlc, investor_trend, current_data = screener_data_provider(code)
            news = news_scraper.fetch_news()[:5] # 임시 키워드 매칭 제거
            temp = market_temp.calculate()
            
            return {
                "ohlc": ohlc,
                "supply": investor_trend,
                "current_data": current_data,
                "market_temp": temp,
                "news": news,
                "screener_score": 0 # (실제 구현 시 Screener 결과를 캐싱하여 주입 고려)
            }
        except Exception as e:
            print(f"[{code}] AI Data Fetch Error: {e}")
            return {}
            
    # ── 메인 루프 ──
    last_scan_time = 0
    scan_interval = trader.get_scan_interval() * 60
    last_portfolio_sync = 0
    
    try:
        while True:
            KST = timezone(timedelta(hours=9))
            now = datetime.datetime.now(KST)
            time_str = now.strftime("%H%M%S")
            now_ts = time.time()
            
            # 장 운영시간 체크
            if not is_paper and not is_market_hours():
                print(f"[{now.strftime('%H:%M:%S')}] 장 운영시간 아님. 1분 대기...")
                time.sleep(60)
                continue
                
            # 포트폴리오 동기화 (10분마다)
            if now_ts - last_portfolio_sync > 600:
                print("🔄 포트폴리오 동기화 중...")
                trader.sync_portfolio()
                last_portfolio_sync = now_ts
                
            # 스크리닝 사이클
            if now_ts - last_scan_time > scan_interval:
                print(f"[{now.strftime('%H:%M:%S')}] 🔍 종목 탐색 시작 (Scanner -> Screener)...")
                # 1. 스캐너 (단순 조회)
                raw_stocks = scanner.get_top_volume_stocks(limit=15)
                # 2. 스크리너 (스코어링) -> Discord 보고됨
                screened_stocks = screener.screen(raw_stocks, screener_data_provider)
                
                if screened_stocks:
                    # 상위 점수 종목만 타겟팅 (포트폴리오 미보유분 중심)
                    trader.update_target_codes(screened_stocks[:5])
                    print(f"🎯 신규 타겟 {len(screened_stocks[:5])}종목 등록 완료.")
                    
                last_scan_time = now_ts
                
            # 매매 사이클 (보유 종목 + 신규 타겟 종목)
            # AI 통신 대기가 길 수 있으므로 로그를 확실히 남김
            for code in trader.target_codes:
                name = trader.stock_names.get(code, '')
                try:
                    trader.process_stock_with_ai(code, time_str, ai_data_provider)
                except Exception as e:
                    print(f"Error processing {name}({code}): {e}")
                
                # API Rate limit
                time.sleep(1)
                
            # 루프 대기 시간 (보통 10~30초)
            loop_wait = trader.get_loop_interval()
            print(f"[{now.strftime('%H:%M:%S')}] Zzz... ({loop_wait}s)")
            time.sleep(loop_wait)

    except KeyboardInterrupt:
        print("\n중지 요청받음. 봇 종료.")
    except Exception as e:
        print(f"\n치명적 오류 발생: {e}")
    finally:
        _release_lock()

if __name__ == "__main__":
    main()
