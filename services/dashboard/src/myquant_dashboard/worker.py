"""Independent IBKR monitor and optional paper-order loop; no HTTP dependency."""

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
import logging
import math
import signal
import time

from filelock import FileLock, Timeout

import pandas as pd
import pandas_market_calendars as calendars

from myquant.engine import Config
from myquant.study import read_protocol

from .broker import Broker, paper_account
from .settings import Settings
from .store import Store, utcnow


def sessions(now):
    schedule = calendars.get_calendar("NYSE").schedule(
        start_date=(now - timedelta(days=14)).date(), end_date=now.date())
    closed = schedule[schedule.market_close <= now]
    if closed.empty:
        raise ValueError("无法确定最近已收盘的美股交易日")
    is_open = bool(((schedule.market_open <= now) & (now < schedule.market_close)).any())
    return str(closed.index[-1].date()), is_open


def create_signal(account, symbol, session, closes, config, protocol_hash):
    if len(closes) < config.slow or any(not math.isfinite(value) or value <= 0 for value in closes):
        raise ValueError("日线不足或价格非法")
    fast = sum(closes[-config.fast:]) / config.fast
    slow = sum(closes[-config.slow:]) / config.slow
    target = config.allocation if fast > slow else 0.0
    reason = (f"{session} 已收盘日线：{config.fast}日均线 {fast:.4f} "
              f"{'高于' if fast > slow else '不高于'} {config.slow}日均线 {slow:.4f}；"
              f"目标为策略预算的 {target:.0%}，下一常规交易时段检查执行条件。")
    identifier = hashlib.sha256(f"{account}:{symbol}:{session}:{protocol_hash}".encode()).hexdigest()[:24]
    return {"id": identifier, "account": account, "symbol": symbol, "session": session,
            "target": target, "fast": fast, "slow": slow, "reason": reason, "created_at": utcnow(),
            "source": "IBKR ADJUSTED_LAST; observed at signal creation; not revised retrospectively"}


def make_order(store, signal_item, snapshot, quote, config):
    symbol = signal_item["symbol"]
    position = next((item for item in snapshot["positions"] if item["symbol"] == symbol), None)
    held = position["quantity"] if position else 0.0
    if held < 0 or not float(held).is_integer():
        raise ValueError("负持仓或零碎股需要人工核对，暂停自动操作")
    if abs(held - store.managed_quantity(snapshot["account"], symbol)) > 1e-6:
        raise ValueError("已有持仓与本策略成交账本不一致；不自动接管或处置手工持仓")
    if snapshot["currency"] != "USD" or snapshot["usd_cash"] is None:
        raise ValueError("缺少可核对的美元净值或现金，暂停自动操作")
    budget = min(config.initial_cash, snapshot["net_liq"])
    if budget <= 0:
        raise ValueError("策略预算不可用")
    reference = quote["ask"] if signal_item["target"] > 0 else quote["bid"]
    target = math.floor(budget * signal_item["target"] / reference)
    difference = target - held
    if difference == 0:
        return None
    action, quantity = ("BUY", difference) if difference > 0 else ("SELL", -difference)
    raw = (quote["ask"] * (1 + config.slippage_bps / 10000) if action == "BUY"
           else quote["bid"] * (1 - config.slippage_bps / 10000))
    tick = Decimal(str(quote["tick"]))
    price = float((Decimal(str(raw)) / tick).to_integral_value(
        rounding=ROUND_CEILING if action == "BUY" else ROUND_FLOOR) * tick)
    # Size once more at the actual limit so rounding cannot exceed the budget.
    if action == "BUY":
        target = math.floor(budget * signal_item["target"] / price)
        quantity = max(0, target - held)
    if quantity <= 0:
        return None
    fee = max(config.minimum_commission, quantity * config.commission_per_share)
    if action == "BUY" and quantity * price + fee > snapshot["usd_cash"]:
        raise ValueError("当前美元现金不足；不借款，也不预支未成交卖单的收入")
    return {"id": "MQP-" + signal_item["id"], "signal_id": signal_item["id"],
            "account": snapshot["account"], "symbol": symbol, "action": action,
            "quantity": quantity, "limit_price": price, "created_at": utcnow(),
            "reason": signal_item["reason"] + f" 当前持有 {held:g} 股，预算 ${budget:,.2f}；"
                      f"{action} {quantity:g} 股，限价 ${price:g}；仅常规交易时段 DAY 模拟单。"}


class Worker:
    def __init__(self, settings, store, broker=None):
        self.settings, self.store = settings, store
        self.protocol = read_protocol(settings.protocol)
        self.config = Config(**self.protocol["strategy"])
        self.protocol_hash = hashlib.sha256(settings.protocol.read_bytes()).hexdigest()
        self.broker = broker or Broker(settings, store)

    def cycle(self, now=None):
        now = now or datetime.now(timezone.utc)
        expected, market_open = sessions(now)
        self.broker.reconcile()
        snapshot = self.broker.snapshot()
        snapshot["strategy_budget_usd"] = self.config.initial_cash
        self.store.account_snapshot(snapshot)
        pending = self.broker.open_orders()
        uncertain = self.store.db.execute("SELECT COUNT(*) FROM orders WHERE status IN ('UNKNOWN','SUBMITTING') AND signal_id IS NOT NULL").fetchone()[0]
        last_message = "已同步；模拟执行已启用" if self.settings.execute_paper_orders else "已同步；仅监控与记录信号，模拟执行未启用"
        submitted = False
        for symbol in self.protocol["universe"]:
            try:
                last = self.store.db.execute("SELECT MAX(session) FROM bars WHERE symbol=?", (symbol,)).fetchone()[0]
                if last != expected:
                    bars = self.broker.history(symbol)
                    prepared = []
                    for bar in bars:
                        day = pd.Timestamp(bar.date).date().isoformat()
                        if day <= expected and math.isfinite(bar.close) and bar.close > 0:
                            prepared.append((symbol, day, float(bar.close), utcnow()))
                    with self.store.db:
                        self.store.db.executemany("INSERT INTO bars VALUES(?,?,?,?) ON CONFLICT(symbol,session) DO UPDATE SET close=excluded.close,fetched_at=excluded.fetched_at", prepared)
                rows = self.store.db.execute("SELECT * FROM bars WHERE symbol=? AND session<=? ORDER BY session DESC LIMIT ?",
                                             (symbol, expected, self.config.slow)).fetchall()
                if not rows or rows[0]["session"] != expected:
                    raise ValueError("最近已收盘日线缺失，不使用过期行情产生订单")
                closes = [row["close"] for row in reversed(rows)]
                required_dates = calendars.get_calendar("NYSE").valid_days(
                    start_date=(pd.Timestamp(expected) - pd.Timedelta(days=self.config.slow * 3)).date(),
                    end_date=expected).strftime("%Y-%m-%d").tolist()[-self.config.slow:]
                if [row["session"] for row in reversed(rows)] != required_dates:
                    raise ValueError("均线区间内存在缺失交易日，暂停生成信号")
                item = create_signal(self.broker.account, symbol, expected, closes, self.config, self.protocol_hash)
                item = self.store.signal(item)
                if not self.settings.execute_paper_orders:
                    continue
                if not market_open:
                    last_message = "信号已保存，等待下一常规交易时段"
                    continue
                if pending or uncertain or submitted:
                    last_message = "有挂单或待核对订单；等待券商状态确认后再计划后续订单"
                    continue
                if self.store.db.execute("SELECT 1 FROM orders WHERE signal_id=?", (item["id"],)).fetchone():
                    continue
                order = make_order(self.store, item, snapshot, self.broker.quote(symbol), self.config)
                if order:
                    stored = self.store.plan(order)
                    submitted = self.broker.submit(dict(stored))
            except (ValueError, OSError, RuntimeError) as error:
                # These diagnostic messages contain strategy data, never login credentials.
                last_message = f"{symbol}：{error}"
        self.store.heartbeat(True, last_message, orders_enabled=self.settings.execute_paper_orders,
                             latest_completed_session=expected, market_open=market_open,
                             order_synced_at=utcnow(), source="IBKR PAPER", protocol_hash=self.protocol_hash)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    settings.trade_db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = FileLock(settings.trade_db.parent / "worker.lock")
    try:
        lock.acquire(timeout=0)
    except Timeout:
        raise SystemExit("同一账本已经有独立后台运行，拒绝重复启动")
    store = Store(settings.trade_db)
    worker = Worker(settings, store)
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    connected = False
    try:
        while running:
            try:
                if not connected:
                    worker.broker.connect()
                    connected = True
                worker.cycle()
            except Exception as error:
                worker.broker.disconnect()
                connected = False
                store.heartbeat(False, f"IBKR 模拟账户连接或同步未就绪（{type(error).__name__}）；保留上次数据",
                                orders_enabled=settings.execute_paper_orders)
                logging.warning("IBKR sync unavailable: %s", type(error).__name__)
            if args.once:
                break
            for _ in range(settings.poll_seconds):
                if not running:
                    break
                if connected:
                    worker.broker.ib.sleep(1)
                else:
                    time.sleep(1)
    finally:
        worker.broker.disconnect()
        store.close()
        lock.release()


if __name__ == "__main__":
    main()
