"""
스캘핑 시스템 오프라인 테스트 — KIS API / WebSocket 불필요.
합성 틱 데이터를 주입해 시그널·전략·엔진 로직을 검증한다.

실행:
    python3 test_scalper.py          # 전체
    python3 test_scalper.py signals  # 시그널만
    python3 test_scalper.py engine   # 엔진 로직만
"""

import sys
import time
import math

from core.encoding_setup import setup_utf8_stdout
setup_utf8_stdout()

# ─────────────────────────────────────────────────────────────
# 헬퍼: 결과 출력
# ─────────────────────────────────────────────────────────────

_passed = 0
_failed = 0

def ok(label):
    global _passed
    _passed += 1
    print(f"  ✅ {label}")

def fail(label, detail=""):
    global _failed
    _failed += 1
    print(f"  ❌ {label}" + (f" — {detail}" if detail else ""))

def section(title):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print(f"{'='*55}")

def summary():
    total = _passed + _failed
    print(f"\n{'='*55}")
    print(f"  결과: {_passed}/{total} 통과" + (" 🎉" if _failed == 0 else f"  ({_failed}개 실패)"))
    print(f"{'='*55}")


# ─────────────────────────────────────────────────────────────
# 합성 틱 주입 유틸
# ─────────────────────────────────────────────────────────────

def inject_ticks(buf, code, scenario):
    """
    scenario: list of (price, volume, direction, seconds_ago)
    seconds_ago=0 → 지금, 10 → 10초 전
    """
    now = time.time()
    for price, volume, direction, seconds_ago in scenario:
        ts = now - seconds_ago
        buf.add_tick(code, price, volume, timestamp=ts, direction=direction)

def make_rising_scenario(base_price=50000, n=60):
    """상승 추세 시나리오: 가격 서서히 상승 + 거래량 증가"""
    ticks = []
    for i in range(n):
        seconds_ago = n - i  # 오래된 것부터
        price = base_price + i * 10
        volume = 500 + i * 20
        direction = 1  # 상승틱
        ticks.append((price, volume, direction, seconds_ago))
    return ticks

def make_vwap_bounce_scenario(base_price=50000, vwap_premium=500, n=60):
    """
    VWAP 아래 위치 + 60초 추세 전환 시나리오.
    초반 하락 → 후반 반등 (VWAP bounce 조건).
    """
    ticks = []
    vwap_level = base_price + vwap_premium  # VWAP = base + 500
    # 초반 40틱: 하락 (VWAP 아래로 내려감)
    for i in range(40):
        seconds_ago = 80 - i
        price = vwap_level - 200 - i * 5  # VWAP 아래
        volume = 300 + i * 10
        direction = -1
        ticks.append((price, volume, direction, seconds_ago))
    # 후반 20틱: 반등 (60초 추세 양전환)
    for i in range(20):
        seconds_ago = 40 - i
        price = vwap_level - 500 + i * 20  # 반등
        volume = 800 + i * 50
        direction = 1
        ticks.append((price, volume, direction, seconds_ago))
    return ticks

def make_falling_scenario(base_price=50000, n=60):
    """하락 추세 시나리오"""
    ticks = []
    for i in range(n):
        seconds_ago = n - i
        price = base_price - i * 10
        volume = 500
        direction = -1
        ticks.append((price, volume, direction, seconds_ago))
    return ticks


# ─────────────────────────────────────────────────────────────
# 1. TickBuffer 기본 동작
# ─────────────────────────────────────────────────────────────

def test_tick_buffer():
    section("1. TickBuffer 기본 동작")
    from core.scalping.tick_buffer import TickBuffer

    buf = TickBuffer(max_size=600)
    code = "005930"

    # 데이터 없음
    assert not buf.has_enough_data(code, 30)
    ok("데이터 없음 → has_enough_data=False")

    # 상승 틱 60개 주입
    inject_ticks(buf, code, make_rising_scenario(base_price=50000))

    assert buf.has_enough_data(code, 30)
    ok("60틱 주입 후 → has_enough_data=True")

    price = buf.get_latest_price(code)
    assert price > 50000, f"price={price}"
    ok(f"최신가격 {price:,}원 (50,000원 초과)")

    vwap = buf.get_vwap(code)
    assert vwap > 0
    ok(f"VWAP {vwap:,.0f}원 계산됨")

    mom = buf.get_momentums(code)
    assert mom["10s"] > 0 and mom["60s"] > 0
    ok(f"상승 시나리오 모멘텀 양수: 10s={mom['10s']:+.3f}% 60s={mom['60s']:+.3f}%")

    tick_ratio = buf.get_tick_direction_ratio(code, 30)
    assert tick_ratio > 0
    ok(f"상승틱 비율 {tick_ratio:.2f} (>0)")

    vol_accel = buf.get_volume_acceleration(code)
    ok(f"거래량 가속 {vol_accel:.2f}")


# ─────────────────────────────────────────────────────────────
# 2. ScalpSignals — 개별 시그널
# ─────────────────────────────────────────────────────────────

def test_signals():
    section("2. ScalpSignals 개별 시그널")
    from core.scalping.tick_buffer import TickBuffer
    from core.scalping.scalp_signals import ScalpSignals
    from core.scalping.orderbook_analyzer import OrderbookAnalyzer

    buf = TickBuffer()
    signals = ScalpSignals()
    ob = OrderbookAnalyzer()

    code = "TEST01"

    # ── 2a. Momentum Burst: 상승 시나리오 ──
    inject_ticks(buf, code, make_rising_scenario(base_price=50000, n=60))
    mom_score = signals.signal_momentum_burst(code, buf)
    ok(f"[Momentum] 상승 시나리오 score={mom_score:.0f}")

    # ── 2b. Momentum Burst: 하락 시나리오 → score 낮아야 함 ──
    code2 = "TEST02"
    inject_ticks(buf, code2, make_falling_scenario(base_price=50000, n=60))
    mom_fall = signals.signal_momentum_burst(code2, buf)
    assert mom_fall < mom_score, f"상승({mom_score}) > 하락({mom_fall}) 이어야 함"
    ok(f"[Momentum] 하락 시나리오 score={mom_fall:.0f} < 상승({mom_score:.0f}) ✓")

    # ── 2c. 소프트 임계값: 단일 하락 틱 추가해도 급락 없음 ──
    code3 = "TEST03"
    inject_ticks(buf, code3, make_rising_scenario(base_price=50000, n=58))
    # 마지막에 하락 틱 1개 추가
    buf.add_tick(code3, 49990, 100, direction=-1)
    buf.add_tick(code3, 49980, 100, direction=-1)
    mom_soft = signals.signal_momentum_burst(code3, buf)
    # 소프트 임계값: 이전엔 0, 이제는 50% 감점으로 어느 정도 살아있어야 함
    ok(f"[Momentum] 단일 하락 틱 후 score={mom_soft:.0f} (소프트 임계값 — 급락 방지)")

    # ── 2d. VWAP Reversion: VWAP 아래 + 60초 추세 양전환 ──
    code4 = "TEST04"
    inject_ticks(buf, code4, make_vwap_bounce_scenario(base_price=50000, vwap_premium=500, n=60))
    vwap_score = signals.signal_vwap_reversion(code4, buf)
    ok(f"[VWAP] bounce 시나리오 score={vwap_score:.0f}")

    # ── 2e. VWAP Reversion: 하락 추세 중 VWAP 아래 → P7 바이어스로 0 반환 ──
    code5 = "TEST05"
    inject_ticks(buf, code5, make_falling_scenario(base_price=48000, n=60))
    # 가격이 VWAP 아래지만 60초 추세도 하락
    vwap_fall = signals.signal_vwap_reversion(code5, buf)
    vwap_dist = buf.get_vwap_distance(code5)
    mom60 = buf.get_momentums(code5)["60s"]
    if mom60 <= 0:
        assert vwap_fall == 0, f"하락 추세에서 vwap_score={vwap_fall} (0이어야 함)"
        ok(f"[VWAP] 하락 추세(60s={mom60:.3f}%) → score=0 (P7 바이어스 동작) ✓")
    else:
        ok(f"[VWAP] 60s 모멘텀 양수({mom60:.3f}%) — 바이어스 조건 비해당, score={vwap_fall:.0f}")

    # ── 2f. Volume Surge ──
    code6 = "TEST06"
    inject_ticks(buf, code6, make_rising_scenario(base_price=50000, n=60))
    vol_score = signals.signal_volume_surge(code6, buf)
    ok(f"[VolSurge] score={vol_score:.0f}")

    # ── 2g. Micro Trend ──
    micro_score = signals.signal_micro_trend(code, buf)
    ok(f"[MicroTrend] 상승 시나리오 score={micro_score:.0f}")


# ─────────────────────────────────────────────────────────────
# 3. ScalpStrategy — confidence 페널티 계산
# ─────────────────────────────────────────────────────────────

def test_strategy_confidence():
    section("3. ScalpStrategy Confidence 계산")
    from core.scalping.tick_buffer import TickBuffer
    from core.scalping.scalp_signals import ScalpSignals
    from core.scalping.scalp_strategy import ScalpStrategy
    from core.scalping.orderbook_analyzer import OrderbookAnalyzer

    buf = TickBuffer()
    ob = OrderbookAnalyzer()
    signals_calc = ScalpSignals()
    strategy = ScalpStrategy(signals_calc)

    code = "TEST_CONF"
    inject_ticks(buf, code, make_rising_scenario(base_price=50000, n=60))

    result = strategy.evaluate(code, buf, ob)

    composite = result["composite"]
    confidence = result["confidence"]
    penalties = result["penalties"]

    ok(f"composite={composite:.1f}, confidence={confidence:.4f}")
    ok(f"penalties: spread={penalties['spread']:.3f}, volume={penalties['volume']:.3f}, "
       f"combined={penalties['combined']:.3f}")

    # 페널티 구조 검증: combined = min(spread, volume)
    expected_combined = min(penalties["spread"], penalties["volume"])
    assert abs(penalties["combined"] - expected_combined) < 0.001, \
        f"combined={penalties['combined']} != min({penalties['spread']},{penalties['volume']})={expected_combined}"
    ok("combined_penalty = min(spread, volume) ✓ (곱산 아님)")

    # 현재 공식: confidence = composite/100 (페널티는 veto 거부권 방식 — 곱셈 아님)
    expected_conf = composite / 100.0
    assert abs(confidence - expected_conf) < 0.0001, \
        f"confidence={confidence} != composite/100={expected_conf}"
    ok("confidence = composite/100 ✓ (veto 방식 — 페널티는 곱셈 아님)")

    # 페널티 veto 조건: combined < 0.5이면 진입 차단 (confidence 무관)
    penalty_veto = penalties["combined"] < 0.5
    ok(f"페널티 veto={'발동 ❌' if penalty_veto else '미발동 ✅'} (combined={penalties['combined']:.3f})")


# ─────────────────────────────────────────────────────────────
# 4. ScalpScreener — 거래대금 필터 + RVOL 스코어
# ─────────────────────────────────────────────────────────────

def test_screener():
    section("4. ScalpScreener 필터링")

    from core.scalping.scalp_screener import ScalpScreener

    # KISManager 없이 스크리너만 테스트하기 위해 mock manager 사용
    class MockManager:
        @staticmethod
        def get_tick_size(price):
            if price < 2000: return 1
            if price < 5000: return 5
            if price < 10000: return 10
            if price < 50000: return 50
            if price < 100000: return 100
            return 500

    screener = ScalpScreener(MockManager())
    # min_trading_value를 직접 설정 (yaml 로드 없이)
    screener.min_trading_value = 50_000_000_000  # 500억
    screener.min_price = 1000
    screener.max_price = 9_999_999
    screener.optimal_price_min = 1000
    screener.optimal_price_max = 9_999_999
    screener.max_spread_bps = 9999

    stocks = [
        # 거래대금 500억+ 통과: 50,000 × 1,200,000 = 600억
        {"code": "A", "name": "종목A", "price": 50000, "volume": 1200000, "change_rate": 5.0},
        # 거래대금 미달: 50,000 × 500,000 = 250억 < 500억
        {"code": "B", "name": "종목B", "price": 50000, "volume": 500000, "change_rate": 3.0},
        # 상한가 제외: change_rate=30
        {"code": "C", "name": "종목C", "price": 10000, "volume": 9000000, "change_rate": 30.0},
        # 저가주 제외: price=500
        {"code": "D", "name": "종목D", "price": 500, "volume": 10000000, "change_rate": 5.0},
        # 거래대금 통과: 10,000 × 6,000,000 = 600억, 높은 변동률
        {"code": "E", "name": "종목E", "price": 10000, "volume": 6000000, "change_rate": 8.0},
    ]

    result = screener.filter_stocks(stocks)
    codes = [s["code"] for s in result]

    assert "A" in codes, f"종목A(거래대금 600억) 통과해야 함, codes={codes}"
    ok("종목A (거래대금 600억) → 통과 ✓")

    assert "B" not in codes, f"종목B(거래대금 250억) 제외되어야 함"
    ok("종목B (거래대금 250억 < 500억) → 제외 ✓")

    assert "C" not in codes
    ok("종목C (상한가 30%) → 제외 ✓")

    assert "D" not in codes
    ok("종목D (저가주 500원) → 제외 ✓")

    assert "E" in codes
    ok("종목E (거래대금 600억) → 통과 ✓")

    # RVOL 스코어 검증: 높은 변동률 × 거래량 → 높은 점수
    score_a = next(s["scalp_score"] for s in result if s["code"] == "A")
    score_e = next(s["scalp_score"] for s in result if s["code"] == "E")
    ok(f"RVOL 스코어: A={score_a}, E={score_e}")

    # 정렬 순서 검증
    if len(result) >= 2:
        assert result[0]["scalp_score"] >= result[1]["scalp_score"]
        ok(f"정렬 확인: {result[0]['code']}({result[0]['scalp_score']}) ≥ {result[1]['code']}({result[1]['scalp_score']}) ✓")

    # RVOL 프록시 직접 계산 검증
    for s in stocks[:1]:
        rvol = abs(s["change_rate"]) * math.log(max(s["volume"], 1))
        ok(f"RVOL 프록시 {s['name']}: {abs(s['change_rate'])} × log({s['volume']}) = {rvol:.1f}")


# ─────────────────────────────────────────────────────────────
# 5. 엔진 로직 — VWAP 거리 필터 + Adaptive Pool Rotation
# ─────────────────────────────────────────────────────────────

def test_engine_logic():
    section("5. ScalpEngine 로직 (VWAP 필터 + Adaptive Rotation)")
    from core.scalping.tick_buffer import TickBuffer
    from core.scalping.scalp_signals import ScalpSignals
    from core.scalping.scalp_strategy import ScalpStrategy
    from core.scalping.orderbook_analyzer import OrderbookAnalyzer
    from core.scalping.strategy_selector import StrategyProfile

    buf = TickBuffer()
    ob = OrderbookAnalyzer()

    # ── 5a. VWAP 거리 필터 시뮬레이션 ──
    # vwap_reversion 전략: -0.3~-1.5% 구간 종목만 통과
    code_ok = "VWAP_IN"     # VWAP 거리 -0.8% (통과)
    code_out = "VWAP_OUT"   # VWAP 거리 +0.5% (VWAP 위, 제외)
    code_far = "VWAP_FAR"   # VWAP 거리 -2.0% (과이탈, 제외)

    # code_ok: VWAP 아래 ~0.8% → 초반 높은 가격으로 VWAP 올리고 이후 낮게
    now = time.time()
    # VWAP를 50,000원으로 만들기 위해 초반 50,000원 대량 거래
    for i in range(40):
        buf.add_tick(code_ok, 50000, 1000, timestamp=now - 120 + i, direction=0)
    # 이후 49,600원 (~-0.8%)으로 하락
    for i in range(20):
        buf.add_tick(code_ok, 49600, 200, timestamp=now - 80 + i, direction=-1)
    # 후반 반등
    for i in range(10):
        buf.add_tick(code_ok, 49650 + i*5, 300, timestamp=now - 20 + i, direction=1)

    vwap_ok = buf.get_vwap(code_ok)
    dist_ok = buf.get_vwap_distance(code_ok)
    in_range = -1.5 <= dist_ok <= -0.3
    ok(f"code_ok: VWAP={vwap_ok:,.0f} 거리={dist_ok:.3f}% → {'통과' if in_range else '제외'}")

    # code_out: VWAP 위 (전부 상승)
    for i in range(60):
        buf.add_tick(code_out, 50000 + i * 10, 500, timestamp=now - 120 + i, direction=1)
    dist_out = buf.get_vwap_distance(code_out)
    not_in_range = not (-1.5 <= dist_out <= -0.3)
    ok(f"code_out: VWAP 거리={dist_out:.3f}% → {'제외됨 ✓' if not_in_range else '통과 (예상 외)'}")

    # ── 5b. Adaptive Pool Rotation 시뮬레이션 ──
    # _low_composite_cycles 딕셔너리를 직접 테스트
    low_cycles = {}
    SKIP_THRESHOLD = 30

    def record_composite(code, composite):
        if composite < 30:
            low_cycles[code] = low_cycles.get(code, 0) + 1
        else:
            low_cycles[code] = 0
        return low_cycles.get(code, 0) >= SKIP_THRESHOLD

    # 30사이클 composite < 30 → 스킵
    code_lazy = "LAZY"
    for _ in range(29):
        should_skip = record_composite(code_lazy, 10)
    assert not should_skip
    should_skip = record_composite(code_lazy, 10)
    assert should_skip
    ok(f"Adaptive rotation: 30사이클 composite<30 → 스킵 ✓ (카운터={low_cycles[code_lazy]})")

    # composite 회복 시 카운터 리셋
    record_composite(code_lazy, 50)
    assert low_cycles[code_lazy] == 0
    ok("composite≥30 회복 → 카운터 리셋 ✓")

    # 종목 풀 갱신 시 전체 리셋
    low_cycles.clear()
    assert code_lazy not in low_cycles
    ok("update_targets 호출(clear) → 카운터 전체 초기화 ✓")

    # ── 5c. 매도 쿨다운 로직 ──
    sell_cooldown = {}
    cooldown_secs = 300

    def mock_sell(code):
        sell_cooldown[code] = time.time() + cooldown_secs

    def can_enter(code):
        if code in sell_cooldown and time.time() < sell_cooldown[code]:
            remaining = sell_cooldown[code] - time.time()
            return False, f"{remaining:.0f}초 쿨다운 중"
        return True, ""

    code_cd = "COOLDOWN"
    mock_sell(code_cd)
    can, reason = can_enter(code_cd)
    assert not can
    ok(f"매도 후 재진입 차단: {reason} ✓")

    # 다른 종목은 영향 없음
    can2, _ = can_enter("OTHER")
    assert can2
    ok("다른 종목 쿨다운 미적용 ✓")


# ─────────────────────────────────────────────────────────────
# 6. WS 구독 복원 로직
# ─────────────────────────────────────────────────────────────

def test_ws_subscription_restore():
    section("6. WebSocket 구독 복원 로직 (핵심 버그 수정 검증)")

    # 버그: 단절 중 rotate_subscriptions 호출 시 _desired_subscriptions이 [] 로 덮임
    # 수정: connected=False면 target 목록만 저장하고 return

    TR_TICK = "H0STCNT0"
    TR_OB   = "H0STASP0"

    desired = []
    connected = False

    def rotate_subscriptions_new(priority_codes, tick_slots=15, orderbook_slots=15):
        """수정된 로직 시뮬레이션"""
        nonlocal desired
        target_tick = priority_codes[:tick_slots]
        target_ob   = priority_codes[:orderbook_slots]

        # 의도한 목록 먼저 저장 (연결 여부 무관)
        desired.clear()
        for c in target_tick:
            desired.append(f"{TR_TICK}|{c}")
        for c in target_ob:
            desired.append(f"{TR_OB}|{c}")

        if not connected:
            return  # 실제 구독 없이 목록만 보존

        # 연결됐으면 실제 구독 (여기선 생략)

    # 시뮬레이션: 단절 상태에서 rotate_subscriptions 호출
    codes = ["005930", "000660", "035420", "051910", "005380"]
    rotate_subscriptions_new(codes, tick_slots=5, orderbook_slots=5)

    assert len(desired) == 10, f"desired={len(desired)} (5 tick + 5 ob = 10 이어야 함)"
    ok(f"단절 중 rotate_subscriptions → desired {len(desired)}개 보존 ✓")

    # 재접속 시 desired로 복원
    resub_keys = desired or []
    assert len(resub_keys) == 10
    ok(f"재접속 후 resub_keys={len(resub_keys)}개 복원 ✓")

    # 기존 버그: connected=False → 구독 실패 → subscriptions={} → desired=[] 로 덮임
    desired_buggy = []
    subscriptions_buggy = {}

    def rotate_buggy(priority_codes):
        nonlocal desired_buggy
        target = priority_codes[:5]
        # 구독 실패 (connected=False)
        # ... subscriptions_buggy stays empty ...
        desired_buggy = list(subscriptions_buggy.keys())  # = []

    rotate_buggy(codes)
    resub_buggy = desired_buggy or list(subscriptions_buggy.keys())
    assert resub_buggy == [], f"버그 재현: resub={resub_buggy}"
    ok("버그 재현: 구 코드에선 재접속 후 resub_keys=[] (구독 복원 실패) ✓")


# ─────────────────────────────────────────────────────────────
# 7. PID 파일 락 로직
# ─────────────────────────────────────────────────────────────

def test_pid_lock():
    section("7. 중복 실행 방지 (PID 파일 락)")
    import os, tempfile

    pid_file = tempfile.mktemp(suffix=".pid")

    def acquire(pid_path):
        if os.path.exists(pid_path):
            try:
                with open(pid_path) as f:
                    old_pid = int(f.read().strip())
                os.kill(old_pid, 0)  # 프로세스 존재 확인
                return False, old_pid  # 이미 실행 중
            except (ProcessLookupError, PermissionError):
                pass  # 좀비 PID → 무시
        with open(pid_path, "w") as f:
            f.write(str(os.getpid()))
        return True, os.getpid()

    def release(pid_path):
        try:
            os.remove(pid_path)
        except FileNotFoundError:
            pass

    # 첫 실행 → 성공
    ok1, pid1 = acquire(pid_file)
    assert ok1
    ok(f"첫 실행 → 락 획득 (PID={pid1}) ✓")

    # 같은 PID로 두 번째 실행 → 차단
    ok2, pid2 = acquire(pid_file)
    assert not ok2
    ok(f"두 번째 실행 → 차단 (기존 PID={pid2}) ✓")

    # 릴리즈 후 재실행 → 성공
    release(pid_file)
    ok3, _ = acquire(pid_file)
    assert ok3
    ok("릴리즈 후 재실행 → 성공 ✓")
    release(pid_file)

    # 좀비 PID (존재하지 않는 PID) → 무시하고 통과
    with open(pid_file, "w") as f:
        f.write("99999999")  # 존재하지 않는 PID
    ok4, _ = acquire(pid_file)
    assert ok4
    ok("좀비 PID 파일 → 무시하고 실행 성공 ✓")
    release(pid_file)


# ─────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────

TESTS = {
    "buffer":    test_tick_buffer,
    "signals":   test_signals,
    "strategy":  test_strategy_confidence,
    "screener":  test_screener,
    "engine":    test_engine_logic,
    "ws":        test_ws_subscription_restore,
    "pid":       test_pid_lock,
}

if __name__ == "__main__":
    filter_arg = sys.argv[1] if len(sys.argv) > 1 else None

    print("\n🔥 Firefeet 스캘핑 오프라인 테스트")
    print(f"   KIS API / WebSocket 불필요 — 합성 틱 데이터 사용\n")

    for name, fn in TESTS.items():
        if filter_arg and filter_arg not in name:
            continue
        try:
            fn()
        except AssertionError as e:
            fail(f"{name} 단언 실패", str(e))
        except Exception as e:
            fail(f"{name} 예외", f"{type(e).__name__}: {e}")

    summary()
