from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from myquant.data import demo_bars, validate_bars
from myquant.engine import Config, run_backtest


def simple_config(**kwargs):
    return replace(Config(fast=1, slow=2, initial_cash=100, allocation=1,
                          minimum_commission=0, commission_per_share=0, slippage_bps=0), **kwargs)


def test_signal_trades_at_next_open_and_known_equity(make_bars):
    bars = make_bars([10, 11, 12, 13, 14, 15])
    result = run_backtest(bars, simple_config())
    assert result.trades.iloc[0].date == bars.index[2]
    assert result.trades.iloc[0].price == 12
    assert result.trades.iloc[0].quantity == 8
    assert result.summary["final_equity"] == 124
    assert result.equity.shares.iloc[:2].eq(0).all()


def test_gap_uses_open_rather_than_signal_close(make_bars):
    bars = make_bars([10, 11, 12, 13], opens=[10, 11, 20, 13])
    result = run_backtest(bars, simple_config())
    assert result.trades.iloc[0].price == 20
    assert result.trades.iloc[0].quantity == 5


def test_future_prices_do_not_change_past_positions(make_bars):
    first = make_bars([10, 11, 12, 13, 14, 15, 16, 17])
    second = make_bars([10, 11, 12, 13, 14, 80, 60, 40])
    a, b = [run_backtest(bars, simple_config()).equity for bars in (first, second)]
    pd.testing.assert_frame_equal(a.iloc[:5], b.iloc[:5])
    assert a.shares.iloc[5] == b.shares.iloc[5]


def test_sell_signal_waits_for_next_open(make_bars):
    bars = make_bars([10, 11, 12, 9, 8, 7])
    result = run_backtest(bars, simple_config())
    sale = result.trades[result.trades.action == "SELL"].iloc[0]
    assert sale.date == bars.index[4]
    assert sale.price == 8
    assert result.summary["final_equity"] == 68
    assert result.summary["ending_shares"] == 0


def test_commission_slippage_and_cash_reconcile(make_bars):
    result = run_backtest(make_bars([10, 11, 12, 13, 14, 15]),
                          simple_config(minimum_commission=1, slippage_bps=100))
    first = result.trades.iloc[0]
    assert first.price == pytest.approx(12.12)
    assert first.commission == 1
    assert first.cash_after == pytest.approx(2.04)
    assert result.summary["final_equity"] == pytest.approx(122.04)
    assert (result.equity.cash >= 0).all()


def test_no_borrowing_and_position_is_whole_shares():
    result = run_backtest(demo_bars(), Config(allocation=1))
    assert (result.equity.cash >= 0).all()
    assert (result.equity.shares >= 0).all()
    assert np.equal(result.equity.shares, np.floor(result.equity.shares)).all()
    assert result.summary["fills"] > 0


def test_flat_market_has_zero_trades(make_bars):
    result = run_backtest(make_bars([10] * 10), simple_config())
    assert result.trades.empty
    assert result.summary["net_return"] == 0
    assert result.summary["sharpe_zero_risk_free"] == 0


@pytest.mark.parametrize("changes", [
    {"fast": 60}, {"initial_cash": 0}, {"allocation": 1.1},
    {"slippage_bps": -1}, {"minimum_commission": float("nan")},
])
def test_bad_configuration_is_rejected(changes):
    with pytest.raises(ValueError):
        Config(**changes)


def test_short_history_is_rejected(make_bars):
    with pytest.raises(ValueError):
        run_backtest(make_bars([10, 11]), Config())


@pytest.mark.parametrize("bad", ["duplicate", "unsorted", "nan", "zero", "range", "missing"])
def test_bad_data_is_rejected(make_bars, bad):
    data = make_bars([10, 11, 12]).reset_index()
    if bad == "duplicate":
        data.loc[1, "date"] = data.loc[0, "date"]
    elif bad == "unsorted":
        data = data.iloc[::-1]
    elif bad == "nan":
        data.loc[0, "volume"] = np.nan
    elif bad == "zero":
        data.loc[0, "close"] = 0
    elif bad == "range":
        data.loc[0, "high"] = 1
    elif bad == "missing":
        data = data.drop(columns="close")
    with pytest.raises(ValueError):
        validate_bars(data)
