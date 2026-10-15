from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from myquant.engine import Config, run_backtest, run_portfolio
from myquant.research_data import normalize_yahoo, total_return_signal, validate_actions, validate_calendar


def config(**changes):
    return replace(Config(fast=1, slow=2, initial_cash=100, allocation=1,
                          commission_per_share=0, minimum_commission=0, slippage_bps=0), **changes)


def actions(bars):
    bars = bars.copy()
    bars["dividend"], bars["split_ratio"] = 0.0, 1.0
    return bars


def test_split_changes_units_without_creating_profit_or_loss(make_bars):
    bars = actions(make_bars([10, 11, 12, 6, 6.5]))
    bars.loc[bars.index[3], "split_ratio"] = 2
    result = run_backtest(bars, config())
    assert result.equity.shares.iloc[2] == 8
    assert result.equity.shares.iloc[3] == 16
    assert result.equity.equity.iloc[2] == result.equity.equity.iloc[3] == 100
    assert not (result.trades.date == bars.index[3]).any()
    assert total_return_signal(bars).iloc[3] == pytest.approx(total_return_signal(bars).iloc[2])


def test_dividend_is_credited_on_sale_ex_date_but_cannot_be_reinvested(make_bars):
    bars = actions(make_bars([10, 11, 9, 8, 9]))
    bars.loc[bars.index[3], "dividend"] = 1
    result = run_backtest(bars, config())
    assert result.equity.shares.iloc[2] == 11
    assert result.equity.shares.iloc[3] == 0
    assert result.equity.distribution_reserve.iloc[3] == 11
    assert result.equity.cash.iloc[3] == 89
    assert result.equity.equity.iloc[3] == 100
    assert result.summary["distributions_not_reinvested"] == 11


def test_buying_on_ex_date_receives_no_dividend(make_bars):
    bars = actions(make_bars([10, 11, 12, 13, 14]))
    bars.loc[bars.index[2], "dividend"] = 1
    result = run_backtest(bars, config())
    assert result.equity.shares.iloc[2] > 0
    assert result.equity.distribution_reserve.iloc[2] == 0


def test_simultaneous_split_and_distribution_uses_post_split_shares(make_bars):
    bars = actions(make_bars([10, 11, 12, 5.5, 6]))
    bars.loc[bars.index[3], ["split_ratio", "dividend"]] = [2, 0.5]
    result = run_backtest(bars, config())
    assert result.equity.shares.iloc[3] == 16
    assert result.equity.distribution_reserve.iloc[3] == 8
    assert result.equity.equity.iloc[3] == 100
    assert total_return_signal(bars).iloc[3] == pytest.approx(total_return_signal(bars).iloc[2])


def test_future_split_and_dividend_cannot_change_past_signals_or_accounts(make_bars):
    before = actions(make_bars([10, 11, 12, 13, 14, 15, 16]))
    after = actions(make_bars([10, 11, 12, 13, 14, 7, 8]))
    after.loc[after.index[5], ["split_ratio", "dividend"]] = [2, 0.5]
    pd.testing.assert_series_equal(total_return_signal(before).iloc[:5], total_return_signal(after).iloc[:5])
    first, second = run_backtest(before, config()), run_backtest(after, config())
    pd.testing.assert_frame_equal(first.equity.iloc[:5], second.equity.iloc[:5])


def payload(prices, volumes, split=False, dividend=1):
    dates = pd.bdate_range("2024-01-02", periods=len(prices))
    times = [int(datetime.combine(day.date(), datetime.min.time(), ZoneInfo("America/New_York")).timestamp())
             for day in dates]
    events = {"dividends": {str(times[1]): {"date": times[1], "amount": dividend}}}
    if split:
        events["splits"] = {str(times[3]): {"date": times[3], "numerator": 2, "denominator": 1}}
    return {"chart": {"result": [{"meta": {"symbol": "TEST", "currency": "USD"},
             "timestamp": times, "events": events, "indicators": {"quote": [{
                 "open": prices, "high": prices, "low": prices, "close": prices, "volume": volumes}]}}], "error": None}}


def test_later_yahoo_split_adjustment_is_undone_without_rewriting_historical_units():
    original = payload([100, 110, 120], [1000] * 3)
    later = payload([50, 55, 60, 65], [2000, 2000, 2000, 1000], split=True, dividend=0.5)
    a = normalize_yahoo(original, "TEST", "2024-01-02", "2024-01-05")
    b = normalize_yahoo(later, "TEST", "2024-01-02", "2024-01-05")
    pd.testing.assert_frame_equal(a, b)
    full = normalize_yahoo(later, "TEST", "2024-01-02", "2024-01-06")
    assert full.close.iloc[-1] == 65
    assert full.split_ratio.iloc[-1] == 2
    assert full.dividend.iloc[1] == 1


def test_benchmark_also_pays_costs_and_drawdown_includes_entry_fee(make_bars):
    result = run_backtest(actions(make_bars([10] * 6)), config(minimum_commission=1))
    assert result.summary["benchmark"]["net_return"] == pytest.approx(-0.01)
    assert result.summary["benchmark"]["max_drawdown"] == pytest.approx(0.01)
    assert result.summary["benchmark"]["commissions"] == 1
    assert result.summary["net_return"] == 0


def test_multi_asset_shared_cash_is_order_independent_and_reconciles(make_bars):
    bars = actions(make_bars([10, 11, 12, 13, 14, 15]))
    setup = config(allocation=0.5, minimum_commission=1)
    first = run_portfolio({"AAA": bars, "BBB": bars}, setup)
    second = run_portfolio({"BBB": bars, "AAA": bars}, setup)
    pd.testing.assert_frame_equal(first.equity, second.equity)
    assert (first.equity.cash >= 0).all()
    assert (first.positions >= 0).all().all()
    curve = first.equity
    np.testing.assert_allclose(curve.equity, curve.cash + curve.market_value + curve.distribution_reserve)
    trades = first.trades
    cashflow = np.where(trades.action == "BUY", -1, 1) * trades.quantity * trades.price - trades.commission
    assert setup.initial_cash + cashflow.sum() == pytest.approx(curve.cash.iloc[-1])


def test_evaluation_resets_capital_but_uses_previous_period_for_warmup(make_bars):
    bars = actions(make_bars([10, 11, 12, 13, 14, 15, 16, 17]))
    start = str(bars.index[4].date())
    result = run_portfolio({"TEST": bars}, config(), start=start)
    assert result.trades.date.iloc[0] == bars.index[4]
    assert result.trades.quantity.iloc[0] == 7
    assert result.summary["initial_equity"] == 100
    assert result.summary["bars"] == 4


@pytest.mark.parametrize("column,value", [("dividend", -1), ("split_ratio", 0), ("split_ratio", np.nan)])
def test_invalid_corporate_action_is_rejected(make_bars, column, value):
    bars = actions(make_bars([10, 11, 12])).reset_index()
    bars.loc[0, column] = value
    with pytest.raises(ValueError):
        validate_actions(bars)


def test_missing_actions_and_missing_trading_day_are_rejected(make_bars):
    with pytest.raises(ValueError, match="dividend"):
        validate_actions(make_bars([10, 11, 12]).reset_index())
    bars = actions(make_bars([10, 11, 12])).drop(pd.Timestamp("2024-01-03"))
    with pytest.raises(ValueError, match="missing"):
        validate_calendar(bars, "2024-01-02", "2024-01-05", "TEST")
