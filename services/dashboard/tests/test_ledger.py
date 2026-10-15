from types import SimpleNamespace as NS

import pytest

from myquant_dashboard.broker import Broker, paper_account
from myquant_dashboard.store import Store, public_state


@pytest.mark.parametrize("accounts", [["U123"], ["DU123", "U456"], ["F123"], []])
def test_only_paper_accounts_can_connect(accounts):
    with pytest.raises(ValueError):
        paper_account(accounts)


def test_ledger_cannot_mix_accounts(store):
    store.bind_account("DU123")
    with pytest.raises(ValueError):
        store.bind_account("DU456")


def test_order_claim_is_atomic_and_unknown_order_is_never_reclaimed(settings, store, order):
    another = Store(settings.trade_db)
    try:
        assert store.claim(order["id"])
        assert not another.claim(order["id"])
        another.uncertain()
        assert store.db.execute("SELECT status FROM orders").fetchone()[0] == "UNKNOWN"
        assert not store.claim(order["id"])
        store.plan(order)
        assert store.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
    finally:
        another.close()


def broker_with_fake(settings, store):
    obj = object.__new__(Broker)
    obj.settings, obj.store, obj.account = settings, store, "DU123"
    obj.ib = NS(managedAccounts=lambda: ["DU123"])
    return obj


def trade(order, status="Submitted", filled=0):
    return NS(order=NS(account="DU123",orderRef=order["id"],action="BUY",totalQuantity=10,lmtPrice=100,
                        orderId=5,permId=123,clientId=71),
              orderStatus=NS(status=status,filled=filled),contract=NS(symbol="AAPL"))


def test_submitted_and_broker_filled_status_do_not_invent_execution_records(settings, store, order):
    broker = broker_with_fake(settings, store)
    broker.on_order(trade(order))
    state = public_state(settings.trade_db)
    assert state["orders"][0]["status"] == "SUBMITTED" and not state["fills"]
    broker.on_order(trade(order,"Filled",10))
    assert public_state(settings.trade_db)["fills"] == []


def test_execution_id_deduplicates_and_commission_can_arrive_later(settings, store, order):
    broker = broker_with_fake(settings, store)
    from datetime import datetime, timezone
    execution = NS(acctNumber="DU123",execId="exec-1",permId=123,clientId=71,orderId=5,shares=4,price=99,side="BOT")
    fill = NS(execution=execution,contract=NS(symbol="AAPL"),time=datetime.now(timezone.utc),
              commissionReport=NS(execId="",commission=0,currency="USD"))
    broker.on_fill(trade(order,filled=4),fill)
    broker.on_fill(trade(order,filled=4),fill)
    state = public_state(settings.trade_db)
    assert len(state["fills"]) == 1 and state["fills"][0]["quantity"] == 4
    assert state["fills"][0]["commission"] is None
    assert state["orders"][0]["status"] == "PARTIALLY_FILLED"
    broker.on_commission(None,fill,NS(execId="exec-1",commission=.75,currency="USD"))
    state = public_state(settings.trade_db)
    assert state["fills"][0]["commission"] == .75
    assert state["fills"][0]["reason"] == order["reason"]


def test_submit_guard_rejects_live_account_before_any_claim(settings, store, order):
    from dataclasses import replace
    broker = broker_with_fake(replace(settings,execute_paper_orders=True),store)
    broker.ib = NS(managedAccounts=lambda:["U123"])
    with pytest.raises(ValueError):
        broker.submit(order)
    assert store.db.execute("SELECT status FROM orders").fetchone()[0] == "PLANNED"


def test_records_survive_process_connection_reopen(settings, store, order):
    other = Store(settings.trade_db)
    try:
        assert other.db.execute("SELECT reason FROM orders").fetchone()[0] == order["reason"]
    finally:
        other.close()


def test_execution_only_does_not_invent_complete_parent_order(settings,store):
    from datetime import datetime,timezone
    execution=NS(acctNumber="DU123",execId="imported-exec",permId=99,clientId=10,orderId=5,
                 orderRef="",shares=4,cumQty=4,price=100,side="BOT")
    fill=NS(execution=execution,contract=NS(symbol="AAPL"),time=datetime.now(timezone.utc),
            commissionReport=NS(execId="",commission=0,currency="USD"))
    broker=broker_with_fake(settings,store)
    broker.ib=NS(reqAllOpenOrders=lambda:[],reqCompletedOrders=lambda **kwargs:[],
                 reqExecutions=lambda *_:[fill],trades=lambda:[])
    broker.reconcile()
    state=public_state(settings.trade_db)
    assert state["orders"][0]["status"]=="UNKNOWN"
    assert state["orders"][0]["quantity"]==0
    assert len(state["fills"])==1 and state["fills"][0]["quantity"]==4


def test_delayed_or_old_quotes_cannot_be_used_for_orders(settings,store):
    from datetime import datetime,timedelta,timezone
    broker=broker_with_fake(settings,store)
    broker.contract=lambda _: (NS(),.01)
    ticker=NS(marketDataType=3,bid=100,ask=101,time=datetime.now(timezone.utc))
    broker.ib=NS(reqTickers=lambda _:[ticker])
    with pytest.raises(ValueError,match="实时"):
        broker.quote("AAPL")
    ticker.marketDataType=1;ticker.time-=timedelta(minutes=5)
    with pytest.raises(ValueError,match="实时"):
        broker.quote("AAPL")


def test_live_port_is_rejected_before_connect(settings,store):
    from dataclasses import replace
    with pytest.raises(ValueError):
        Broker(replace(settings,ib_port=4001),store)


def test_schema_upgrade_preserves_old_equity_history(tmp_path):
    import sqlite3
    path=tmp_path/"old.sqlite3"
    db=sqlite3.connect(path)
    db.execute("CREATE TABLE equity(id INTEGER PRIMARY KEY,observed_at TEXT,net_liq REAL,cash REAL,currency TEXT)")
    db.execute("INSERT INTO equity VALUES(1,'2024-07-05T14:00:00+00:00',100000,100000,'USD')")
    db.commit();db.close()
    upgraded=Store(path)
    try:
        assert upgraded.db.execute("SELECT net_liq,daily_pnl FROM equity").fetchone()[0]==100000
        assert public_state(path)["history"][0]["daily_pnl"] is None
    finally:upgraded.close()
