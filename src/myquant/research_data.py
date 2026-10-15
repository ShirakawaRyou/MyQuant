"""Immutable research snapshots with explicit cash distributions and splits."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pandas_market_calendars as calendars

from .data import validate_bars

ACTION_COLUMNS = ["dividend", "split_ratio"]
NY = ZoneInfo("America/New_York")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_actions(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(column).lower().strip() for column in frame.columns]
    if frame.columns.has_duplicates or any(column not in frame for column in ACTION_COLUMNS):
        raise ValueError("Research CSV requires unique columns including dividend and split_ratio")
    bars = validate_bars(frame)
    actions = frame[ACTION_COLUMNS].apply(pd.to_numeric, errors="raise").to_numpy(dtype=float)
    if not np.isfinite(actions).all() or (actions[:, 0] < 0).any() or (actions[:, 1] <= 0).any():
        raise ValueError("Distributions must be finite/nonnegative; split_ratio must be finite/positive")
    bars[ACTION_COLUMNS] = actions
    return bars


def total_return_signal(bars: pd.DataFrame) -> pd.Series:
    """Forward-only index: each new observation uses that day's known actions."""
    gross = (bars.close + bars.dividend) * bars.split_ratio / bars.close.shift(1)
    gross.iloc[0] = 1.0
    return gross.cumprod()


def _event_date(timestamp: int) -> str:
    return datetime.fromtimestamp(int(timestamp), NY).date().isoformat()


def normalize_yahoo(payload: dict, symbol: str, start: str, end: str) -> pd.DataFrame:
    """Undo Yahoo's split-adjusted quote units, then account for events once.

    The response must extend through its retrieval date, even when research ends
    earlier: later splits are already reflected in Yahoo's historical quotes.
    Future split factors here only undo provider scaling; signals never use them.
    """
    chart = payload.get("chart", {})
    if chart.get("error") or not chart.get("result"):
        raise ValueError(f"Yahoo returned no usable history for {symbol}")
    result = chart["result"][0]
    metadata = result.get("meta", {})
    if metadata.get("currency") != "USD" or metadata.get("symbol", "").upper() != symbol.upper():
        raise ValueError(f"Unexpected symbol/currency in Yahoo response for {symbol}")
    timestamps = result.get("timestamp", [])
    if not timestamps:
        raise ValueError(f"No bars for {symbol}")
    quotes = result["indicators"]["quote"][0]
    dates = [_event_date(timestamp) for timestamp in timestamps]
    frame = pd.DataFrame({"date": dates, **{column: quotes[column] for column in
                                          ["open", "high", "low", "close", "volume"]}})
    events = result.get("events", {})
    splits = {}
    for event in events.get("splits", {}).values():
        ratio = float(event["numerator"]) / float(event["denominator"])
        if not np.isfinite(ratio) or ratio <= 0:
            raise ValueError("Invalid Yahoo split event")
        day = _event_date(event["date"])
        splits[day] = splits.get(day, 1.0) * ratio
    distributions = {}
    for category in ("dividends", "capitalGains"):
        for event in events.get(category, {}).values():
            day = _event_date(event["date"])
            distributions[day] = distributions.get(day, 0.0) + float(event["amount"])
    # On the split date itself the price/dividend is already in post-split units.
    factor = np.array([np.prod([ratio for day, ratio in splits.items() if day > date])
                       for date in dates], dtype=float)
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="raise") * factor
    frame["volume"] = pd.to_numeric(frame["volume"], errors="raise") / factor
    frame["dividend"] = [distributions.get(date, 0.0) * scale for date, scale in zip(dates, factor)]
    frame["split_ratio"] = [splits.get(date, 1.0) for date in dates]
    frame = frame[(frame.date >= start) & (frame.date < end)]
    available_dates = set(frame.date)
    for day in set(splits) | set(distributions):
        if start <= day < end and day not in available_dates:
            raise ValueError(f"Corporate action without a price bar: {symbol} {day}")
    return validate_actions(frame)


def validate_calendar(bars: pd.DataFrame, start: str, end: str, symbol: str) -> None:
    expected = calendars.get_calendar("NYSE").valid_days(
        start_date=start, end_date=pd.Timestamp(end) - pd.Timedelta(days=1),
    ).tz_localize(None)
    selected = bars.loc[(bars.index >= start) & (bars.index < end)]
    missing, extra = expected.difference(selected.index), selected.index.difference(expected)
    if len(missing) or len(extra):
        raise ValueError(f"{symbol}: incomplete/misaligned daily history; "
                         f"missing={list(missing.strftime('%Y-%m-%d'))[:8]}, "
                         f"extra={list(extra.strftime('%Y-%m-%d'))[:8]}")


def fetch_snapshot(symbols: list[str], start: str, end: str, output: Path) -> dict:
    if output.exists():
        raise ValueError("Snapshot output already exists; choose a new directory")
    now = datetime.now(timezone.utc)
    through = datetime.combine(now.astimezone(NY).date() + timedelta(days=1), datetime.min.time(), NY)
    if pd.Timestamp(end).date() > through.date():
        raise ValueError("Requested history extends into the future")
    output.mkdir(parents=True)
    manifest = {"schema_version": 1, "source": "Yahoo chart daily snapshots", "status": "incomplete",
                "retrieved_at_utc": now.isoformat(), "start": start, "end_exclusive": end,
                "price_basis": "as_traded", "symbols": {}, "errors": {}}
    for symbol in symbols:
        try:
            query = urlencode({"period1": int(datetime.fromisoformat(start).replace(tzinfo=NY).timestamp()),
                               "period2": int(through.timestamp()), "interval": "1d",
                               "events": "div,splits,capitalGains"})
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?{query}"
            with urlopen(Request(url, headers={"User-Agent": "MyQuant-research/0.2"}), timeout=30) as response:
                raw = response.read()
            (output / f"{symbol}.raw.json").write_bytes(raw)
            bars = normalize_yahoo(json.loads(raw), symbol, start, end)
            validate_calendar(bars, start, end, symbol)
            bars.to_csv(output / f"{symbol}.csv", index_label="date", date_format="%Y-%m-%d")
            manifest["symbols"][symbol] = {
                "csv_sha256": sha256(output / f"{symbol}.csv"),
                "raw_sha256": sha256(output / f"{symbol}.raw.json"),
                "bars": len(bars), "distribution_events": int((bars.dividend != 0).sum()),
                "split_events": int((bars.split_ratio != 1).sum()),
            }
        except (ValueError, KeyError, OSError, TypeError) as error:
            manifest["errors"][symbol] = f"{type(error).__name__}: {error}"
    if not manifest["errors"]:
        manifest["status"] = "complete"
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if manifest["errors"]:
        raise ValueError(f"Data snapshot incomplete: {manifest['errors']}; no performance result produced")
    return manifest


def load_snapshot(root: Path, symbols: list[str]) -> tuple[dict[str, pd.DataFrame], dict]:
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("status") != "complete" or manifest.get("price_basis") != "as_traded":
        raise ValueError("Need a complete snapshot with explicit actions and as-traded prices")
    if sorted(manifest["symbols"]) != sorted(symbols):
        raise ValueError("Snapshot symbols do not match the research protocol")
    panel = {}
    for symbol in symbols:
        item = manifest["symbols"][symbol]
        if sha256(root / f"{symbol}.csv") != item["csv_sha256"]:
            raise ValueError(f"Normalized CSV hash changed for {symbol}")
        if sha256(root / f"{symbol}.raw.json") != item["raw_sha256"]:
            raise ValueError(f"Raw source hash changed for {symbol}")
        panel[symbol] = validate_actions(pd.read_csv(root / f"{symbol}.csv"))
        validate_calendar(panel[symbol], manifest["start"], manifest["end_exclusive"], symbol)
    return panel, manifest
