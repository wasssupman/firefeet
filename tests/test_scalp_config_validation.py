"""설정 파일 일관성 검증 테스트 — 배포 전 필수 실행."""

import pytest
import yaml
import os

# 프로젝트 루트의 실제 config 파일 사용
CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")


def _load_yaml(filename):
    path = os.path.join(CONFIG_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def scalping_settings():
    return _load_yaml("scalping_settings.yaml")


@pytest.fixture(scope="module")
def scalping_rules():
    return _load_yaml("scalping_rules.yaml")


@pytest.fixture(scope="module")
def scalping_strategies():
    return _load_yaml("scalping_strategies.yaml")


class TestTPExceedsFee:
    """모든 TP > 왕복 수수료 0.21%."""

    def test_settings_tp(self, scalping_settings):
        tp = scalping_settings.get("take_profit_pct", 0)
        assert tp > 0.21, f"settings TP {tp}% <= 수수료 0.21%"

    def test_strategies_tp(self, scalping_strategies):
        for strat in scalping_strategies.get("strategies", []):
            tp = strat.get("take_profit", 0)
            assert tp > 0.21, f"{strat['name']} TP {tp}% <= 수수료 0.21%"

        adaptive = scalping_strategies.get("adaptive", {})
        if adaptive:
            tp = adaptive.get("take_profit", 0)
            assert tp > 0.21, f"adaptive TP {tp}% <= 수수료 0.21%"

    def test_rules_temperature_tp(self, scalping_rules):
        overrides = scalping_rules.get("temperature_overrides", {})
        for level, cfg in overrides.items():
            tp = cfg.get("take_profit_pct", 0)
            if tp > 0:
                assert tp > 0.21, f"온도 {level} TP {tp}% <= 수수료 0.21%"


class TestTemperatureOverrides:
    """HOT~COLD 5개 레벨 모두 정의."""

    EXPECTED_LEVELS = ["HOT", "WARM", "NEUTRAL", "COOL", "COLD"]

    def test_all_levels_defined(self, scalping_rules):
        overrides = scalping_rules.get("temperature_overrides", {})
        for level in self.EXPECTED_LEVELS:
            assert level in overrides, f"온도 레벨 {level} 미정의"

    def test_confidence_defined(self, scalping_rules):
        overrides = scalping_rules.get("temperature_overrides", {})
        for level in self.EXPECTED_LEVELS:
            cfg = overrides[level]
            assert "confidence" in cfg, f"{level}: confidence 미정의"
            assert 0 < cfg["confidence"] < 1, f"{level}: confidence={cfg['confidence']} 범위 이상"

    def test_max_positions_defined(self, scalping_rules):
        overrides = scalping_rules.get("temperature_overrides", {})
        for level in self.EXPECTED_LEVELS:
            cfg = overrides[level]
            assert "max_positions" in cfg, f"{level}: max_positions 미정의"
            assert cfg["max_positions"] >= 1, f"{level}: max_positions < 1"


class TestWeightsSum:
    """시그널 가중치 합 == 100."""

    def test_settings_weights(self, scalping_settings):
        weights = scalping_settings.get("signal_weights", {})
        if weights:
            total = sum(weights.values())
            assert total == 100, f"settings signal_weights 합={total}"

    def test_strategy_weights(self, scalping_strategies):
        for strat in scalping_strategies.get("strategies", []):
            weights = strat.get("signal_weights", {})
            total = sum(weights.values())
            assert total == 100, f"{strat['name']} signal_weights 합={total}"

        adaptive = scalping_strategies.get("adaptive", {})
        if adaptive:
            weights = adaptive.get("signal_weights", {})
            total = sum(weights.values())
            assert total == 100, f"adaptive signal_weights 합={total}"


class TestLunchBlock:
    """점심 차단 구간 검증."""

    def test_lunch_block_format(self, scalping_strategies):
        start = scalping_strategies.get("lunch_block_start", "")
        end = scalping_strategies.get("lunch_block_end", "")

        assert len(start) == 4, f"lunch_block_start '{start}' HHMM 아님"
        assert len(end) == 4, f"lunch_block_end '{end}' HHMM 아님"
        assert start.isdigit(), f"lunch_block_start '{start}' 숫자 아님"
        assert end.isdigit(), f"lunch_block_end '{end}' 숫자 아님"

    def test_lunch_start_before_end(self, scalping_strategies):
        start = scalping_strategies.get("lunch_block_start", "1200")
        end = scalping_strategies.get("lunch_block_end", "1330")
        assert start < end, f"lunch start={start} >= end={end}"


class TestTimeRanges:
    """전략 시간대가 장중(0900~1530) 이내."""

    def test_strategy_times_within_market(self, scalping_strategies):
        for strat in scalping_strategies.get("strategies", []):
            for rng in strat.get("active_times", []):
                start = rng["start"]
                end = rng["end"]
                assert start >= "0900", f"{strat['name']} start={start} < 0900"
                assert end <= "1530", f"{strat['name']} end={end} > 1530"
                assert start < end, f"{strat['name']} start={start} >= end={end}"

    def test_time_restrictions_within_market(self, scalping_rules):
        for mode_name in ["real", "paper"]:
            mode_cfg = scalping_rules.get("mode", {}).get(mode_name, {})
            time_rules = mode_cfg.get("time_restrictions", {})
            if time_rules:
                no_before = time_rules.get("no_entry_before", "0900")
                no_after = time_rules.get("no_entry_after", "1530")
                force_exit = time_rules.get("force_exit_by", "1530")
                assert no_before >= "0900", f"{mode_name} no_entry_before={no_before}"
                assert no_after <= "1530", f"{mode_name} no_entry_after={no_after}"
                assert force_exit <= "1530", f"{mode_name} force_exit_by={force_exit}"
                assert no_before < no_after, f"{mode_name} before >= after"


class TestModeConsistency:
    """real/paper 모드 구조 일관성."""

    def test_both_modes_defined(self, scalping_rules):
        modes = scalping_rules.get("mode", {})
        assert "real" in modes, "real 모드 미정의"
        assert "paper" in modes, "paper 모드 미정의"

    def test_required_sections(self, scalping_rules):
        required = ["per_trade", "daily_limits", "time_restrictions"]
        for mode_name in ["real", "paper"]:
            mode_cfg = scalping_rules["mode"][mode_name]
            for section in required:
                assert section in mode_cfg, f"{mode_name}.{section} 미정의"
