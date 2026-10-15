"""Only this module communicates with IBKR. No credentials pass through the web."""

from datetime import datetime, timezone
import math
import re

from ib_async import ExecutionFilter, IB, LimitOrder, Stock

from .store import utcnow


def paper_account(accounts, requested=""):
    if not accounts or any(not re.fullmatch(r"DU\d+", account) for account in accounts):
        raise ValueError("仅支持 DU 模拟账户；拒绝实盘或未知账户类型")
    if requested:
        if requested not in accounts:
            raise ValueError("指定的模拟账户不在 Gateway 会话中")
        return requested
    if len(accounts) != 1:
        raise ValueError("多个模拟账户需要明确指定 IBKR_PAPER_ACCOUNT")
    return accounts[0]


def finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and abs(value) < 1e100 else None
    except (ValueError, TypeError):
        return None


class Broker:
    def __init__(self, settings, store):
        if settings.ib_port not in {4002, 4004, 7497, 7499}:
            raise ValueError("仅允许模拟 API 端口 4002/4004/7497/7499")
        self.settings, self.store = settings, store
        self.ib, self.account = IB(), None
        self.contracts = {}

    def connect(self):
        self.ib.connect(self.settings.ib_host, self.settings.ib_port,
                        clientId=self.settings.ib_client_id, timeout=12,
                        readonly=not self.settings.execute_paper_orders)
        self.account = paper_account(self.ib.managedAccounts(), self.settings.ib_account)
        self.store.bind_account(self.account)
        self.ib.orderStatusEvent += self.on_order
        self.ib.execDetailsEvent += self.on_fill
        self.ib.commissionReportEvent += self.on_commission
        self.ib.reqMarketDataType(1)
        self.pnl = self.ib.reqPnL(self.account)

    def disconnect(self):
        self.ib.disconnect()

    def on_order(self, trade):
        order, status = trade.order, trade.orderStatus
        if order.account != self.account:
            return
        identifier = order.orderRef or f"IB-{self.account}-{order.permId or str(order.clientId)+'-'+str(order.orderId)}"
        mapping = {"PendingSubmit": "SUBMITTING", "ApiPending": "SUBMITTING", "PreSubmitted": "PRE_SUBMITTED",
                   "Submitted": "SUBMITTED", "Filled": "FILLED", "Cancelled": "CANCELLED",
                   "ApiCancelled": "CANCELLED", "Inactive": "REJECTED", "PendingCancel": "PENDING_CANCEL"}
        state = mapping.get(status.status, "UNKNOWN")
        if 0 < status.filled < order.totalQuantity:
            state = "PARTIALLY_FILLED"
        self.store.broker_order({"id": identifier, "account": self.account, "symbol": trade.contract.symbol,
            "action": order.action, "quantity": float(order.totalQuantity), "limit_price": finite(order.lmtPrice),
            "status": state, "filled": float(status.filled), "broker_order_id": order.orderId,
            "perm_id": order.permId, "reason": "券商导入记录；无本项目策略信号，不推断操作原因", "created_at": utcnow()})

    def on_fill(self, trade, fill):
        execution = fill.execution
        if execution.acctNumber != self.account:
            return
        self.on_order(trade)
        ref = trade.order.orderRef or f"IB-{self.account}-{execution.permId or str(execution.clientId)+'-'+str(execution.orderId)}"
        existing = self.store.db.execute("SELECT id FROM orders WHERE id=? OR (account=? AND perm_id=? AND perm_id>0)",
                                         (ref, self.account, execution.permId)).fetchone()
        self.store.fill({"exec_id": execution.execId, "order_id": existing[0] if existing else ref,
            "account": self.account, "symbol": fill.contract.symbol,
            "action": "BUY" if execution.side in {"BOT", "BUY"} else "SELL",
            "quantity": float(execution.shares), "price": float(execution.price),
            "executed_at": fill.time.astimezone(timezone.utc).isoformat(), "recorded_at": utcnow()})
        report = fill.commissionReport
        if report.execId and finite(report.commission) is not None:
            self.store.commission(execution.execId, float(report.commission), report.currency)

    def on_commission(self, trade, fill, report):
        if fill.execution.acctNumber == self.account and finite(report.commission) is not None:
            self.store.commission(report.execId, float(report.commission), report.currency)

    def reconcile(self):
        for trade in self.ib.reqAllOpenOrders():
            self.on_order(trade)
        for trade in self.ib.reqCompletedOrders(apiOnly=False):
            self.on_order(trade)
        for fill in self.ib.reqExecutions(ExecutionFilter(acctCode=self.account)):
            # reqExecutions also populates IB's Trade objects, including orderRef.
            matches = [trade for trade in self.ib.trades() if trade.order.permId == fill.execution.permId
                       and trade.order.account == self.account]
            if matches:
                self.on_fill(matches[0], fill)
            else:
                from types import SimpleNamespace
                execution = fill.execution
                order = SimpleNamespace(account=self.account, orderRef=execution.orderRef,
                    permId=execution.permId, clientId=execution.clientId, orderId=execution.orderId,
                    action="BUY" if execution.side == "BOT" else "SELL", totalQuantity=0,
                    lmtPrice=0)
                trade = SimpleNamespace(order=order, contract=fill.contract,
                    orderStatus=SimpleNamespace(status="Unknown", filled=execution.cumQty))
                self.on_fill(trade, fill)
        self.store.uncertain()

    def snapshot(self):
        rows = self.ib.accountSummary(self.account) + self.ib.accountValues(self.account)
        net = next((row for row in rows if row.tag == "NetLiquidation" and finite(row.value) is not None), None)
        if net is None:
            raise ValueError("IBKR 账户摘要尚未就绪")
        currency = net.currency or "BASE"

        def value(tag):
            row = next((item for item in rows if item.tag == tag and item.currency == currency), None)
            return finite(row.value) if row else None

        cash_usd = [finite(row.value) for row in self.ib.accountValues(self.account)
                    if row.tag == "CashBalance" and row.currency == "USD"]
        positions = [{"symbol": item.contract.symbol, "quantity": float(item.position),
            "average_cost": finite(item.averageCost), "market_price": finite(item.marketPrice),
            "market_value": finite(item.marketValue), "unrealized_pnl": finite(item.unrealizedPNL),
            "currency": item.contract.currency} for item in self.ib.portfolio(self.account)]
        pnl = getattr(self, "pnl", None)
        return {"account": self.account, "currency": currency, "net_liq": float(net.value),
            "cash": value("TotalCashValue"), "unrealized_pnl": value("UnrealizedPnL"),
            "realized_pnl": value("RealizedPnL"), "usd_cash": cash_usd[0] if len(cash_usd) == 1 else None,
            "daily_pnl": finite(pnl.dailyPnL) if pnl else None,
            "positions": positions, "updated_at": utcnow(), "source": "IBKR account / portfolio"}

    def contract(self, symbol):
        if symbol not in self.contracts:
            details = self.ib.reqContractDetails(Stock(symbol, "SMART", "USD"))
            matches = [item for item in details if item.contract.secType == "STK" and item.contract.currency == "USD"]
            if len(matches) != 1 or matches[0].minTick <= 0:
                raise ValueError("股票合约或最小报价单位不明确")
            self.contracts[symbol] = (matches[0].contract, matches[0].minTick)
        return self.contracts[symbol]

    def history(self, symbol):
        contract, _ = self.contract(symbol)
        return self.ib.reqHistoricalData(contract, endDateTime="", durationStr="2 Y", barSizeSetting="1 day",
            whatToShow="ADJUSTED_LAST", useRTH=True, formatDate=2, keepUpToDate=False, timeout=30)

    def quote(self, symbol):
        contract, tick = self.contract(symbol)
        tickers = self.ib.reqTickers(contract)
        if len(tickers) != 1:
            raise ValueError("实时行情未就绪")
        ticker = tickers[0]
        if (ticker.marketDataType != 1 or finite(ticker.bid) is None or finite(ticker.ask) is None
                or ticker.bid <= 0 or ticker.ask < ticker.bid or ticker.time is None
                or not 0 <= (datetime.now(timezone.utc) - ticker.time).total_seconds() <= 120):
            raise ValueError("没有新鲜实时买卖报价；延迟或缺失行情只监控，不提交订单")
        return {"bid": ticker.bid, "ask": ticker.ask, "tick": tick, "updated_at": ticker.time.isoformat()}

    def open_orders(self):
        return [trade for trade in self.ib.reqAllOpenOrders() if trade.order.account == self.account]

    def submit(self, order):
        # Repeat account validation at the only network-writing boundary.
        if not self.settings.execute_paper_orders:
            raise ValueError("模拟订单执行未启用")
        paper_account(self.ib.managedAccounts(), self.account)
        if not self.store.claim(order["id"]):
            return False
        contract, _ = self.contract(order["symbol"])
        obj = LimitOrder(order["action"], order["quantity"], order["limit_price"],
                         account=self.account, orderRef=order["id"], tif="DAY", outsideRth=False)
        trade = self.ib.placeOrder(contract, obj)
        self.on_order(trade)
        self.ib.sleep(0.2)
        return True
