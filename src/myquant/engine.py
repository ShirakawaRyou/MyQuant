"""Causal multi-asset accounting, corporate actions and equal-cost benchmarks."""

from dataclasses import asdict, dataclass, field
import math

import numpy as np
import pandas as pd

from .research_data import total_return_signal, validate_actions


@dataclass(frozen=True)
class Config:
    fast: int = 20
    slow: int = 60
    initial_cash: float = 100_000
    allocation: float = 0.20
    commission_per_share: float = 0.005
    minimum_commission: float = 1.0
    slippage_bps: float = 5.0

    def __post_init__(self):
        if not 1 <= self.fast < self.slow:
            raise ValueError("Windows must satisfy 1 <= fast < slow")
        numeric = [self.initial_cash, self.allocation, self.commission_per_share,
                   self.minimum_commission, self.slippage_bps]
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("Configuration values must be finite")
        if self.initial_cash <= 0 or not 0 < self.allocation <= 1:
            raise ValueError("Cash must be positive; allocation must be in (0, 1]")
        if min(self.commission_per_share, self.minimum_commission, self.slippage_bps) < 0:
            raise ValueError("Costs cannot be negative")
        if self.slippage_bps >= 10_000:
            raise ValueError("Slippage must be below 10000 bps")


def target_weights(bars: pd.DataFrame, config: Config) -> pd.Series:
    index = total_return_signal(bars)
    fast, slow = index.rolling(config.fast).mean(), index.rolling(config.slow).mean()
    weights = pd.Series(np.where(fast > slow, config.allocation, 0.0), index=bars.index)
    return weights.where(slow.notna())


@dataclass
class Result:
    equity: pd.DataFrame
    trades: pd.DataFrame
    summary: dict
    positions: pd.DataFrame = field(default_factory=pd.DataFrame)
    actions: pd.DataFrame = field(default_factory=pd.DataFrame)
    benchmark_trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    rejected: pd.DataFrame = field(default_factory=pd.DataFrame)


def _commission(quantity: float, config: Config) -> float:
    return max(config.minimum_commission, quantity * config.commission_per_share) if quantity > 0 else 0.0


def _simulate(panel, signals, dates, config, benchmark=False):
    symbols = sorted(panel)
    cash, reserve = config.initial_cash, 0.0
    held = dict.fromkeys(symbols, 0.0)
    ledger, fills, positions, actions, rejected = [], [], [], [], []
    slip = config.slippage_bps / 10_000
    for number, date in enumerate(dates):
        rows = {symbol: panel[symbol].loc[date] for symbol in symbols}
        for symbol, row in rows.items():
            before = held[symbol]
            held[symbol] *= row.split_ratio
            if row.split_ratio != 1:
                actions.append({"date": date, "symbol": symbol, "kind": "split",
                                "ratio": row.split_ratio, "shares_before": before,
                                "shares_after": held[symbol], "distribution_credit": 0.0})
            # Entitlement belongs to the position carried across the ex-date.
            # Distributions are segregated and never fund purchases in this model.
            credit = held[symbol] * row.dividend
            if row.dividend:
                reserve += credit
                actions.append({"date": date, "symbol": symbol, "kind": "distribution",
                                "ratio": 1.0, "shares_before": held[symbol],
                                "shares_after": held[symbol], "distribution_credit": credit})
        investable = cash + sum(held[symbol] * rows[symbol].open for symbol in symbols)
        desired = {}
        if not benchmark or number == 0:
            for symbol in symbols:
                weight = 1 / len(symbols) if benchmark else signals[symbol].loc[date]
                desired[symbol] = held[symbol] if pd.isna(weight) else float(math.floor(
                    investable * weight / (rows[symbol].open * (1 + slip))))
        else:
            desired = held.copy()

        def fill(symbol, action, quantity):
            nonlocal cash
            if quantity <= 1e-10:
                return
            price = rows[symbol].open * (1 + slip if action == "BUY" else 1 - slip)
            fee = _commission(quantity, config)
            delta = -quantity * price - fee if action == "BUY" else quantity * price - fee
            if cash + delta < -1e-7:
                rejected.append({"date": date, "symbol": symbol, "action": action,
                                 "quantity": quantity, "reason": "insufficient_cash_for_costs"})
                return
            cash = max(0.0, cash + delta)
            held[symbol] += quantity if action == "BUY" else -quantity
            held[symbol] = max(0.0, held[symbol])
            fills.append({"date": date, "symbol": symbol, "action": action,
                          "quantity": quantity, "price": price, "commission": fee,
                          "slippage_cost": quantity * abs(price - rows[symbol].open),
                          "cash_after": cash, "shares_after": held[symbol]})

        for symbol in symbols:
            fill(symbol, "SELL", max(0.0, held[symbol] - desired[symbol]))
        requested = {symbol: math.floor(max(0.0, desired[symbol] - held[symbol]) + 1e-9)
                     for symbol in symbols}

        def buy_cost(scale):
            quantities = {symbol: math.floor(quantity * scale) for symbol, quantity in requested.items()}
            cost = sum(quantity * rows[symbol].open * (1 + slip) + _commission(quantity, config)
                       for symbol, quantity in quantities.items())
            return cost, quantities

        cost, quantities = buy_cost(1.0)
        if cost > cash:
            # Allocate shared cash proportionally rather than by ticker order.
            low, high = 0.0, 1.0
            for _ in range(50):
                midpoint = (low + high) / 2
                if buy_cost(midpoint)[0] <= cash:
                    low = midpoint
                else:
                    high = midpoint
            _, quantities = buy_cost(low)
        for symbol in symbols:
            fill(symbol, "BUY", quantities[symbol])
        market_value = sum(held[symbol] * rows[symbol].close for symbol in symbols)
        equity = cash + reserve + market_value
        ledger.append({"date": date, "cash": cash, "distribution_reserve": reserve,
                       "market_value": market_value, "equity": equity,
                       "exposure": market_value / equity})
        positions.append({"date": date, **held})
    trade_columns = ["date", "symbol", "action", "quantity", "price", "commission",
                     "slippage_cost", "cash_after", "shares_after"]
    action_columns = ["date", "symbol", "kind", "ratio", "shares_before", "shares_after", "distribution_credit"]
    return (pd.DataFrame(ledger).set_index("date"), pd.DataFrame(fills, columns=trade_columns),
            pd.DataFrame(positions).set_index("date"), pd.DataFrame(actions, columns=action_columns),
            pd.DataFrame(rejected, columns=["date", "symbol", "action", "quantity", "reason"]))


def metrics(curve: pd.DataFrame, trades: pd.DataFrame, initial: float) -> dict:
    values = curve.equity.to_numpy()
    returns = pd.Series(np.r_[values[0] / initial - 1, values[1:] / values[:-1] - 1])
    volatility = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    peaks = np.maximum.accumulate(np.r_[initial, values])[1:]
    return {
        "initial_equity": initial, "final_equity": float(values[-1]),
        "net_return": float(values[-1] / initial - 1),
        "annualized_return": float((values[-1] / initial) ** (252 / len(values)) - 1),
        "max_drawdown": float((1 - values / peaks).max()),
        "sharpe_zero_risk_free": float(returns.mean() / volatility * math.sqrt(252)) if volatility > 0 else 0.0,
        "annualized_volatility": volatility * math.sqrt(252),
        "average_exposure": float(curve.exposure.mean()), "fills": len(trades),
        "commissions": float(trades.commission.sum()),
        "slippage_cost": float(trades.slippage_cost.sum()),
        "distributions_not_reinvested": float(curve.distribution_reserve.iloc[-1]),
        "ending_trading_cash": float(curve.cash.iloc[-1]),
    }


def run_portfolio(panel: dict[str, pd.DataFrame], config: Config,
                  start: str | None = None, end: str | None = None) -> Result:
    if not panel or len(panel) * config.allocation > 1 + 1e-10:
        raise ValueError("Need a nonempty universe whose combined target weights do not exceed 100%")
    clean = {symbol: validate_actions(bars.reset_index()) for symbol, bars in panel.items()}
    index = next(iter(clean.values())).index
    if any(not bars.index.equals(index) for bars in clean.values()):
        raise ValueError("All symbols must have exactly the same dates; missing data cannot be filled")
    dates = index[(index >= (start or str(index[0].date()))) & (index < (end or "2200-01-01"))]
    if len(dates) == 0 or (start is None and len(dates) <= config.slow):
        raise ValueError("Not enough history for the requested backtest")
    if start is not None and int((index < dates[0]).sum()) < config.slow:
        raise ValueError("Need at least slow-window bars strictly before the evaluation period")
    signals = {symbol: target_weights(bars, config).shift(1) for symbol, bars in clean.items()}
    curve, trades, positions, actions, rejected = _simulate(clean, signals, dates, config)
    benchmark, benchmark_trades, _, benchmark_actions, benchmark_rejected = _simulate(
        clean, signals, dates, config, benchmark=True)
    for column in ["equity", "cash", "distribution_reserve", "exposure"]:
        curve[f"benchmark_{column}"] = benchmark[column]
    curve["benchmark_net"] = benchmark.equity
    for label, values in [("strategy", curve.equity), ("benchmark", benchmark.equity)]:
        peaks = np.maximum.accumulate(np.r_[config.initial_cash, values.to_numpy()])[1:]
        curve[f"{label}_drawdown"] = values / peaks - 1
    actions["book"], benchmark_actions["book"] = "strategy", "benchmark"
    rejected["book"], benchmark_rejected["book"] = "strategy", "benchmark"
    summary = {**metrics(curve, trades, config.initial_cash), "config": asdict(config),
               "start": str(dates[0].date()), "end": str(dates[-1].date()), "bars": len(dates),
               "universe": sorted(clean), "ending_positions": positions.iloc[-1].to_dict(),
               "benchmark": metrics(benchmark, benchmark_trades, config.initial_cash),
               "benchmark_definition": "equal-weight buy-and-hold; same fees/slippage; distributions not reinvested",
               "liquidated_at_end": False, "rejected_orders": len(rejected) + len(benchmark_rejected),
               "distribution_policy": "ex-date entitlement segregated; never available for purchases",
               "fractional_policy": "whole-share purchases; split-generated fractions may be sold",
               "signal_basis": "forward-only total-return index; previous close -> next open"}
    return Result(curve, trades, summary, positions, pd.concat([actions, benchmark_actions], ignore_index=True),
                  benchmark_trades, pd.concat([rejected, benchmark_rejected], ignore_index=True))


def run_backtest(bars: pd.DataFrame, config: Config) -> Result:
    """Compatibility helper; unspecified actions mean no actions (synthetic tests).

    Research CLI inputs always require explicit action columns and provenance.
    """
    bars = bars.copy()
    if "dividend" not in bars:
        bars["dividend"] = 0.0
    if "split_ratio" not in bars:
        bars["split_ratio"] = 1.0
    result = run_portfolio({"asset": bars}, config)
    result.equity["shares"] = result.positions.asset
    result.summary["ending_shares"] = float(result.positions.asset.iloc[-1])
    return result
