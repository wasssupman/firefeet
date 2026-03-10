"""StrategySelector 유닛 테스트 — 전략 선택 + 시간/온도 로직."""

import pytest
from unittest.mock import patch
import datetime
from datetime import timezone, timedelta

from core.scalping.strategy_selector import StrategySelector, StrategyProfile

KST = timezone(timedelta(hours=9))


@pytest.fixture
def selector(scalp_strategies):
    return StrategySelector(config_path=scalp_strategies)


def _make_kst_datetime(hour, minute):
    """특정 시각의 KST datetime 생성."""
    return datetime.datetime(2026, 2, 26, hour, minute, 0, tzinfo=KST)


class TestStrategySelection:

    def test_vwap_reversion_at_0930(self, selector):
        """09:30 -> vwap_reversion 전략 선택."""
        with patch("core.scalping.strategy_selector.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(9, 30)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            profile = selector.select()

        assert profile is not None
        assert profile.name == "vwap_reversion"

    def test_vwap_reversion_at_1000_hot(self, selector):
        """10:00 + HOT -> vwap_reversion 선택 (temperatures: any)."""
        selector.apply_temperature({"level": "HOT", "temperature": 80})

        with patch("core.scalping.strategy_selector.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            profile = selector.select()

        assert profile is not None
        assert profile.name == "vwap_reversion"

    def test_lunch_block_returns_none(self, selector):
        """12:30 -> 점심 구간 -> None."""
        with patch("core.scalping.strategy_selector.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(12, 30)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            profile = selector.select()

        assert profile is None

    def test_adaptive_fallback(self, selector):
        """매칭 없을 때 -> adaptive."""
        # 15:25 -> vwap_reversion 활성시간(0930~1200) 외, 점심차단(1200~1520) 이후
        # -> 전략 매칭 없음 -> adaptive fallback
        selector.apply_temperature({"level": "COLD", "temperature": -80})

        with patch("core.scalping.strategy_selector.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(15, 25)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            profile = selector.select()

        assert profile is not None
        assert profile.name == "adaptive"

    def test_profile_weights_sum_100(self, selector):
        """모든 전략 weights 합이 100."""
        for time_h, time_m in [(9, 15), (10, 0), (11, 0)]:
            for level in ["HOT", "WARM", "NEUTRAL", "COOL", "COLD"]:
                selector.apply_temperature({"level": level, "temperature": 0})

                with patch("core.scalping.strategy_selector.datetime") as mock_dt:
                    mock_dt.datetime.now.return_value = _make_kst_datetime(time_h, time_m)
                    mock_dt.timezone = datetime.timezone
                    mock_dt.timedelta = datetime.timedelta

                    profile = selector.select()

                if profile is not None:
                    total = sum(profile.weights.values())
                    assert total == 100, (
                        f"weights sum != 100 for {profile.name}: {total}"
                    )

    def test_profile_tp_sl_from_config(self, selector):
        """vwap_reversion -> tp=0.6, sl=-0.4 (config에서)."""
        with patch("core.scalping.strategy_selector.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(10, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            profile = selector.select()

        assert profile.take_profit == 0.6
        assert profile.stop_loss == -0.4
        assert profile.max_hold_seconds == 120

    def test_vwap_reversion_at_1100_cold(self, selector):
        """11:00 + COLD -> vwap_reversion 선택."""
        selector.apply_temperature({"level": "COLD", "temperature": -80})

        with patch("core.scalping.strategy_selector.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(11, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            profile = selector.select()

        assert profile is not None
        assert profile.name == "vwap_reversion"

    def test_lunch_block_boundary_start(self, selector):
        """12:00 정각 -> 점심 차단 시작."""
        with patch("core.scalping.strategy_selector.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(12, 0)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            profile = selector.select()

        assert profile is None

    def test_lunch_block_boundary_end(self, selector):
        """15:20 -> 점심 차단 종료 (>= lunch_end)."""
        with patch("core.scalping.strategy_selector.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = _make_kst_datetime(15, 20)
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta

            profile = selector.select()

        # 15:20 >= "1520" -> not in lunch block -> adaptive fallback
        assert profile is not None
