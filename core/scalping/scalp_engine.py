import time
import datetime
from datetime import timezone, timedelta
import threading
import yaml
import os
import json

KST = timezone(timedelta(hours=9))

from core.providers.kis_api import OrderType
from core.trade_logger import TradeLogger
from core.scalping.tick_buffer import TickBuffer
from core.scalping.orderbook_analyzer import OrderbookAnalyzer
from core.scalping.scalp_signals import ScalpSignals
from core.scalping.scalp_strategy import ScalpStrategy
from core.scalping.risk_manager import RiskManager
from core.scalping.scalp_screener import ScalpScreener
from core.scalping.strategy_selector import StrategySelector
from core.technical.candle_history import CandleHistory, Candle
from core.technical.analyzer import IntradayAnalyzer


class ScalpEngine:
    """스캘핑 메인 오케스트레이터 (1.5초 주기 매매 루프)"""

    def __init__(self, manager, kis_ws, scanner, discord=None,
                 settings_path="config/scalping_settings.yaml", mode="PAPER"):
        self.manager = manager
        self.kis_ws = kis_ws
        self.scanner = scanner
        self.discord = discord
        self.settings_path = settings_path
        self.settings = self._load_settings()

        # 데이터 레이어
        tick_buf_size = self.settings.get("tick_buffer_size", 600)
        self.tick_buffer = TickBuffer(max_size=tick_buf_size)
        self.orderbook_analyzer = OrderbookAnalyzer()

        # 기술적 분석 레이어
        ta_cfg = {}
        candle_interval = 15
        max_candles = 60
        try:
            ta_cfg_path = "config/technical_config.yaml"
            if os.path.exists(ta_cfg_path):
                with open(ta_cfg_path, "r", encoding="utf-8") as f:
                    ta_cfg = yaml.safe_load(f) or {}
                candle_interval = ta_cfg.get("candle_interval", 15)
                max_candles = ta_cfg.get("max_candles", 60)
        except Exception:
            pass
        self.candle_history = CandleHistory(max_candles=max_candles, interval=candle_interval)
        self.ta_analyzer = IntradayAnalyzer(self.candle_history, config=ta_cfg)
        self.tick_buffer.set_candle_callback(self._on_candle_complete)
        self._ta_candle_interval = candle_interval

        # 전략 레이어
        self.signals = ScalpSignals(settings_path)
        self.strategy = ScalpStrategy(self.signals, settings_path)
        self.strategy_selector = StrategySelector("config/scalping_strategies.yaml")
        self.risk_manager = RiskManager(settings_path, mode=mode)
        self.screener = ScalpScreener(manager, settings_path)

        # 로깅
        self.trade_logger = TradeLogger(strategy="scalp")

        # 포지션 관리
        self.positions = {}  # {code: {qty, buy_price, buy_time, order_no, trailing_high}}
        self.stock_names = {}  # {code: name}
        self.pending_orders = {}  # {order_no: {code, type, price, qty, time}}

        # 종목 관리
        self.target_codes = []  # WebSocket 구독 대상 종목
        self._order_cooldown = {}  # {code: cooldown_until_time}
        self._low_composite_cycles = {}  # {code: 연속 저복합점수 사이클 수} — adaptive pool rotation

        # 실행 상태
        self._running = False
        self._eval_interval = self.settings.get("eval_interval_ms", 1500) / 1000.0

        # 매도 후 재진입 쿨다운 {code: cooldown_until_timestamp}
        self._sell_cooldown_path = "logs/sell_cooldown.json"
        self._sell_cooldown = self._load_sell_cooldown()

        # WebSocket 콜백 등록
        self.kis_ws.on_tick(self._on_tick)
        self.kis_ws.on_orderbook(self._on_orderbook)
        self.kis_ws.on_notice(self._on_notice)

    def _load_settings(self):
        try:
            if os.path.exists(self.settings_path):
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[ScalpEngine] Settings load failed: {e}")
        return {}

    def _load_sell_cooldown(self) -> dict:
        """재시작 후에도 매도 쿨다운 복원 (당일 쿨다운만 유효)"""
        try:
            if os.path.exists(self._sell_cooldown_path):
                with open(self._sell_cooldown_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                now = time.time()
                # 만료된 항목 제거, 타입 보정
                restored = {code: float(until) for code, until in raw.items()
                            if float(until) > now}
                if restored:
                    print(f"[ScalpEngine] 매도 쿨다운 복원: {list(restored.keys())} "
                          f"({len(restored)}종목)")
                return restored
        except Exception:
            pass
        return {}

    def _save_sell_cooldown(self):
        """매도 쿨다운을 디스크에 저장"""
        try:
            os.makedirs(os.path.dirname(self._sell_cooldown_path), exist_ok=True)
            with open(self._sell_cooldown_path, "w", encoding="utf-8") as f:
                json.dump(self._sell_cooldown, f)
        except Exception as e:
            print(f"[ScalpEngine] 쿨다운 저장 실패: {e}")

    # ── Candle Callback ──────────────────────────

    def _on_candle_complete(self, code, interval, candle_data):
        """TickBuffer 캔들 완성 콜백 → CandleHistory에 저장"""
        if interval == self._ta_candle_interval:
            self.candle_history.on_candle_complete(code, Candle(
                open=candle_data["open"],
                high=candle_data["high"],
                low=candle_data["low"],
                close=candle_data["close"],
                volume=candle_data["volume"],
                timestamp=candle_data["start_time"],
            ))

    # ── WebSocket Callbacks ──────────────────────────

    def _on_tick(self, tick_data):
        """체결가 수신 → TickBuffer에 저장"""
        code = tick_data.get("code")
        if not code:
            return

        price = tick_data["price"]
        volume = tick_data["volume"]

        # 틱 방향 판정
        direction_raw = tick_data.get("tick_direction", "0")
        if direction_raw in ("1", "2"):  # 매수체결
            direction = 1
        elif direction_raw in ("5", "4"):  # 매도체결
            direction = -1
        else:
            direction = 0

        self.tick_buffer.add_tick(code, price, volume, direction=direction)

        # 이름 업데이트 (WebSocket에서 이름 올 수도 있으니)
        if code not in self.stock_names:
            self.stock_names[code] = code

    def _on_orderbook(self, ob_data):
        """호가 수신 → OrderbookAnalyzer에 저장"""
        self.orderbook_analyzer.update(ob_data)

    def _on_notice(self, notice_data):
        """체결통보 수신 → 주문 상태 업데이트"""
        order_no = notice_data.get("order_no", "")
        if order_no in self.pending_orders:
            pending = self.pending_orders[order_no]
            code = pending["code"]
            name = self.stock_names.get(code, code)

            if notice_data.get("order_status") == "체결":
                price = notice_data.get("price", pending["price"])
                qty = notice_data.get("qty", pending["qty"])

                if pending["type"] == "BUY":
                    self.positions[code] = {
                        "qty": qty,
                        "buy_price": price,
                        "buy_time": time.time(),
                        "order_no": order_no,
                        "trailing_high": price,
                        "profile": pending.get("profile"),  # 청산 시 재사용
                    }
                    confidence = pending.get("confidence", 0)
                    self.trade_logger.log_scalp_buy(code, name, qty, price, confidence)
                    print(f"[ScalpEngine] ✅ 매수 체결: {name}({code}) {qty}주 @ {price:,}원")
                elif pending["type"] == "SELL":
                    buy_price = pending.get("buy_price", 0)
                    signal = pending.get("signal", "SCALP_SELL")
                    sell_info = self.trade_logger.log_scalp_sell(code, name, qty, price, buy_price, signal)
                    self.risk_manager.record_trade(sell_info["realized_pnl"])

                    if self.discord:
                        self.discord.send(
                            f"⚡ **SCALP SELL ({signal})** {name}({code}) {qty}주 @ {price:,}원\n"
                            f"실현손익: {sell_info['realized_pnl']:+,}원 ({sell_info['pnl_rate']:+.2f}%)"
                        )

                    self.positions.pop(code, None)
                    # 체결 통보 경로에서도 재진입 쿨다운 등록
                    sell_cooldown_secs = self.settings.get("sell_cooldown_seconds", 300)
                    self._sell_cooldown[code] = time.time() + sell_cooldown_secs
                    self._save_sell_cooldown()
                    print(f"[ScalpEngine] ✅ 매도 체결: {name}({code}) {qty}주 @ {price:,}원")

                del self.pending_orders[order_no]

    # ── Target Management ──────────────────────────

    def update_targets(self, stocks):
        """종목 목록 업데이트 + WebSocket 구독 로테이션"""
        filtered = self.screener.filter_stocks(stocks, self.orderbook_analyzer)

        # 이름 업데이트
        for s in filtered:
            self.stock_names[s["code"]] = s.get("name", s["code"])

        # adaptive pool rotation 카운터 초기화 (종목 풀 갱신 시 재평가 기회 부여)
        self._low_composite_cycles.clear()

        # 우선순위 코드 (보유 종목 우선)
        held_codes = list(self.positions.keys())
        new_codes = [s["code"] for s in filtered if s["code"] not in held_codes]
        self.target_codes = held_codes + new_codes

        # WebSocket 구독 로테이션
        ws_cfg = self.settings.get("websocket", {})
        tick_slots = ws_cfg.get("tick_slots", 10)
        ob_slots = ws_cfg.get("orderbook_slots", 5)
        self.kis_ws.rotate_subscriptions(self.target_codes, tick_slots, ob_slots)

        names = [f"{self.stock_names.get(c, c)}({c})" for c in self.target_codes[:10]]
        print(f"[ScalpEngine] 타겟 업데이트: {len(self.target_codes)}종목 — {names}")

    # ── Main Trading Loop ──────────────────────────

    def run(self):
        """메인 매매 루프 (1.5초 주기)"""
        self._running = True
        print(f"[ScalpEngine] 매매 루프 시작 ({self._eval_interval}초 주기)")

        if self.discord:
            self.discord.send(
                f"🔥 **스캘핑 봇 시작** | "
                f"온도: {self.strategy.temperature_level} | "
                f"임계값: {self.strategy.confidence_threshold}"
            )

        try:
            while self._running:
                loop_start = time.time()

                try:
                    self._eval_cycle()
                except Exception as e:
                    print(f"[ScalpEngine] 루프 에러: {e}")

                # 고정 주기 유지
                elapsed = time.time() - loop_start
                sleep_time = max(0, self._eval_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("[ScalpEngine] 중단 요청...")
        finally:
            self._running = False

    def stop(self):
        """매매 루프 중지"""
        self._running = False

    def _eval_cycle(self):
        """한 사이클: 미체결 관리 → 매도 평가 → 매수 평가"""
        now = datetime.datetime.now(KST)
        time_str = now.strftime("%H%M")

        # 30초마다 상태 로그
        if not hasattr(self, '_last_status_log'):
            self._last_status_log = 0
        if time.time() - self._last_status_log >= 30:
            data_codes = sum(1 for c in self.target_codes
                             if self.tick_buffer.has_enough_data(c, 30))
            strategy_name = self.strategy_selector.current_strategy_name()
            print(f"[{now.strftime('%H:%M:%S')}] 전략={strategy_name} 타겟={len(self.target_codes)} "
                  f"데이터OK={data_codes} 포지션={len(self.positions)} "
                  f"미체결={len(self.pending_orders)}")
            self._last_status_log = time.time()

        # 설정 리로드
        self.settings = self._load_settings()
        self.risk_manager.reload_rules()

        # 0. 런타임 불변조건 가드
        _max_pos = self.risk_manager._get_max_positions()
        _pending_buys = sum(1 for p in self.pending_orders.values() if p["type"] == "BUY")
        _effective = len(self.positions) + _pending_buys
        if _effective > _max_pos + 1:
            print(f"[ScalpEngine] 🚨 INVARIANT VIOLATION: 포지션 초과 "
                  f"({_effective} > {_max_pos}+1) — 전 포지션 청산 + 엔진 중지")
            self._force_exit_all("SCALP_SELL_INVARIANT")
            self.stop()
            return

        _budget = self.settings.get("scalping_budget", 500000)
        _invested = sum(p["qty"] * p["buy_price"] for p in self.positions.values())
        _pending_inv = sum(p["qty"] * p["price"] for p in self.pending_orders.values()
                          if p["type"] == "BUY")
        if (_invested + _pending_inv) > _budget * 1.5:
            print(f"[ScalpEngine] 🚨 INVARIANT VIOLATION: 예산 초과 "
                  f"({_invested + _pending_inv:,.0f} > {_budget * 1.5:,.0f}) — 전 포지션 청산 + 엔진 중지")
            self._force_exit_all("SCALP_SELL_INVARIANT")
            self.stop()
            return

        # 1. 전체 청산 시간 체크
        if self.risk_manager.should_force_exit():
            if self.positions:
                print(f"[ScalpEngine] 장 마감 전 전체 청산 ({time_str})")
                self._force_exit_all("SCALP_SELL_EOD")
            print(f"[ScalpEngine] 장 마감 시간 도달 — 엔진 중지 ({time_str})")
            self.stop()
            return

        # 2. 서킷브레이커 체크 — 전 포지션 청산
        if self.risk_manager.circuit_broken:
            if self.positions:
                print("[ScalpEngine] 🚨 서킷브레이커 — 전 포지션 청산")
                self._force_exit_all("SCALP_SELL_CIRCUIT")
                if self.discord:
                    summary = self.risk_manager.get_daily_summary()
                    self.discord.send(
                        f"🚨 **서킷브레이커 발동**\n"
                        f"일일 손익: {summary['daily_pnl']:+,}원 | "
                        f"연속손실: {summary['consecutive_losses']}회 | "
                        f"거래: {summary['trade_count']}건"
                    )
            return

        # 3. 미체결 주문 타임아웃 관리
        self._manage_pending_orders()

        # 4. 보유 포지션 매도 평가
        for code in list(self.positions.keys()):
            self._eval_exit(code)

        # 5. 신규 진입 평가
        for code in self.target_codes:
            if code in self.positions:
                continue
            if code in [p["code"] for p in self.pending_orders.values()]:
                continue
            self._eval_entry(code)

    # ── Entry Logic ──────────────────────────

    def _eval_entry(self, code):
        """매수 진입 평가"""
        # 포지션 + 미체결 매수 합산 한도 체크
        max_positions = self.risk_manager._get_max_positions()
        pending_buys = sum(1 for p in self.pending_orders.values() if p["type"] == "BUY")
        if (len(self.positions) + pending_buys) >= max_positions:
            return

        # 주문 쿨다운 체크
        if code in self._order_cooldown and time.time() < self._order_cooldown[code]:
            return

        # 매도 후 재진입 쿨다운 체크 (5분)
        if code in self._sell_cooldown and time.time() < self._sell_cooldown[code]:
            return

        # 데이터 충분성 체크
        if not self.tick_buffer.has_enough_data(code, 30):
            # print(f"  [DEBUG] {code} 틱 부족 ({len(self.tick_buffer.get_ticks(code))} / 30)")
            return

        # 전략 선택 (점심 구간이면 None → 진입 차단)
        profile = self.strategy_selector.select()
        if profile is None:
            return

        # vwap_reversion 전략: VWAP 거리 -0.3~-1.5% 구간 종목만 평가 (Phase 3.1)
        # VWAP 위에 있거나 VWAP에서 너무 많이 이탈한 종목은 bounce 가능성 낮음
        if profile.name == "vwap_reversion":
            vwap_dist = self.tick_buffer.get_vwap_distance(code)
            if not (-1.5 <= vwap_dist <= -0.3):
                return

        # 적응형 풀 스킵 체크 (Phase 3.2): 50사이클 연속 composite < 15이면 건너뜀
        if self._low_composite_cycles.get(code, 0) >= 50:
            return

        # 기술적 분석 오버레이
        ta_overlay = self.ta_analyzer.analyze(code)

        # 전략 평가
        result = self.strategy.evaluate(code, self.tick_buffer, self.orderbook_analyzer, profile=profile, ta_overlay=ta_overlay)

        # composite 기록 — adaptive pool rotation 카운터 관리
        if result["composite"] < 15:
            self._low_composite_cycles[code] = self._low_composite_cycles.get(code, 0) + 1
        else:
            self._low_composite_cycles[code] = 0

        name = self.stock_names.get(code, code)
        penalties = result.get("penalties", {})
        veto = penalties.get("combined", 1) < 0.5
        if result["composite"] >= 15:
            sigs = result.get("signals", {})
            print(f"  [{profile.name.upper()}] {name}({code}) "
                  f"comp={result['composite']:.0f} conf={result['confidence']:.3f} "
                  f"thr={result['threshold']:.2f} {'VETO' if veto else ''} "
                  f"enter={'✅' if result['should_enter'] else '❌'} "
                  f"| V:{sigs.get('vwap_reversion',0):.0f} "
                  f"O:{sigs.get('orderbook_pressure',0):.0f} "
                  f"M:{sigs.get('momentum_burst',0):.0f} "
                  f"$:{sigs.get('volume_surge',0):.0f} "
                  f"T:{sigs.get('micro_trend',0):.0f}")
        if not result["should_enter"]:
            return

        # 주문 수량/가격 결정
        price = self.tick_buffer.get_latest_price(code)
        if price <= 0:
            return

        name = self.stock_names.get(code, code)
        budget = self.settings.get("scalping_budget", 500000)
        max_pos = self.settings.get("max_position_value", 200000)

        # 투자 가용 예산 (포지션 + pending 매수 주문 모두 반영)
        invested = sum(p["qty"] * p["buy_price"] for p in self.positions.values())
        pending_invested = sum(p["qty"] * p["price"] for p in self.pending_orders.values()
                               if p["type"] == "BUY")
        remaining = budget - invested - pending_invested
        per_stock = min(remaining, max_pos)

        qty = int(per_stock // price)
        if qty <= 0:
            print(f"  [DEBUG] {code} 수량 부족 (qty={qty}, price={price}, per_stock={per_stock})")
            return

        position_value = qty * price

        # 리스크 체크
        can_enter, reason = self.risk_manager.can_enter(code, position_value, self.positions)
        if not can_enter:
            print(f"  [DEBUG] {code} Risk Manager 거절: {reason}")
            return

        # 지정가 주문 (최우선 매수호가 또는 현재가)
        order_price = self.manager.round_to_tick(price, direction="up")

        print(f"[ScalpEngine] 📈 매수 시도: {name}({code}) {qty}주 @ {order_price:,}원 "
              f"(conf={result['confidence']:.3f}, strategy={profile.name})")

        try:
            order_no = self.manager.place_order(code, qty, order_price, OrderType.BUY)
        except Exception as e:
            print(f"[ScalpEngine] 매수 주문 API 실패 ({name}): {e}")
            self._order_cooldown[code] = time.time() + 30  # 30초 쿨다운
            return

        if not order_no:
            self._order_cooldown[code] = time.time() + 10  # 10초 쿨다운
            return

        if order_no:
            # 주문 접수 → pending_orders에 등록 (체결 확인은 _manage_pending_orders에서)
            self.pending_orders[order_no] = {
                "code": code,
                "type": "BUY",
                "price": order_price,
                "qty": qty,
                "time": time.time(),
                "confidence": result["confidence"],
                "profile": profile,
            }
            print(f"[ScalpEngine] 📋 매수 주문 접수: {name}({code}) {qty}주 @ {order_price:,}원 "
                  f"(주문번호={order_no}, conf={result['confidence']:.3f}, strategy={profile.name})")

    # ── Exit Logic ──────────────────────────

    def _eval_exit(self, code):
        """매도 평가"""
        pos = self.positions.get(code)
        if not pos:
            return
        if pos.get("selling"):
            return  # 매도 주문 진행 중

        current_price = self.tick_buffer.get_latest_price(code)
        if current_price <= 0:
            return

        buy_price = pos["buy_price"]
        hold_seconds = time.time() - pos["buy_time"]
        name = self.stock_names.get(code, code)

        # 최소 보유시간 체크 (30초) — 리스크 강제청산은 예외
        min_hold = 30

        # 트레일링 스탑 업데이트
        if current_price > pos["trailing_high"]:
            pos["trailing_high"] = current_price

        # 리스크 매니저의 포지션 리스크 체크
        force_exit, risk_reason = self.risk_manager.check_position_risk(
            buy_price, current_price, pos["qty"]
        )
        if force_exit:
            print(f"[ScalpEngine] 🚨 리스크 강제 청산: {name}({code}) — {risk_reason}")
            self._place_sell_order(code, pos["qty"], 0, f"SCALP_SELL_RISK({risk_reason})", is_market=True)
            return

        # 트레일링 스탑 체크
        trailing_activation = self.settings.get("trailing_stop_activation", 0.15)
        trailing_pct = self.settings.get("trailing_stop_pct", 50)
        profit_rate = (current_price - buy_price) / buy_price * 100

        if profit_rate >= trailing_activation:
            # 트레일링 활성: 고점 대비 하락 시 청산
            peak_profit = (pos["trailing_high"] - buy_price) / buy_price * 100
            trailing_floor = peak_profit * (trailing_pct / 100.0)
            if profit_rate < trailing_floor:
                print(f"[ScalpEngine] 📉 트레일링 스탑: {name}({code}) "
                      f"수익 {profit_rate:+.2f}% < floor {trailing_floor:.2f}%")
                self._place_sell_order(
                    code, pos["qty"], 0,
                    f"SCALP_SELL_TRAILING(peak={peak_profit:.2f}%,floor={trailing_floor:.2f}%)",
                    is_market=True
                )
                return

        # 최소 보유시간 미달 시 전략 매도 건너뜀 (리스크/트레일링은 예외)
        if hold_seconds < min_hold:
            return

        # 기술적 분석 오버레이
        ta_overlay = self.ta_analyzer.analyze(code)

        # 전략 기반 매도 판단 (진입 당시 profile 재사용)
        entry_profile = pos.get("profile")
        should_sell, reason, is_market = self.strategy.should_exit(
            code, buy_price, current_price, hold_seconds,
            self.tick_buffer, self.orderbook_analyzer,
            profile=entry_profile,
            ta_overlay=ta_overlay,
        )

        if should_sell:
            if is_market:
                sell_price = 0  # 시장가
            else:
                sell_price = self.manager.round_to_tick(current_price, direction="down")

            print(f"[ScalpEngine] 📉 매도: {name}({code}) — {reason}")
            self._place_sell_order(code, pos["qty"], sell_price, reason, is_market)

    def _place_sell_order(self, code, qty, price, signal, is_market=False):
        """매도 주문 실행"""
        name = self.stock_names.get(code, code)
        order_price = 0 if is_market else price
        buy_price = self.positions.get(code, {}).get("buy_price", 0)

        try:
            order_no = self.manager.place_order(code, qty, order_price, OrderType.SELL)
        except Exception as e:
            print(f"[ScalpEngine] 매도 주문 API 실패 ({name}): {e}")
            if self.discord:
                self.discord.send(f"❌ **SCALP SELL 실패** {name}({code}) — API 에러, 수동 확인 필요")
            return

        if not order_no:
            # 매도 실패 — 연속 실패 카운터 관리
            pos = self.positions.get(code)
            if pos:
                pos["sell_fail_count"] = pos.get("sell_fail_count", 0) + 1
                if pos["sell_fail_count"] >= 3:
                    # 3회 연속 매도 실패 → 유령 포지션, 원래 매수 주문도 취소
                    print(f"[ScalpEngine] ⚠️ 매도 3회 실패 → 유령 포지션 제거: {name}({code})")
                    buy_odno = pos.get("order_no")
                    if buy_odno:
                        try:
                            self.manager.cancel_order(buy_odno, code, pos["qty"])
                            print(f"[ScalpEngine] 원매수 주문 취소: #{buy_odno}")
                        except Exception:
                            pass
                    self.positions.pop(code, None)
            return

        if order_no:
            # 즉시 매도 쿨다운 등록 (체결 전에도 재진입 차단)
            sell_cooldown_secs = self.settings.get("sell_cooldown_seconds", 300)
            self._sell_cooldown[code] = time.time() + sell_cooldown_secs
            self._save_sell_cooldown()

            # 매도 주문 접수 → pending_orders에 등록, 포지션에 selling 플래그
            self.pending_orders[order_no] = {
                "code": code,
                "type": "SELL",
                "price": order_price if order_price > 0 else self.tick_buffer.get_latest_price(code),
                "qty": qty,
                "time": time.time(),
                "signal": signal,
                "buy_price": buy_price,
            }
            if code in self.positions:
                self.positions[code]["selling"] = True
            print(f"[ScalpEngine] 📋 매도 주문 접수: {name}({code}) {qty}주 (주문번호={order_no})")

    # ── Pending Order Management ──────────────────────────

    def _manage_pending_orders(self):
        """미체결 주문 관리: 주문내역 API로 체결 확인 + 타임아웃 취소"""
        if not self.pending_orders:
            return

        now = time.time()

        # API 호출 빈도 제한 (3초마다)
        if hasattr(self, '_last_order_check') and now - self._last_order_check < 3:
            return
        self._last_order_check = now

        # 주문내역 조회
        order_map = {}
        try:
            orders = self.manager.get_order_status()
            order_map = {o.get('odno'): o for o in orders}
        except Exception as e:
            print(f"[ScalpEngine] 주문내역 조회 실패: {e}")
            # API 실패 시에도 타임아웃 처리는 진행

        timeout = 15  # 15초 타임아웃

        for odno in list(self.pending_orders.keys()):
            pending = self.pending_orders[odno]
            code = pending["code"]
            name = self.stock_names.get(code, code)
            elapsed = now - pending["time"]

            # 주문내역에서 체결 확인
            order_data = order_map.get(odno)
            if order_data:
                filled_qty = int(order_data.get('tot_ccld_qty', 0))
                if filled_qty > 0:
                    avg_price = float(order_data.get('avg_prvs', 0)) or pending["price"]

                    if pending["type"] == "BUY":
                        profile = pending.get("profile")
                        self.positions[code] = {
                            "qty": filled_qty,
                            "buy_price": avg_price,
                            "buy_time": pending["time"],
                            "order_no": odno,
                            "trailing_high": avg_price,
                            "profile": profile,
                        }
                        confidence = pending.get("confidence", 0)
                        self.trade_logger.log_scalp_buy(code, name, filled_qty, avg_price, confidence)
                        print(f"[ScalpEngine] ✅ 매수 체결: {name}({code}) "
                              f"{filled_qty}주 @ {avg_price:,.0f}원 (strategy={profile.name if profile else '?'})")
                        if self.discord:
                            self.discord.send(
                                f"📈 **SCALP BUY** {name}({code}) {filled_qty}주 @ {avg_price:,.0f}원\n"
                                f"신뢰도: {confidence:.3f} | 전략: {profile.name if profile else 'adaptive'}"
                            )

                    elif pending["type"] == "SELL":
                        buy_price = pending.get("buy_price", 0)
                        signal = pending.get("signal", "SCALP_SELL")
                        sell_info = self.trade_logger.log_scalp_sell(
                            code, name, filled_qty, avg_price, buy_price, signal
                        )
                        self.risk_manager.record_trade(sell_info["realized_pnl"])
                        self.positions.pop(code, None)

                        sell_cooldown_secs = self.settings.get("sell_cooldown_seconds", 300)
                        self._sell_cooldown[code] = now + sell_cooldown_secs
                        self._save_sell_cooldown()

                        print(f"[ScalpEngine] ✅ 매도 체결: {name}({code}) {filled_qty}주 @ {avg_price:,.0f}원 "
                              f"손익={sell_info['realized_pnl']:+,}원 ({sell_info['pnl_rate']:+.2f}%) "
                              f"| 재진입 쿨다운 {sell_cooldown_secs}s")
                        if self.discord:
                            self.discord.send(
                                f"⚡ **SCALP SELL ({signal})** {name}({code}) {filled_qty}주 @ {avg_price:,.0f}원\n"
                                f"실현손익: {sell_info['realized_pnl']:+,}원 ({sell_info['pnl_rate']:+.2f}%)"
                            )

                    del self.pending_orders[odno]
                    continue

            # 타임아웃 → 취소
            if elapsed >= timeout:
                print(f"[ScalpEngine] ⏰ 미체결 타임아웃: {name}({code}) "
                      f"주문번호={odno} ({elapsed:.1f}초)")
                try:
                    self.manager.cancel_order(odno, code, pending["qty"])
                except Exception as e:
                    print(f"[ScalpEngine] 주문 취소 실패 ({odno}): {e}")

                # 매도 pending이면 selling 플래그 해제
                if pending["type"] == "SELL":
                    pos = self.positions.get(code)
                    if pos:
                        pos.pop("selling", None)

                del self.pending_orders[odno]

    # ── Force Exit ──────────────────────────

    def _force_exit_all(self, signal="SCALP_SELL_EOD"):
        """전 포지션 시장가 청산"""
        for code in list(self.positions.keys()):
            pos = self.positions[code]
            name = self.stock_names.get(code, code)
            qty = pos["qty"]
            buy_price = pos["buy_price"]

            print(f"[ScalpEngine] 🔴 강제 청산: {name}({code}) {qty}주")

            try:
                order_no = self.manager.place_order(code, qty, 0, OrderType.SELL)
            except Exception as e:
                print(f"[ScalpEngine] 강제 청산 API 실패 ({name}): {e}")
                if self.discord:
                    self.discord.send(f"❌ **강제 청산 실패** {name}({code}) — 수동 확인 필요")
                continue

            if order_no:
                current_price = self.tick_buffer.get_latest_price(code)
                if current_price <= 0:
                    current_price = buy_price

                sell_info = self.trade_logger.log_scalp_sell(
                    code, name, qty, current_price, buy_price, signal
                )
                self.risk_manager.record_trade(sell_info["realized_pnl"])

        self.positions.clear()

        if self.discord:
            summary = self.risk_manager.get_daily_summary()
            self.discord.send(
                f"🔴 **전 포지션 청산 ({signal})**\n"
                f"일일 손익: {summary['daily_pnl']:+,}원 | 거래: {summary['trade_count']}건"
            )

    # ── Temperature ──────────────────────────

    def apply_temperature(self, temp_result):
        """온도 결과를 전략 + 선택기 + 리스크에 적용"""
        self.strategy.apply_temperature(temp_result)
        self.strategy_selector.apply_temperature(temp_result)
        self.risk_manager.apply_temperature(temp_result)

    # ── Session Management ──────────────────────────

    def reset_daily(self):
        """일일 리셋"""
        self.risk_manager.reset_daily()
        self.tick_buffer.reset_all()
        self.orderbook_analyzer.reset_all()
        self.candle_history.reset()
        self.positions.clear()
        self.pending_orders.clear()
        self._sell_cooldown.clear()
        self._order_cooldown.clear()
        self._low_composite_cycles.clear()
        self._save_sell_cooldown()  # 빈 상태로 초기화
        print("[ScalpEngine] 일일 리셋 완료")

    def get_status(self):
        """현재 상태 요약"""
        risk = self.risk_manager.get_daily_summary()
        return {
            "positions": len(self.positions),
            "target_codes": len(self.target_codes),
            "pending_orders": len(self.pending_orders),
            "strategy": self.strategy_selector.current_strategy_name(),
            "mode": self.strategy._get_mode(),
            "temperature": self.strategy.temperature_level,
            "confidence_threshold": self.strategy.confidence_threshold,
            **risk,
        }

    def print_status(self):
        """상태 출력"""
        status = self.get_status()
        print(f"\n{'='*50}")
        print(f"📊 스캘핑 상태")
        print(f"{'='*50}")
        print(f"  전략: {status['strategy']} | 모드: {status['mode']} | 온도: {status['temperature']}")
        print(f"  포지션: {status['positions']}개 | 타겟: {status['target_codes']}종목")
        print(f"  일일 손익: {status['daily_pnl']:+,}원 | 거래: {status['trade_count']}건")
        print(f"  연속손실: {status['consecutive_losses']} | 서킷: {status['circuit_broken']}")
        print(f"{'='*50}")
