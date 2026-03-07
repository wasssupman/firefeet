"""스캘핑 테스트용 헬퍼: TickBuffer/OrderbookAnalyzer 데이터 주입 + 팩토리."""

import time
from core.scalping.tick_buffer import TickBuffer
from core.scalping.orderbook_analyzer import OrderbookAnalyzer
from core.scalping.strategy_selector import StrategyProfile
from core.technical.overlay import TAOverlay


def inject_ticks(tick_buffer, code, prices, volumes=None, directions=None):
    """TickBuffer에 가상 틱 시퀀스 주입 (30+ 틱으로 has_enough_data 충족)."""
    n = len(prices)
    if volumes is None:
        volumes = [1000] * n
    if directions is None:
        directions = [1] * n
    now = time.time()
    for i in range(n):
        tick_buffer.add_tick(
            code, prices[i], volumes[i],
            timestamp=now - (n - i) * 0.5,
            direction=directions[i],
        )


def inject_orderbook(ob_analyzer, code, bid_prices, bid_volumes, ask_prices, ask_volumes):
    """OrderbookAnalyzer에 가상 호가 주입."""
    total_bid = sum(bid_volumes)
    total_ask = sum(ask_volumes)
    ob_analyzer.update({
        "code": code,
        "total_bid_volume": total_bid,
        "total_ask_volume": total_ask,
        "bid_prices": bid_prices,
        "ask_prices": ask_prices,
        "bid_volumes": bid_volumes,
        "ask_volumes": ask_volumes,
    })


def make_strategy_profile(name="momentum_scalp", conf=0.35, tp=1.2, sl=-0.5,
                           max_hold=180, weights=None):
    """테스트용 StrategyProfile 생성."""
    if weights is None:
        weights = {
            "vwap_reversion": 25,
            "orderbook_pressure": 25,
            "momentum_burst": 20,
            "volume_surge": 15,
            "micro_trend": 15,
        }
    return StrategyProfile(
        name=name,
        weights=weights,
        take_profit=tp,
        stop_loss=sl,
        confidence_threshold=conf,
        max_hold_seconds=max_hold,
    )


def make_ta_overlay(bb_position=0.5, nearest_resistance=0,
                    resistance_distance_pct=1.0,
                    suggested_tp=0.0, suggested_sl=0.0,
                    bb_exit_threshold=0.8):
    """테스트용 TAOverlay 생성."""
    return TAOverlay(
        bb_position=bb_position,
        nearest_resistance=nearest_resistance,
        resistance_distance_pct=resistance_distance_pct,
        suggested_tp=suggested_tp,
        suggested_sl=suggested_sl,
        bb_exit_threshold=bb_exit_threshold,
    )


def make_tick_buffer_with_data(code="005930", n=50, base_price=50000,
                                volume=1000, direction=1):
    """데이터가 채워진 TickBuffer 반환."""
    buf = TickBuffer(max_size=600)
    prices = [base_price + i * 10 for i in range(n)]
    inject_ticks(buf, code, prices,
                 volumes=[volume] * n,
                 directions=[direction] * n)
    return buf


def make_orderbook_with_data(code="005930", spread_bps=10, imbalance=0.3):
    """데이터가 채워진 OrderbookAnalyzer 반환."""
    oba = OrderbookAnalyzer()
    best_bid = 50000
    best_ask = int(best_bid * (1 + spread_bps / 10000))
    bid_vol = int(5000 * (1 + imbalance))
    ask_vol = int(5000 * (1 - imbalance))
    inject_orderbook(
        oba, code,
        bid_prices=[best_bid, best_bid - 50, best_bid - 100],
        bid_volumes=[bid_vol, bid_vol - 200, bid_vol - 400],
        ask_prices=[best_ask, best_ask + 50, best_ask + 100],
        ask_volumes=[ask_vol, ask_vol - 200, ask_vol - 400],
    )
    return oba
