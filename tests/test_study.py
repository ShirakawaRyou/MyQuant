import json
from pathlib import Path

import pandas as pd
import pandas_market_calendars as calendars
import pytest

from myquant.cli import main
from myquant.study import freeze, import_snapshot, read_protocol, run_stage


@pytest.fixture
def experiment(tmp_path):
    dates = calendars.get_calendar("NYSE").valid_days("2023-01-01", "2023-03-31").tz_localize(None)
    prices = [10 + number * 0.1 for number in range(len(dates))]
    frame = pd.DataFrame({"date": dates, "open": prices, "high": prices, "low": prices,
                          "close": prices, "volume": 1000, "dividend": 0, "split_ratio": 1})
    source = tmp_path / "input"
    source.mkdir()
    frame.to_csv(source / "TEST.csv", index=False)
    protocol = {
        "universe": ["TEST"], "universe_policy": "Synthetic software test fixture only",
        "history_start": "2023-01-01", "history_end_exclusive": "2023-04-01",
        "strategy": {"fast": 1, "slow": 2, "initial_cash": 1000, "allocation": 1},
        "periods": {
            "development": {"start": "2023-02-01", "end_exclusive": "2023-03-01"},
            "validation": {"start": "2023-03-01", "end_exclusive": "2023-03-15"},
            "holdout": {"start": "2023-03-15", "end_exclusive": "2023-04-01"},
        },
    }
    config = tmp_path / "protocol.json"
    config.write_text(json.dumps(protocol))
    data = tmp_path / "snapshot"
    import_snapshot(config, source, data, "Synthetic test data; not real market performance")
    frozen = tmp_path / "frozen.json"
    freeze(config, data, frozen)
    return config, data, frozen, source


def test_frozen_holdout_executes_real_nonzero_test_workflow(experiment, tmp_path):
    config, data, frozen, _ = experiment
    out = tmp_path / "report"
    assert main(["study", "--config", str(config), "--data", str(data), "--freeze", str(frozen),
                 "--stage", "holdout", "--out", str(out)]) == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["stage"] == "holdout"
    assert summary["start"] == "2023-03-15"
    assert summary["fills"] > 0 and summary["bars"] > 5
    assert summary["experiment"]["parameter_search"] == "none"
    for filename in ["equity.png", "equity.csv", "trades.csv", "benchmark_trades.csv", "corporate_actions.csv", "report.md"]:
        assert (out / filename).stat().st_size > 0


def test_parameter_change_invalidates_freeze_before_evaluation(experiment):
    config, data, frozen, _ = experiment
    protocol = json.loads(config.read_text())
    protocol["strategy"]["slow"] = 3
    config.write_text(json.dumps(protocol))
    with pytest.raises(ValueError, match="mismatch"):
        run_stage(config, data, frozen, "holdout")


def test_csv_tampering_invalidates_snapshot(experiment):
    config, data, frozen, _ = experiment
    with (data / "TEST.csv").open("a") as handle:
        handle.write("\n")
    with pytest.raises(ValueError, match="hash"):
        run_stage(config, data, frozen, "holdout")


def test_raw_source_tampering_invalidates_snapshot(experiment):
    config, data, frozen, _ = experiment
    (data / "TEST.raw.json").write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        run_stage(config, data, frozen, "holdout")


def test_frozen_record_cannot_be_overwritten(experiment):
    config, data, frozen, _ = experiment
    with pytest.raises(ValueError, match="overwritten"):
        freeze(config, data, frozen)


def test_overlapping_history_is_rejected(experiment):
    config, _, _, _ = experiment
    protocol = json.loads(config.read_text())
    protocol["periods"]["holdout"]["start"] = "2023-03-01"
    config.write_text(json.dumps(protocol))
    with pytest.raises(ValueError, match="nonoverlapping"):
        read_protocol(config)


def test_missing_input_has_no_partial_performance_result(experiment, tmp_path):
    config, _, _, source = experiment
    (source / "TEST.csv").unlink()
    target = tmp_path / "bad-snapshot"
    with pytest.raises(ValueError, match="Incomplete"):
        import_snapshot(config, source, target, "test")
    assert json.loads((target / "manifest.json").read_text())["status"] == "incomplete"
    assert not (target / "summary.json").exists()


def test_history_after_evaluation_cannot_change_development_results(experiment):
    config, data, frozen, source = experiment
    first = run_stage(config, data, frozen, "development")
    frame = pd.read_csv(source / "TEST.csv")
    selected = frame.date >= "2023-03-15"
    for column in ["open", "high", "low", "close"]:
        frame.loc[selected, column] *= 3
    frame.to_csv(source / "TEST.csv", index=False)
    other = data.parent / "other-snapshot"
    import_snapshot(config, source, other, "Synthetic future mutation fixture")
    other_frozen = frozen.parent / "other-frozen.json"
    freeze(config, other, other_frozen)
    second = run_stage(config, other, other_frozen, "development")
    pd.testing.assert_frame_equal(first.equity, second.equity)
