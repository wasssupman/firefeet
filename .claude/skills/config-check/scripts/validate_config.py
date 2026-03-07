"""Firefeet Config Check — YAML 설정 정합성 검증 스크립트."""

import os
import sys

import yaml

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "config")

ROUND_TRIP_FEE = 0.21  # 왕복 수수료 %

results = {"pass": [], "warn": [], "fail": []}


def log_pass(msg):
    results["pass"].append(msg)


def log_warn(msg):
    results["warn"].append(msg)


def log_fail(msg):
    results["fail"].append(msg)


def load_yaml(filename):
    path = os.path.join(CONFIG_DIR, filename)
    if not os.path.exists(path):
        log_fail(f"{filename} 파일 없음")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        log_pass(f"{filename} 로드 성공")
        return data
    except yaml.YAMLError as e:
        log_fail(f"{filename} YAML 파싱 오류: {e}")
        return None


def check_secrets():
    path = os.path.join(CONFIG_DIR, "secrets.yaml")
    if not os.path.exists(path):
        log_warn("secrets.yaml 없음 (gitignore 대상이므로 정상일 수 있음)")
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for section in ["PROD", "PAPER"]:
            if section not in data:
                log_fail(f"secrets.yaml: {section} 섹션 없음")
            else:
                for key in ["APP_KEY", "APP_SECRET"]:
                    if key not in data[section]:
                        log_fail(f"secrets.yaml: {section}.{key} 없음")
        if "CANO" not in data:
            log_fail("secrets.yaml: CANO 없음")
        else:
            log_pass("secrets.yaml 필수 키 확인 완료")
    except Exception as e:
        log_fail(f"secrets.yaml 읽기 오류: {e}")


def check_scalping_triple_conflict(settings, strategies, rules):
    """3중 충돌 검증 — 최우선."""
    if not all([settings, strategies, rules]):
        return

    global_threshold = settings.get("default_confidence_threshold", 0)
    global_tp = settings.get("take_profit_pct", 0)
    global_sl = settings.get("stop_loss_pct", 0)

    for strat in strategies.get("strategies", []):
        name = strat.get("name", "unknown")
        strat_threshold = strat.get("confidence_threshold")
        strat_tp = strat.get("take_profit")
        strat_sl = strat.get("stop_loss")

        # conf threshold 충돌
        if strat_threshold is not None and strat_threshold != global_threshold:
            log_pass(f"[{name}] conf_threshold={strat_threshold} (전략 오버라이드, 글로벌={global_threshold})")
        elif strat_threshold is None:
            log_warn(f"[{name}] conf_threshold 미정의 → 글로벌 {global_threshold} 사용됨")

        # TP 수수료 바닥선
        tp = strat_tp if strat_tp is not None else global_tp
        if tp is not None and abs(tp) <= ROUND_TRIP_FEE:
            log_fail(f"[{name}] TP={tp}% ≤ 수수료 {ROUND_TRIP_FEE}% → 구조적 손실")
        elif tp is not None:
            log_pass(f"[{name}] TP={tp}% > 수수료 {ROUND_TRIP_FEE}%")

        # SL vs rules 정합성
        sl = strat_sl if strat_sl is not None else global_sl
        paper_rules = rules.get("mode", {}).get("paper", {}).get("per_trade", {})
        rules_max_loss = paper_rules.get("max_loss_pct", 999)
        if sl is not None and abs(sl) > rules_max_loss:
            log_warn(f"[{name}] SL={sl}% 이 rules max_loss_pct={rules_max_loss}%보다 넓음 → rules가 먼저 청산")


def check_temperature_profiles(temp_config):
    if not temp_config:
        return

    profiles = temp_config.get("strategy_profiles", {})
    expected_levels = ["HOT", "WARM", "NEUTRAL", "COOL", "COLD"]

    for level in expected_levels:
        if level not in profiles:
            log_fail(f"strategy_profiles: {level} 레벨 누락")
            return

    log_pass("strategy_profiles: 5개 레벨 모두 정의됨")

    # k 단조증가 (HOT→COLD)
    k_values = [profiles[l].get("k", 0) for l in expected_levels]
    if k_values == sorted(k_values):
        log_pass(f"k 값 단조증가: {k_values}")
    else:
        log_fail(f"k 값 단조증가 위반: {k_values} (HOT→COLD 순서)")

    # TP 단조감소 (HOT→COLD)
    tp_values = [profiles[l].get("take_profit", 0) for l in expected_levels]
    if tp_values == sorted(tp_values, reverse=True):
        log_pass(f"TP 값 단조감소: {tp_values}")
    else:
        log_warn(f"TP 값 단조감소 아님: {tp_values}")

    # level_thresholds 순서
    thresholds = temp_config.get("level_thresholds", {})
    if thresholds:
        th_values = [thresholds.get(l, 0) for l in ["HOT", "WARM", "NEUTRAL", "COOL"]]
        if th_values == sorted(th_values, reverse=True):
            log_pass(f"level_thresholds 순서 정상: {th_values}")
        else:
            log_fail(f"level_thresholds 순서 위반: {th_values}")


def check_risk_rules(rules, settings):
    if not rules:
        return

    real = rules.get("mode", {}).get("real", {})
    paper = rules.get("mode", {}).get("paper", {})

    # REAL이 PAPER보다 엄격한지
    real_max_loss = real.get("per_trade", {}).get("max_loss_amount", 0)
    paper_max_loss = paper.get("per_trade", {}).get("max_loss_amount", 0)
    if real_max_loss <= paper_max_loss:
        log_pass(f"REAL 건당한도({real_max_loss:,}) ≤ PAPER({paper_max_loss:,})")
    else:
        log_warn(f"REAL 건당한도({real_max_loss:,}) > PAPER({paper_max_loss:,}) — REAL이 더 느슨함")

    # 서킷브레이커 범위
    consec = real.get("daily_limits", {}).get("max_consecutive_losses", 0)
    if 3 <= consec <= 10:
        log_pass(f"서킷브레이커 연속손실={consec} (적정 범위)")
    else:
        log_warn(f"서킷브레이커 연속손실={consec} (권장 3~10)")

    # 일일손실한도 vs 예산
    if settings:
        budget = settings.get("scalping_budget", 0)
        daily_max = real.get("daily_limits", {}).get("max_daily_loss", 0)
        if budget > 0 and daily_max > 0:
            ratio = daily_max / budget * 100
            if ratio <= 10:
                log_pass(f"일일손실한도 {daily_max:,}원 = 예산의 {ratio:.1f}%")
            else:
                log_warn(f"일일손실한도 {daily_max:,}원 = 예산의 {ratio:.1f}% (10% 초과)")


def check_time_settings(strategies, settings):
    if not strategies:
        return

    lunch_start = strategies.get("lunch_block_start", "")
    lunch_end = strategies.get("lunch_block_end", "")
    if lunch_start and lunch_end:
        if lunch_start < lunch_end:
            log_pass(f"점심차단 {lunch_start}~{lunch_end} 순서 정상")
        else:
            log_fail(f"점심차단 {lunch_start}~{lunch_end} 순서 역전")

    if settings:
        eod = settings.get("eod_exit_time", "")
        if eod and isinstance(eod, str) and len(eod) == 4:
            log_pass(f"EOD 청산 시각: {eod}")
        elif eod:
            log_warn(f"eod_exit_time={eod} — HHMM 문자열이 아닐 수 있음")


def main():
    print("🔍 Firefeet Config Validator\n")

    # 파일 로드
    check_secrets()
    scalp_settings = load_yaml("scalping_settings.yaml")
    scalp_strategies = load_yaml("scalping_strategies.yaml")
    scalp_rules = load_yaml("scalping_rules.yaml")
    temp_config = load_yaml("temperature_config.yaml")
    load_yaml("trading_settings.yaml")
    load_yaml("trading_rules.yaml")
    load_yaml("screener_settings.yaml")
    load_yaml("deep_analysis.yaml")

    # 검증
    print("\n--- 3중 충돌 검증 ---")
    check_scalping_triple_conflict(scalp_settings, scalp_strategies, scalp_rules)

    print("\n--- 온도 프로필 검증 ---")
    check_temperature_profiles(temp_config)

    print("\n--- 리스크 룰 검증 ---")
    check_risk_rules(scalp_rules, scalp_settings)

    print("\n--- 시간 설정 검증 ---")
    check_time_settings(scalp_strategies, scalp_settings)

    # 결과 출력
    print("\n" + "=" * 60)
    print("📋 검증 결과 요약")
    print("=" * 60)

    for msg in results["fail"]:
        print(f"❌ FAIL  | {msg}")
    for msg in results["warn"]:
        print(f"⚠️  WARN  | {msg}")
    for msg in results["pass"]:
        print(f"✅ PASS  | {msg}")

    total = len(results["pass"]) + len(results["warn"]) + len(results["fail"])
    print(f"\n합계: {len(results['pass'])} PASS, {len(results['warn'])} WARN, {len(results['fail'])} FAIL / {total} 항목")

    if results["fail"]:
        print("\n🚨 FAIL 항목이 있습니다. 실매매 전 반드시 수정하세요.")
        sys.exit(1)
    elif results["warn"]:
        print("\n⚠️  경고 항목이 있습니다. 확인을 권장합니다.")
    else:
        print("\n✅ 모든 검증 통과!")


if __name__ == "__main__":
    main()
