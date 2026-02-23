import sys
import os
import yaml
import time
import datetime
from datetime import timezone, timedelta

# ── 중복 실행 방지 (PID 파일 락) ──────────────────────────
_PID_FILE = "/tmp/firefeet_main.pid"

def _acquire_lock():
    """이미 실행 중인 프로세스가 있으면 종료."""
    if os.path.exists(_PID_FILE):
        try:
            with open(_PID_FILE) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            print(f"[Main] ❌ 이미 실행 중입니다 (PID {old_pid}). 중복 실행 방지로 종료합니다.")
            print(f"[Main]    기존 프로세스를 먼저 종료하세요: kill {old_pid}")
            sys.exit(1)
        except (ProcessLookupError, PermissionError):
            pass
        except ValueError:
            pass
    with open(_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

def _release_lock():
    """종료 시 PID 파일 제거."""
    try:
        os.remove(_PID_FILE)
    except FileNotFoundError:
        pass

_acquire_lock()

from core.config_loader import ConfigLoader
from core.kis_auth import KISAuth
from core.providers.kis_api import KISManager
from core.analysis.technical import VolatilityBreakoutStrategy
from core.discord_client import DiscordClient
from core.execution.trader import FirefeetTrader
from core.execution.scanner import StockScanner
from core.analysis.scoring_engine import StockScreener
from core.analysis.market_temperature import MarketTemperature


def is_market_hours():
    """한국 장 운영시간 여부 (09:00~15:30 KST, 주말 제외)"""
    kst = timezone(timedelta(hours=9))
    now = datetime.datetime.now(kst)
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return 900 <= t <= 1530

def main():
    print("=== Firefeet Auto Trading System ===")
    
    # 1. Initialize Components
    loader = ConfigLoader()
    mode = "REAL" # Set to REAL for actual trading
    print(f"Mode: {mode}")
    
    config = loader.get_kis_config(mode=mode)
    account_info = loader.get_account_info()
    
    auth = KISAuth(config)
    manager = KISManager(auth, account_info, mode=mode)
    strategy = VolatilityBreakoutStrategy(k=0.5)
    discord = DiscordClient()
    
    # 2. Trader, Scanner & Screener Setup
    bot = FirefeetTrader(manager, strategy, discard_client=discord)
    scanner = StockScanner(primary_fetcher=manager.get_top_volume_stocks)
    screener = StockScreener(strategy, discord=discord)
    
    # 2.5 Data Provider Setup for Screener
    from core.analysis.supply import SupplyAnalyzer
    supply_analyzer = SupplyAnalyzer()
    
    def screener_data_provider(code):
        ohlc = manager.get_daily_ohlc(code)
        time.sleep(0.5)
        
        investor_trend = manager.get_investor_trend(code)
        supply = supply_analyzer.analyze_supply(investor_trend)
        time.sleep(0.5)
        current_data = manager.get_current_price(code)
        time.sleep(0.5)
        return ohlc, supply, current_data
    
    # 3. Add Initial Targets from Watchlist
    try:
        with open("config/watchlist.yaml", 'r', encoding='utf-8') as f:
            watchlist_data = yaml.safe_load(f).get("watchlist", [])
            for item in watchlist_data:
                bot.add_target(item['code'], item.get('name'))
    except Exception as e:
        print(f"Failed to load watchlist: {e}")
        bot.add_target("005930", "삼성전자")
        
    last_scan_time = 0
    last_sync_time = 0

    # 4. Run
    print("\n[Trader] Starting Main Loop...")
    if discord:
        discord.send("🔥 **Firefeet Trading Bot Started! (Dynamic Scanning Enabled)**")

    temp_done = False  # 온도 분석은 장 시작 전 1회만

    try:
        while True:
            if not is_market_hours():
                now = datetime.datetime.now(timezone(timedelta(hours=9)))
                timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{timestamp}] 장 운영시간 외 — 대기 중 (09:00~15:30 KST, 평일)")
                temp_done = False  # 다음 장 시작 시 온도 재계산
                bot.sold_today = {}  # 다음 장 세션 초기화
                bot.daily_realized_pnl = 0
                bot.consecutive_sl_count = 0
                bot.sl_brake_until = None
                time.sleep(60)
                continue

            # 장 시작 시 온도 1회 재계산
            if not temp_done:
                print("\n🌡️ 장 시작 — Market Temperature 재계산...")
                try:
                    mt = MarketTemperature()
                    temp_result = mt.calculate()
                    temp_report = mt.generate_report(temp_result)
                    print(temp_report)
                    profiles = mt.config.get("strategy_profiles", {})
                    strategy.apply_temperature(temp_result, profiles)
                    if discord:
                        discord.send(temp_report + f"\n\n⚙️ 전략: k={strategy.k}, "
                                     f"TP={strategy.take_profit:+.1f}%, SL={strategy.stop_loss:.1f}%")
                except Exception as e:
                    print(f"[Temperature] 온도 계산 실패 (기본 전략 유지): {e}")
                bot.trading_rules = bot._load_trading_rules()
                temp_done = True

            # Refresh targets (온도 기반 동적 주기)
            scan_interval = bot.get_scan_interval()
            current_time = time.time()
            if current_time - last_scan_time > scan_interval:
                print("🔍 Scanning & screening stocks...")
                new_targets = scanner.get_top_volume_stocks(limit=20)
                if new_targets:
                    screened = screener.get_screened_stocks(new_targets, screener_data_provider)
                    if screened:
                        bot.update_target_codes(screened)
                    else:
                        print("[Screener] No stocks passed screening")
                last_scan_time = current_time

            # 주기적 포트폴리오 동기화 (5분마다 — 실체결가 반영)
            if current_time - last_sync_time > 300:
                try:
                    bot.sync_portfolio()
                except Exception as e:
                    print(f"[Sync] 포트폴리오 동기화 실패: {e}")
                last_sync_time = current_time

            # Standard trading logic (매 루프 규칙 reload)
            bot.settings = bot._load_settings()
            bot.trading_rules = bot._load_trading_rules()
            now = datetime.datetime.now()
            time_str = now.strftime("%H%M")
            timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

            current_targets = [c for c in bot.target_codes if c not in bot.sold_today]
            blocked_count = len(bot.target_codes) - len(current_targets)

            target_display = [f"{bot.stock_names.get(c, 'Unknown')}({c})" for c in current_targets]
            print(f"[{timestamp}] 👟 Checking {len(current_targets)} stocks ({blocked_count} blocked): {target_display}")
            for i, code in enumerate(current_targets):
                try:
                    bot.process_stock(code, time_str)
                except Exception as e:
                    print(f"[Error] {code} 처리 중 예외: {e}")
                time.sleep(1)

            # 차단 비율 높으면 조기 스캔
            total = len(bot.target_codes)
            if total > 0 and blocked_count / total >= 0.3:
                if current_time - last_scan_time > 60:
                    print(f"🔄 {blocked_count}/{total} 종목 차단 — 조기 스캔 실행")
                    new_targets = scanner.get_top_volume_stocks(limit=20)
                    if new_targets:
                        screened = screener.get_screened_stocks(new_targets, screener_data_provider)
                        if screened:
                            bot.update_target_codes(screened)
                    last_scan_time = current_time

            loop_interval = bot.get_loop_interval()
            print(f"[{timestamp}] ⬇️ Cycle complete. Waiting {loop_interval}s...")
            time.sleep(loop_interval)

    except KeyboardInterrupt:
        print("[Trader] Stopping...")
        bot.trade_logger.print_daily_summary()
    finally:
        _release_lock()

if __name__ == "__main__":
    main()
