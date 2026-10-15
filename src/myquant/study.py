"""Predefined periods and frozen experiment identities; no optimizer."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import pandas as pd

from .engine import Config, run_portfolio
from .research_data import load_snapshot, sha256, validate_actions, validate_calendar

STAGES = ["development", "validation", "holdout"]
PROJECT = Path(__file__).resolve().parents[2]


def read_protocol(path: Path) -> dict:
    protocol = json.loads(path.read_text())
    symbols = protocol["universe"]
    if (not symbols or len(set(symbols)) != len(symbols)
            or any(not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol) for symbol in symbols)):
        raise ValueError("Need unique, safe uppercase stock symbols")
    config = Config(**protocol["strategy"])
    if len(symbols) * config.allocation > 1 + 1e-10:
        raise ValueError("Combined stock targets exceed 100%")
    periods = protocol["periods"]
    if set(periods) != set(STAGES):
        raise ValueError("Declare development, validation and holdout periods explicitly")
    previous = protocol["history_start"]
    for stage in STAGES:
        period = periods[stage]
        start, end = period["start"], period["end_exclusive"]
        for day in (start, end):
            if pd.Timestamp(day).strftime("%Y-%m-%d") != day:
                raise ValueError("Use ISO dates")
        if not previous <= start < end <= protocol["history_end_exclusive"]:
            raise ValueError("Evaluation periods must be ordered, nonoverlapping and within history")
        previous = end
    return protocol


def code_digest() -> str:
    digest = hashlib.sha256()
    paths = [PROJECT / "pyproject.toml", PROJECT / "uv.lock", *sorted((PROJECT / "src").rglob("*.py"))]
    for path in paths:
        digest.update(path.relative_to(PROJECT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def identity(protocol_path: Path, data_root: Path) -> dict:
    protocol = read_protocol(protocol_path)
    _, manifest = load_snapshot(data_root, protocol["universe"])
    if (manifest["start"] > protocol["history_start"]
            or manifest["end_exclusive"] < protocol["history_end_exclusive"]):
        raise ValueError("Snapshot does not cover the full declared history")
    return {"protocol_sha256": sha256(protocol_path), "code_sha256": code_digest(),
            "data_manifest_sha256": sha256(data_root / "manifest.json")}


def freeze(protocol_path: Path, data_root: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("Frozen experiment already exists; it cannot be overwritten")
    record = {**identity(protocol_path, data_root),
              "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
              "protocol": read_protocol(protocol_path), "parameter_search": "none",
              "note": "Period definitions and rules frozen before evaluation; no automatic tuning"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2) + "\n")
    return record


def run_stage(protocol_path: Path, data_root: Path, frozen: Path, stage: str):
    if stage not in STAGES:
        raise ValueError("Unknown evaluation stage")
    record = json.loads(frozen.read_text())
    current = identity(protocol_path, data_root)
    if any(record.get(key) != value for key, value in current.items()):
        raise ValueError("Frozen experiment mismatch: code, parameters or data changed; evaluation refused")
    protocol = read_protocol(protocol_path)
    panel, manifest = load_snapshot(data_root, protocol["universe"])
    period = protocol["periods"][stage]
    result = run_portfolio(panel, Config(**protocol["strategy"]), period["start"], period["end_exclusive"])
    result.summary.update({"stage": stage, "experiment": record, "data_manifest": manifest,
                           "selection_bias": protocol["universe_policy"],
                           "capital_policy": "Independent reset for each period; do not concatenate period equity levels"})
    return result


def import_snapshot(protocol_path: Path, source: Path, output: Path, label: str) -> dict:
    """User-declared as-traded CSV only; adjusted data is never silently inferred."""
    if output.exists():
        raise ValueError("Import output already exists")
    protocol = read_protocol(protocol_path)
    output.mkdir(parents=True)
    manifest = {"schema_version": 1, "source": label, "status": "incomplete",
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "start": protocol["history_start"], "end_exclusive": protocol["history_end_exclusive"],
                "price_basis": "as_traded", "symbols": {}, "errors": {}}
    for symbol in protocol["universe"]:
        try:
            raw = (source / f"{symbol}.csv").read_bytes()
            bars = validate_actions(pd.read_csv(source / f"{symbol}.csv"))
            validate_calendar(bars, manifest["start"], manifest["end_exclusive"], symbol)
            bars = bars.loc[(bars.index >= manifest["start"]) & (bars.index < manifest["end_exclusive"])]
            # This raw envelope retains the exact input; no brokerage connection.
            (output / f"{symbol}.raw.json").write_text(json.dumps({"source_csv": raw.decode("utf-8")}))
            bars.to_csv(output / f"{symbol}.csv", index_label="date", date_format="%Y-%m-%d")
            manifest["symbols"][symbol] = {
                "csv_sha256": sha256(output / f"{symbol}.csv"),
                "raw_sha256": sha256(output / f"{symbol}.raw.json"), "bars": len(bars),
                "distribution_events": int((bars.dividend != 0).sum()),
                "split_events": int((bars.split_ratio != 1).sum()),
            }
        except (ValueError, OSError) as error:
            manifest["errors"][symbol] = str(error)
    if not manifest["errors"]:
        manifest["status"] = "complete"
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if manifest["errors"]:
        raise ValueError(f"Incomplete import: {manifest['errors']}")
    return manifest
