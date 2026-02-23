"""
utils/chart_renderer.py
Renders candlestick charts with technical indicators to a PNG buffer.
Used by VisionAnalyst for visual chart pattern recognition.
"""

import io
import logging
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
from core.providers.kis_api import KisAPI

logger = logging.getLogger("ChartRenderer")


def render_chart_to_bytes(code: str, period_days: int = 60) -> bytes:
    """
    Fetches OHLCV data for a given stock code and renders it to a PNG bytes buffer.
    Includes 5/20/60 EMA lines, volume bars, and Bollinger Bands.

    Args:
        code: Stock code (e.g., '005930')
        period_days: Number of recent trading days to include in the chart

    Returns:
        PNG image as bytes (ready to send to Vision API), or None on failure
    """
    try:
        api = KisAPI()
        # Fetch daily OHLCV — KIS API returns records newest-first
        raw = api.get_ohlcv(code, period=period_days)
        if not raw or len(raw) < 20:
            logger.warning(f"[{code}] Insufficient OHLCV data ({len(raw) if raw else 0} rows).")
            return None

        # Build standard DataFrame required by mplfinance
        df = pd.DataFrame(raw)
        df = df.rename(columns={
            "stck_bsop_date": "Date",
            "stck_oprc": "Open",
            "stck_hgpr": "High",
            "stck_lwpr": "Low",
            "stck_clpr": "Close",
            "acml_vol": "Volume",
        })
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna()

        # --- Additional Plots: EMA lines ---
        ema5 = df["Close"].ewm(span=5, adjust=False).mean()
        ema20 = df["Close"].ewm(span=20, adjust=False).mean()
        ema60 = df["Close"].ewm(span=60, adjust=False).mean()

        # Bollinger Bands (20-period, 2 std)
        rolling_mean = df["Close"].rolling(window=20).mean()
        rolling_std = df["Close"].rolling(window=20).std()
        bb_upper = rolling_mean + 2 * rolling_std
        bb_lower = rolling_mean - 2 * rolling_std

        extra_plots = [
            mpf.make_addplot(ema5, color='cyan', width=0.8, label='EMA5'),
            mpf.make_addplot(ema20, color='orange', width=0.8, label='EMA20'),
            mpf.make_addplot(ema60, color='magenta', width=1.0, label='EMA60'),
            mpf.make_addplot(bb_upper, color='gray', width=0.6, linestyle='--'),
            mpf.make_addplot(bb_lower, color='gray', width=0.6, linestyle='--'),
        ]

        # Render to buffer
        buf = io.BytesIO()
        mpf.plot(
            df,
            type='candle',
            style='nightclouds',
            volume=True,
            addplot=extra_plots,
            title=f'{code} — {period_days}D Chart',
            figsize=(14, 8),
            tight_layout=True,
            savefig=dict(fname=buf, dpi=120, bbox_inches='tight'),
        )
        buf.seek(0)
        png_bytes = buf.read()
        logger.info(f"[{code}] Chart rendered successfully ({len(png_bytes)} bytes).")
        return png_bytes

    except Exception as e:
        logger.error(f"[{code}] Chart render failed: {e}")
        return None
