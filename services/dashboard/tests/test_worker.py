from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pandas as pd
import pandas_market_calendars as calendars
import pytest

from myquant_dashboard.worker import Worker, make_order, sessions
from myquant.engine import Config


class FakeBroker:
    def __init__(self, store):
        self.store, self.account, self.submitted = store, "DU123", []
        self.held = 0
        dates = calendars.get_calendar("NYSE").valid_days("2023-01-01","2024-07-03")
        self.bars = [NS(date=day.date(),close=100+index*.1) for index,day in enumerate(dates)]

    def reconcile(self):
        self.store.uncertain()

    def snapshot(self):
        from myquant_dashboard.store import utcnow
        return {"account": self.account,"currency":"USD","net_liq":100000,"usd_cash":100000,
                "cash":100000,"updated_at":utcnow(),"unrealized_pnl":0,"realized_pnl":0,
                "positions": [{"symbol":"AAPL","quantity":self.held}] if self.held else []}

    def history(self,symbol):
        return self.bars

    def open_orders(self):
        return self.store.db.execute("SELECT * FROM orders WHERE status='SUBMITTED'").fetchall()

    def quote(self,symbol):
        return {"ask":100,"bid":99.9,"tick":.01}

    def submit(self,order):
        if not self.store.claim(order["id"]):
            return False
        with self.store.db:
            self.store.db.execute("UPDATE orders SET status='SUBMITTED' WHERE id=?",(order["id"],))
        self.submitted.append(order)
        return True


def test_monitor_records_signals_without_submitting(settings,store):
    broker=FakeBroker(store)
    Worker(settings,store,broker).cycle(datetime(2024,7,5,15,tzinfo=timezone.utc))
    assert store.db.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1
    assert store.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
    assert broker.submitted == []


def test_repeated_worker_cycles_do_not_duplicate_order(settings,store):
    broker=FakeBroker(store)
    worker=Worker(replace(settings,execute_paper_orders=True),store,broker)
    for _ in range(3):
        worker.cycle(datetime(2024,7,5,15,tzinfo=timezone.utc))
    assert len(broker.submitted) == 1
    assert store.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
    assert store.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 0
    assert "均线" in broker.submitted[0]["reason"]


def test_uncertain_submission_requires_reconciliation_and_is_never_retried(settings,store):
    broker=FakeBroker(store)
    worker=Worker(replace(settings,execute_paper_orders=True),store,broker)
    worker.cycle(datetime(2024,7,5,15,tzinfo=timezone.utc))
    with store.db:
        store.db.execute("UPDATE orders SET status='SUBMITTING'")
    worker.cycle(datetime(2024,7,5,15,tzinfo=timezone.utc))
    assert len(broker.submitted) == 1
    assert store.db.execute("SELECT status FROM orders").fetchone()[0] == "UNKNOWN"


def test_stale_or_missing_internal_daily_bar_blocks_signal(settings,store):
    broker=FakeBroker(store)
    broker.bars=[bar for bar in broker.bars if str(bar.date)!="2024-06-20"]
    Worker(replace(settings,execute_paper_orders=True),store,broker).cycle(datetime(2024,7,5,15,tzinfo=timezone.utc))
    assert not broker.submitted
    assert store.db.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 0
    assert "缺失交易日" in store.get_meta("worker")["message"]


def test_manual_holdings_are_not_adopted_or_liquidated(settings,store):
    broker=FakeBroker(store)
    broker.held=10
    Worker(replace(settings,execute_paper_orders=True),store,broker).cycle(datetime(2024,7,5,15,tzinfo=timezone.utc))
    assert not broker.submitted
    assert "不自动接管" in store.get_meta("worker")["message"]


def test_early_close_is_respected_and_new_signal_waits(settings,store):
    broker=FakeBroker(store)
    Worker(replace(settings,execute_paper_orders=True),store,broker).cycle(datetime(2024,7,3,18,tzinfo=timezone.utc))
    assert not broker.submitted
    assert sessions(datetime(2024,7,3,18,tzinfo=timezone.utc)) == ("2024-07-03",False)
    assert sessions(datetime(2024,7,3,16,tzinfo=timezone.utc)) == ("2024-07-02",True)


def test_limit_price_rounding_stays_within_budget_and_never_borrows(settings,store):
    from myquant_dashboard.worker import create_signal
    broker=FakeBroker(store)
    item=create_signal("DU123","AAPL","2024-07-03",list(range(100,170)),Config(),"test-protocol")
    snapshot=broker.snapshot()
    order=make_order(store,item,snapshot,broker.quote("AAPL"),Config())
    assert order["quantity"]*order["limit_price"]<=20000
    snapshot["usd_cash"]=1
    with pytest.raises(ValueError,match="现金不足"):
        make_order(store,item,snapshot,broker.quote("AAPL"),Config())
