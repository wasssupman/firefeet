import sys
import os
import yaml
import time
import datetime
from datetime import timezone, timedelta

from core.encoding_setup import setup_utf8_stdout
setup_utf8_stdout()

from core.bot_lifecycle import BotLifecycle

_lifecycle = BotLifecycle("firefeet_main", close_time="1530")
_lifecycle.setup_signal_handler()
_lifecycle.acquire_lock()

from core.config_loader import ConfigLoader
from core.kis_auth import KISAuth
from core.providers.kis_api import KISManager
from core.providers.data_service import KISDataService
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
    now_str = f"{now.hour:02d}{now.minute:02d}"
    return _lifecycle.is_market_hours(now_str)

def main():
    print("=== Firefeet Auto Trading System ===")
    
    # 1. Initialize Components
    loader = ConfigLoader()
    mode = "PAPER"
    if "--real" in sys.argv:
        mode = "REAL"
        print("⚠️  WARNING: REAL TRADING MODE ACTIVE")
    print(f"Mode: {mode}")
    
    config = loader.get_kis_config(mode=mode)
    account_info = loader.get_account_info()
    
    auth = KISAuth(config)
    manager = KISManager(auth, account_info, mode=mode)
    data_service = KISDataService(manager)
    strategy = VolatilityBreakoutStrategy(k=0.5)
    discord = DiscordClient()
    
    # 2.5 Data Provider Setup
    from core.analysis.supply import SupplyAnalyzer
    supply_analyzer = SupplyAnalyzer()

    def screener_data_provider(code):
        ohlc = data_service.get_daily_ohlc(code)
        investor_trend = data_service.get_investor_trend(code)
        supply = supply_analyzer.analyze_supply(investor_trend)
        current_data = data_service.get_current_price(code)
        return ohlc, supply, current_data

    def trading_data_provider(code):
        """트레이딩 루프용 data provider → (df, current_price)"""
        df = data_service.get_daily_ohlc(code)
        price_data = data_service.get_current_price(code)
        if price_data is None:
            return None, None
        return df, price_data["price"]

    # 2. Trader, Scanner & Screener Setup
    bot = FirefeetTrader(manager, strategy, discord_client=discord, data_provider_fn=trading_data_provider)
    scanner = StockScanner(primary_fetcher=data_service.get_top_volume_stocks)
    screener = StockScreener(strategy, discord=discord)
    
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

    last_temp_time = 0  # 온도 분석 타임스탬프 (0 = 미계산)
    TEMP_REFRESH_INTERVAL = 3600  # 1시간마다 갱신

    try:
        while True:
            if not is_market_hours():
                now = datetime.datetime.now(timezone(timedelta(hours=9)))
                timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{timestamp}] 장 운영시간 외 — 대기 중 (09:00~15:30 KST, 평일)")
                last_temp_time = 0  # 다음 장 시작 시 온도 재계산
                bot.reset_daily()   # 날짜 변경 시에만 리셋 (장중 재시작 안전)
                time.sleep(60)
                continue

            # 주기적 온도 갱신 (초기 계산 + 1시간마다)
            if time.time() - last_temp_time > TEMP_REFRESH_INTERVAL:
                is_refresh = last_temp_time > 0
                label = "갱신" if is_refresh else "초기 계산"
                print(f"\n🌡️ Market Temperature {label}...")
                try:
                    mt = MarketTemperature()
                    temp_result = mt.calculate()
                    if temp_result.get("degraded"):
                        print("⚠️ 시장 온도 데이터 불완전 (일부 소스 무응답)")
                    temp_report = mt.generate_report(temp_result)
                    print(temp_report)
                    profiles = mt.config.get("strategy_profiles", {})
                    strategy.apply_temperature(temp_result, profiles)
                    if discord:
                        discord.send(temp_report + f"\n\n⚙️ 전략: k={strategy.k}, "
                                     f"TP={strategy.take_profit:+.1f}%, SL={strategy.stop_loss:.1f}%")
                except Exception as e:
                    print(f"[Temperature] 온도 계산 실패 (기존 전략 유지): {e}")
                bot.trading_rules = bot._load_trading_rules()
                last_temp_time = time.time()

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
