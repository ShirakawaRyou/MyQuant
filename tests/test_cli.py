import json

import pytest

from myquant.cli import main


def test_demo_to_report_workflow_and_preserve_outputs(tmp_path):
    data = tmp_path / "data" / "demo.csv"
    report = tmp_path / "reports"
    assert main(["demo", "--output", str(data)]) == 0
    assert main(["backtest", "--csv", str(data), "--out", str(report)]) == 0
    summary = json.loads((report / "summary.json").read_text())
    assert summary["bars"] == 400
    assert summary["fills"] > 0
    assert summary["data_source"]["source"] == "synthetic"
    assert (report / "equity.png").stat().st_size > 1000
    assert (report / "trades.csv").read_text().count("\n") > 1
    original = data.read_bytes()
    assert main(["demo", "--output", str(data)]) == 1
    assert data.read_bytes() == original
    assert main(["backtest", "--csv", str(data), "--out", str(report)]) == 1


@pytest.mark.parametrize("command", ["paper", "ibkr-status"])
def test_no_broker_commands_exist(command):
    with pytest.raises(SystemExit) as error:
        main([command])
    assert error.value.code == 2
