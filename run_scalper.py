"""
Firefeet Scalping Bot — 독립 실행 엔트리포인트.
실시간 틱 데이터 기반 스캘핑 매매.

Usage:
    python3 run_scalper.py              # 기본 실행 (REAL 모드)
    python3 run_scalper.py --paper      # 모의투자 모드
    python3 run_scalper.py --dry-run    # 드라이런 (시그널 로깅만, 주문 없음)
"""

import sys
import os
import time
import datetime
import yaml
from datetime import timezone, timedelta

from core.encoding_setup import setup_utf8_stdout
setup_utf8_stdout()

from core.bot_lifecycle import BotLifecycle

_lifecycle = BotLifecycle("firefeet_scalper", close_time="1530")
_lifecycle.setup_signal_handler()
_lifecycle.acquire_lock()

from core.config_loader import ConfigLoader
from core.kis_auth import KISAuth
from core.providers.kis_api import KISManager
from core.providers.data_service import KISDataService
from core.kis_websocket import KISWebSocket
from core.discord_client import DiscordClient
from core.execution.scanner import StockScanner
from core.analysis.market_temperature import MarketTemperature
from core.scalping.scalp_engine import ScalpEngine


def is_market_hours():
    """한국 장 운영시간 여부 (09:00~15:30 KST, 주말 제외)"""
    kst = timezone(timedelta(hours=9))
    now = datetime.datetime.now(kst)
    if now.weekday() >= 5:
        return False
    now_str = f"{now.hour:02d}{now.minute:02d}"
    return _lifecycle.is_market_hours(now_str)


def main():
    # ── 1. 인자 파싱 ──────────────────────────
    args = sys.argv[1:]
    mode = "REAL"
    dry_run = False

    if "--paper" in args:
        mode = "PAPER"
    if "--dry-run" in args:
        dry_run = True

    print("=" * 60)
    print("🔥 Firefeet Scalping Bot")
    print(f"   Mode: {mode} | Dry Run: {dry_run}")
    print("=" * 60)

    # ── 2. 초기화 ──────────────────────────
    loader = ConfigLoader()
    config = loader.get_kis_config(mode=mode)
    account_info = loader.get_account_info(mode=mode)

    auth = KISAuth(config)
    if mode == "PAPER":
        from core.providers.kis_api import DummyManager
        manager = DummyManager(auth, account_info, mode=mode)
    else:
        manager = KISManager(auth, account_info, mode=mode)
    data_service = KISDataService(manager)

    # HTS ID (체결통보용 — secrets.yaml에서 로드)
    secrets = loader.load_config()
    hts_id = secrets.get("HTS_ID", "")

    # Discord
    discord = DiscordClient(webhook_key="DISCORD_SCALP_WEBHOOK_URL")

    # Scanner (기존 거래량 스캐너 재사용, DataService TTL 캐시 경유)
    scanner = StockScanner(data_service.get_top_volume_stocks)

    # WebSocket (scalping_settings에서 max_subscriptions 로드)
    try:
        with open("config/scalping_settings.yaml", "r", encoding="utf-8") as f:
            _scalp_cfg = yaml.safe_load(f) or {}
        _max_subs = _scalp_cfg.get("websocket", {}).get("max_subscriptions", 41)
    except Exception:
        _max_subs = 41
    kis_ws = KISWebSocket(auth, mode=mode, hts_id=hts_id, max_subscriptions=_max_subs)

    # Scalping Engine
    engine = ScalpEngine(manager, kis_ws, scanner, discord=discord, mode=mode)

    # ── Stale position cleanup ──────────────────────────
    engine.position_registry.cleanup_stale()

    # ── 미체결 주문 정리 (시작 시) ──────────────────────────
    print("[Scalper] 기존 미체결 주문 정리 중...")
    try:
        orders = manager.get_order_status()
        unfilled = [o for o in orders if int(o.get('rmn_qty', 0)) > 0]
        if unfilled:
            print(f"[Scalper] 미체결 {len(unfilled)}건 취소")
            for o in unfilled:
                odno = o.get('odno')
                code = o.get('pdno', '')
                rmn = int(o.get('rmn_qty', 0))
                name = o.get('prdt_name', code)
                manager.cancel_order(odno, code, rmn)
                print(f"  취소: #{odno} {name} {rmn}주")
                time.sleep(0.5)
        else:
            print("[Scalper] 미체결 없음")
    except Exception as e:
        print(f"[Scalper] 미체결 정리 실패: {e}")

    # ── 3. 메인 루프 ──────────────────────────
    last_temp_time = 0  # 마지막 온도 계산 시각 (Unix timestamp, 0=미계산)
    last_scan_time = 0
    ws_connected = False

    try:
        while True:
            # 장 외 시간 대기
            if not is_market_hours():
                now_kst = datetime.datetime.now(timezone(timedelta(hours=9)))
                timestamp = now_kst.strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{timestamp}] 장 운영시간 외 — 대기 중 (09:00~15:30 KST, 평일)")
                last_temp_time = 0  # 다음 장 시작 시 온도 재계산

                # WebSocket 종료
                if ws_connected:
                    kis_ws.disconnect()
                    ws_connected = False

                # 일일 리셋
                engine.reset_daily()
                time.sleep(60)
                continue

            # ── 장 시작 시 초기화 ──────────────

            # 온도 분석 (30분 주기 장중 재계산)
            temp_interval = 1800  # 30분
            current_time_ts = time.time()
            if current_time_ts - last_temp_time >= temp_interval:
                is_recalc = last_temp_time > 0
                label = "장중 온도 재계산" if is_recalc else "장 시작 — Market Temperature 계산"
                print(f"\n🌡️ {label}...")
                try:
                    mt = MarketTemperature()
                    # Liquidity hint from orderbook spread
                    liquidity_hint = None
                    if engine.target_codes:
                        spreads = []
                        for _c in engine.target_codes[:5]:
                            _s = engine.orderbook_analyzer.get_spread_bps(_c)
                            if _s != float('inf') and _s > 0:
                                spreads.append(_s)
                        if spreads:
                            liquidity_hint = {"spread_bps": sum(spreads) / len(spreads)}
                    temp_result = mt.calculate(liquidity_data=liquidity_hint)
                    temp_report = mt.generate_report(temp_result)
                    print(temp_report)
                    engine.apply_temperature(temp_result)
                    if discord:
                        prefix = "🔄 장중 재계산" if is_recalc else "🌡️ 장 시작"
                        discord.send(
                            f"{prefix}\n{temp_report}\n\n⚙️ 스캘핑: "
                            f"threshold={engine.strategy.confidence_threshold}"
                        )
                except Exception as e:
                    print(f"[Temperature] 온도 계산 실패 — 기존 설정 유지: {e}")
                    if last_temp_time == 0:
                        # 최초 실패 시 NEUTRAL 기본값
                        engine.apply_temperature({"level": "NEUTRAL", "temperature": 0})
                        if discord:
                            discord.send(f"⚠️ 온도 계산 실패 — NEUTRAL 기본값으로 보수적 운영")
                last_temp_time = current_time_ts

            # WebSocket 접속
            if not ws_connected:
                print("[Scalper] WebSocket 접속 시도...")
                if kis_ws.connect():
                    ws_connected = True
                    # 체결통보 구독
                    if hts_id:
                        kis_ws.subscribe_notice()
                else:
                    print("[Scalper] WebSocket 접속 실패 — 30초 후 재시도")
                    time.sleep(30)
                    continue

            # ── 종목 스캔 + 구독 갱신 ──────────────
            scan_cfg = engine.settings.get("screener", {})
            scan_interval = scan_cfg.get("refresh_interval", 300)
            current_time = time.time()

            if current_time - last_scan_time > scan_interval:
                last_scan_time = current_time
                print("[Scalper] 종목 스캔 중...")
                try:
                    limit = scan_cfg.get("top_n", 30)
                    raw_stocks = scanner.get_top_stocks(limit=limit)
                    if raw_stocks:
                        engine.update_targets(raw_stocks)
                        print(f"[Scalper] 타겟 {len(engine.target_codes)}종목 확정")
                    else:
                        print("[Scalper] 스캔 결과 없음 — 기존 타겟 유지")
                except Exception as e:
                    print(f"[Scalper] 종목 스캔 실패: {e}")

            # ── 타겟 없으면 대기 ──────────────
            if not engine.target_codes:
                print("[Scalper] 타겟 종목 없음 — 30초 후 재스캔")
                time.sleep(30)
                last_scan_time = 0  # 즉시 재스캔
                continue

            # ── 데이터 축적 대기 ──────────────
            # WebSocket 구독 후 최소 30초 데이터 축적 후 매매 시작
            min_data_codes = sum(1 for c in engine.target_codes
                                 if engine.tick_buffer.has_enough_data(c, 30))
            if min_data_codes == 0:
                print("[Scalper] 틱 데이터 축적 중... (최소 30틱 필요)")
                time.sleep(5)
                continue

            # ── 매매 루프 실행 ──────────────
            if dry_run:
                # 드라이런: 시그널만 로깅
                _dry_run_cycle(engine)
            else:
                # 실제 매매: 1.5초 주기 루프
                engine.run()

    except KeyboardInterrupt:
        print("\n[Scalper] 중단 요청...")
    finally:
        # 정리
        if engine.positions and not dry_run:
            print("[Scalper] 잔여 포지션 청산 중...")
            engine._force_exit_all("SCALP_SELL_SHUTDOWN")

        engine.position_registry.remove_all("scalp")

        if ws_connected:
            kis_ws.unsubscribe_all()
            kis_ws.disconnect()

        # 일일 요약
        engine.trade_logger.print_daily_summary()
        engine.print_status()

        if discord:
            status = engine.get_status()
            discord.send(
                f"🔥 **스캘핑 봇 종료**\n"
                f"일일 손익: {status['daily_pnl']:+,}원 | 거래: {status['trade_count']}건"
            )

        _release_lock()


def _dry_run_cycle(engine):
    """드라이런: 시그널 평가만 수행하고 로깅"""
    print("\n[DryRun] 시그널 평가 시작 (주문 없음)")
    last_strategy = None
    try:
        while True:
            now = datetime.datetime.now()
            timestamp = now.strftime("%H:%M:%S")

            # 전략 선택 (점심 구간 차단 포함)
            profile = engine.strategy_selector.select()
            strategy_name = engine.strategy_selector.current_strategy_name()

            # 전략 전환 감지 시 로그
            if strategy_name != last_strategy:
                if profile is None:
                    print(f"[{timestamp}] [StrategySelector] → {strategy_name} (진입 차단)")
                else:
                    print(f"[{timestamp}] [StrategySelector] → {strategy_name} "
                          f"(TP={profile.take_profit}% SL={profile.stop_loss}% "
                          f"thresh={profile.confidence_threshold} hold={profile.max_hold_seconds}s)")
                last_strategy = strategy_name

            if profile is None:
                time.sleep(engine._eval_interval)
                continue

            for code in engine.target_codes:
                if not engine.tick_buffer.has_enough_data(code, 30):
                    continue

                result = engine.strategy.evaluate(
                    code, engine.tick_buffer, engine.orderbook_analyzer, profile=profile
                )
                name = engine.stock_names.get(code, code)
                conf = result["confidence"]
                composite = result["composite"]

                if conf >= 0.3:  # 유의미한 시그널만 출력
                    signals = result["signals"]
                    print(f"  [{timestamp}] [{strategy_name.upper()}] {name}({code}) "
                          f"conf={conf:.3f} composite={composite:.1f} "
                          f"enter={'✅' if result['should_enter'] else '❌'} "
                          f"| VWAP:{signals.get('vwap_reversion', 0):.0f} "
                          f"OB:{signals.get('orderbook_pressure', 0):.0f} "
                          f"Mom:{signals.get('momentum_burst', 0):.0f} "
                          f"Vol:{signals.get('volume_surge', 0):.0f} "
                          f"Trend:{signals.get('micro_trend', 0):.0f}")

            time.sleep(engine._eval_interval)

    except KeyboardInterrupt:
        print("[DryRun] 종료")


if __name__ == "__main__":
    main()
