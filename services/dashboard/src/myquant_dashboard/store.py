"""Durable trading ledger. The web process opens this database read-only."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def connect(path: Path, readonly=False):
    if readonly:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
        connection.execute("PRAGMA query_only=ON")
    else:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.db = connect(self.path)
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS signals(
            id TEXT PRIMARY KEY, account TEXT NOT NULL, symbol TEXT NOT NULL,
            session TEXT NOT NULL, target REAL NOT NULL, fast REAL NOT NULL, slow REAL NOT NULL,
            reason TEXT NOT NULL, created_at TEXT NOT NULL, source TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS orders(
            id TEXT PRIMARY KEY, signal_id TEXT, account TEXT NOT NULL, symbol TEXT NOT NULL,
            action TEXT NOT NULL, quantity REAL NOT NULL, limit_price REAL,
            status TEXT NOT NULL, filled REAL NOT NULL DEFAULT 0,
            broker_order_id INTEGER, perm_id INTEGER, reason TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
          CREATE UNIQUE INDEX IF NOT EXISTS strategy_signal_order ON orders(signal_id) WHERE signal_id IS NOT NULL;
          CREATE UNIQUE INDEX IF NOT EXISTS broker_perm_id ON orders(account,perm_id) WHERE perm_id>0;
          CREATE TABLE IF NOT EXISTS fills(
            exec_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, account TEXT NOT NULL,
            symbol TEXT NOT NULL, action TEXT NOT NULL, quantity REAL NOT NULL, price REAL NOT NULL,
            commission REAL, commission_currency TEXT, executed_at TEXT NOT NULL, recorded_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS equity(
            id INTEGER PRIMARY KEY AUTOINCREMENT, observed_at TEXT NOT NULL,
            net_liq REAL NOT NULL, cash REAL, currency TEXT NOT NULL, daily_pnl REAL);
          CREATE TABLE IF NOT EXISTS bars(
            symbol TEXT NOT NULL, session TEXT NOT NULL, close REAL NOT NULL,
            fetched_at TEXT NOT NULL, PRIMARY KEY(symbol,session));
          CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            level TEXT NOT NULL, message TEXT NOT NULL);
        """)
        if "daily_pnl" not in {row[1] for row in self.db.execute("PRAGMA table_info(equity)")}:
            self.db.execute("ALTER TABLE equity ADD COLUMN daily_pnl REAL")
        self.db.commit()
        self.path.chmod(0o600)

    def close(self):
        self.db.close()

    def meta(self, key, value):
        with self.db:
            self.db.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (key, json.dumps(value, allow_nan=False)))

    def get_meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def heartbeat(self, connected, message, **extra):
        self.meta("worker", {"heartbeat_at": utcnow(), "connected": connected, "message": message, **extra})

    def account_snapshot(self, snapshot):
        previous = self.get_meta("account")
        if previous and previous["currency"] != snapshot["currency"]:
            raise ValueError("Account base currency changed; use a separate ledger")
        with self.db:
            self.db.execute("INSERT INTO meta VALUES('account',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (json.dumps(snapshot, allow_nan=False),))
            if snapshot.get("net_liq") is not None:
                self.db.execute("INSERT INTO equity(observed_at,net_liq,cash,currency,daily_pnl) VALUES(?,?,?,?,?)",
                                (snapshot["updated_at"], snapshot["net_liq"], snapshot.get("cash"), snapshot["currency"],snapshot.get("daily_pnl")))

    def bind_account(self, account):
        previous = self.get_meta("bound_account")
        if previous and previous != account:
            raise ValueError("Ledger is bound to a different account; use separate storage")
        self.meta("bound_account", account)

    def signal(self, item):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO signals VALUES(:id,:account,:symbol,:session,:target,:fast,:slow,:reason,:created_at,:source)", item)
        return dict(self.db.execute("SELECT * FROM signals WHERE id=?", (item["id"],)).fetchone())

    def plan(self, item):
        with self.db:
            self.db.execute("""INSERT OR IGNORE INTO orders
                (id,signal_id,account,symbol,action,quantity,limit_price,status,reason,created_at,updated_at)
                VALUES(:id,:signal_id,:account,:symbol,:action,:quantity,:limit_price,'PLANNED',:reason,:created_at,:created_at)""", item)
        return self.db.execute("SELECT * FROM orders WHERE signal_id=?", (item["signal_id"],)).fetchone()

    def claim(self, order_id):
        # Commit the submitting state before any network call. A crashed claim is
        # reconciled, never automatically resent. BEGIN/UPDATE serializes writers.
        with self.db:
            result = self.db.execute("UPDATE orders SET status='SUBMITTING',updated_at=? WHERE id=? AND status='PLANNED'",
                                     (utcnow(), order_id))
        return result.rowcount == 1

    def uncertain(self):
        with self.db:
            self.db.execute("UPDATE orders SET status='UNKNOWN',updated_at=? WHERE status='SUBMITTING'", (utcnow(),))

    def broker_order(self, item):
        current = self.db.execute("SELECT * FROM orders WHERE id=? OR (account=? AND perm_id=? AND perm_id>0)",
                                  (item["id"], item["account"], item.get("perm_id", 0))).fetchone()
        if current:
            terminal = {"FILLED", "CANCELLED", "REJECTED"}
            status = item["status"]
            if current["status"] in terminal and status not in terminal:
                status = current["status"]
            with self.db:
                self.db.execute("""UPDATE orders SET status=?, filled=MAX(filled,?), broker_order_id=?,
                    perm_id=CASE WHEN ?>0 THEN ? ELSE perm_id END, updated_at=? WHERE id=?""",
                    (status, item.get("filled", 0), item.get("broker_order_id"), item.get("perm_id", 0),
                     item.get("perm_id", 0), utcnow(), current["id"]))
            return current["id"]
        with self.db:
            self.db.execute("""INSERT INTO orders(id,signal_id,account,symbol,action,quantity,limit_price,status,
              filled,broker_order_id,perm_id,reason,created_at,updated_at)
              VALUES(:id,NULL,:account,:symbol,:action,:quantity,:limit_price,:status,:filled,:broker_order_id,
              :perm_id,:reason,:created_at,:created_at)""", item)
        return item["id"]

    def fill(self, item):
        with self.db:
            self.db.execute("""INSERT OR IGNORE INTO fills(exec_id,order_id,account,symbol,action,quantity,price,
                executed_at,recorded_at) VALUES(:exec_id,:order_id,:account,:symbol,:action,:quantity,:price,
                :executed_at,:recorded_at)""", item)

    def commission(self, exec_id, amount, currency):
        with self.db:
            self.db.execute("UPDATE fills SET commission=?,commission_currency=? WHERE exec_id=?", (amount, currency, exec_id))

    def managed_quantity(self, account, symbol):
        row = self.db.execute("""SELECT COALESCE(SUM(CASE WHEN f.action='BUY' THEN f.quantity ELSE -f.quantity END),0)
          FROM fills f JOIN orders o ON o.id=f.order_id WHERE f.account=? AND f.symbol=? AND o.signal_id IS NOT NULL""",
          (account, symbol)).fetchone()
        return float(row[0])


def public_state(path):
    empty = {"mode": "模拟交易", "broker": "IBKR PAPER", "account": None,
             "worker": {"connected": False, "message": "等待后台连接 IBKR 模拟账户"},
             "history": [], "signals": [], "orders": [], "fills": [], "counts": {}}
    if not path.exists():
        return empty
    db = connect(path, readonly=True)
    try:
        db.execute("BEGIN")
        with db:
            values = {row["key"]: json.loads(row["value"]) for row in db.execute("SELECT * FROM meta")}
            state = {**empty, "account": values.get("account"), "worker": values.get("worker", empty["worker"])}
            for table in ("signals", "orders"):
                order = "created_at" if table == "signals" else "updated_at"
                state[table] = [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY {order} DESC LIMIT 300")]
            state["fills"] = [dict(row) for row in db.execute("""SELECT f.*,o.reason,o.signal_id FROM fills f
                LEFT JOIN orders o ON o.id=f.order_id ORDER BY f.executed_at DESC LIMIT 300""")]
            count = db.execute("SELECT COUNT(*) FROM equity").fetchone()[0]
            stride = max(1, count // 1000)
            state["history"] = [dict(row) for row in db.execute("""SELECT * FROM equity
                WHERE id % ?=0 OR id IN (SELECT MIN(id) FROM equity UNION SELECT MAX(id) FROM equity) ORDER BY id""", (stride,))]
            state["counts"] = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                               for table in ("signals", "orders", "fills")}
            state["record_limit"] = 300
            return state
    finally:
        db.close()
