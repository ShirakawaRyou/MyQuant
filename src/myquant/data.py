"""Strict OHLCV validation and reproducible synthetic software-test data."""

from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["open", "high", "low", "close", "volume"]


def validate_bars(frame: pd.DataFrame) -> pd.DataFrame:
    bars = frame.copy()
    bars.columns = [str(column).strip().lower() for column in bars.columns]
    if bars.columns.has_duplicates or "date" not in bars or any(column not in bars for column in COLUMNS):
        raise ValueError("CSV needs unique date, open, high, low, close, volume columns")
    dates = pd.to_datetime(bars.pop("date"), errors="raise", utc=True)
    bars.index = pd.DatetimeIndex(dates).tz_convert(None).normalize()
    bars.index.name = "date"
    if bars.empty or bars.index.isna().any():
        raise ValueError("No price bars or invalid date")
    if bars.index.has_duplicates or not bars.index.is_monotonic_increasing:
        raise ValueError("Dates must be unique and in ascending order")
    bars = bars[COLUMNS].apply(pd.to_numeric, errors="raise").astype(float)
    if not np.isfinite(bars.to_numpy()).all():
        raise ValueError("Prices and volume must be finite; missing bars are not filled")
    if (bars[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Prices must be positive")
    if (bars["volume"] < 0).any():
        raise ValueError("Volume must be nonnegative")
    if ((bars["high"] < bars[["open", "close", "low"]].max(axis=1)).any()
            or (bars["low"] > bars[["open", "close", "high"]].min(axis=1)).any()):
        raise ValueError("OHLC price ranges are inconsistent")
    return bars


def write_bars(bars: pd.DataFrame, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bars.to_csv(path, index_label="date", date_format="%Y-%m-%d")


def demo_bars(count: int = 400, seed: int = 42) -> pd.DataFrame:
    """Synthetic prices for exercising software, never investment evidence."""
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, count)))
    opening = np.r_[close[0], close[:-1]] * np.exp(rng.normal(0, 0.003, count))
    bars = validate_bars(pd.DataFrame({
        "date": pd.bdate_range("2023-01-03", periods=count), "open": opening,
        "high": np.maximum(opening, close) * (1 + rng.uniform(0.001, 0.02, count)),
        "low": np.minimum(opening, close) * (1 - rng.uniform(0.001, 0.02, count)),
        "close": close, "volume": rng.integers(100_000, 5_000_000, count),
    }))
    bars["dividend"], bars["split_ratio"] = 0.0, 1.0
    return bars
