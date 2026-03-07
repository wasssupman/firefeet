"""TradeLogger 스캘핑 로깅 유닛 테스트 — 30컬럼 CSV 기록 검증."""

import csv
import pytest
from core.trade_logger import TradeLogger


@pytest.fixture
def logger(tmp_path):
    """임시 디렉토리에 로그 파일 생성."""
    return TradeLogger(log_dir=str(tmp_path), strategy="scalp")


def _read_csv_rows(logger):
    """CSV 파일에서 데이터 행 읽기 (헤더 제외)."""
    with open(logger.csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


class TestCSVHeader:

    def test_csv_header_30_columns(self, logger):
        """CSV_HEADER가 정확히 30컬럼."""
        assert len(TradeLogger.CSV_HEADER) == 30

    def test_csv_header_written_on_init(self, logger):
        """초기화 시 CSV 헤더가 기록됨."""
        with open(logger.csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == TradeLogger.CSV_HEADER


class TestScalpBuy:

    def test_buy_writes_strategy_composite(self, logger):
        """log_scalp_buy -> CSV에 strategy, composite 기록."""
        logger.log_scalp_buy(
            "005930", "삼성전자", 10, 50000, signal_confidence=0.42,
            strategy="momentum_scalp", composite=42.5, threshold=0.35,
            temperature="HOT",
        )

        rows = _read_csv_rows(logger)
        assert len(rows) == 1
        row = rows[0]
        assert row["action"] == "SCALP_BUY"
        assert row["strategy"] == "momentum_scalp"
        assert row["composite"] == "42.5"
        assert row["threshold"] == "0.35"
        assert row["temperature"] == "HOT"

    def test_buy_fee_calculation(self, logger):
        """매수 수수료 계산: 0.015%."""
        result = logger.log_scalp_buy("005930", "삼성전자", 10, 50000)

        amount = 10 * 50000  # 500,000
        expected_fee = int(amount * 0.00015)  # 75
        assert result["fee"] == expected_fee
        assert result["net_amount"] == amount + expected_fee

    def test_buy_writes_signal_fields(self, logger):
        """5개 시그널 필드 기록."""
        logger.log_scalp_buy(
            "005930", "삼성전자", 10, 50000, signal_confidence=0.42,
            sig_vwap=60.0, sig_ob=45.0, sig_mom=55.0,
            sig_vol=30.0, sig_trend=40.0,
        )

        rows = _read_csv_rows(logger)
        row = rows[0]
        assert row["sig_vwap"] == "60.0"
        assert row["sig_ob"] == "45.0"
        assert row["sig_mom"] == "55.0"
        assert row["sig_vol"] == "30.0"
        assert row["sig_trend"] == "40.0"


class TestScalpSell:

    def test_sell_writes_hold_seconds(self, logger):
        """log_scalp_sell -> hold_seconds 기록."""
        logger.log_scalp_sell(
            "005930", "삼성전자", 10, 50500, buy_price=50000,
            signal="SCALP_SELL_TP(+1.00%)",
            hold_seconds=95.3, peak_profit_pct=1.25,
        )

        rows = _read_csv_rows(logger)
        assert len(rows) == 1
        row = rows[0]
        assert row["hold_seconds"] == "95.3"
        assert row["peak_profit_pct"] == "1.25"

    def test_sell_pnl_calculation(self, logger):
        """매도 실현손익 계산."""
        result = logger.log_scalp_sell(
            "005930", "삼성전자", 10, 50500, buy_price=50000,
            signal="SCALP_SELL_TP",
        )

        buy_amount = 10 * 50000
        buy_fee = int(buy_amount * 0.00015)
        buy_net = buy_amount + buy_fee

        sell_amount = 10 * 50500
        sell_fee = int(sell_amount * (0.00015 + 0.0018))
        sell_net = sell_amount - sell_fee

        expected_pnl = sell_net - buy_net
        assert result["realized_pnl"] == expected_pnl
        assert result["buy_net"] == buy_net
        assert result["sell_net"] == sell_net

    def test_sell_writes_strategy(self, logger):
        """매도 시 strategy 필드 기록."""
        logger.log_scalp_sell(
            "005930", "삼성전자", 10, 50500, buy_price=50000,
            signal="SCALP_SELL_SL",
            strategy="orb", temperature="WARM",
        )

        rows = _read_csv_rows(logger)
        row = rows[0]
        assert row["strategy"] == "orb"
        assert row["temperature"] == "WARM"
        assert row["signal"] == "SCALP_SELL_SL"


class TestBackwardCompat:

    def test_backward_compat_no_kwargs(self, logger):
        """kwargs 없이 호출 -> 에러 없음, 빈값 기록."""
        logger.log_scalp_buy("005930", "삼성전자", 10, 50000)
        logger.log_scalp_sell("005930", "삼성전자", 10, 50500, buy_price=50000)

        rows = _read_csv_rows(logger)
        assert len(rows) == 2

        buy_row = rows[0]
        assert buy_row["strategy"] == ""
        assert buy_row["composite"] == ""

        sell_row = rows[1]
        assert sell_row["hold_seconds"] == ""
        assert sell_row["peak_profit_pct"] == ""

    def test_multiple_trades_append(self, logger):
        """여러 거래 append."""
        for i in range(5):
            logger.log_scalp_buy("005930", "삼성전자", 10, 50000 + i * 100)

        rows = _read_csv_rows(logger)
        assert len(rows) == 5
