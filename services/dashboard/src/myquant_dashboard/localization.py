"""仅翻译展示与导出，账本中的标识符和券商状态码保持原值。"""

COLUMNS_ZH = {
    "id": "记录编号", "account": "模拟账户", "symbol": "股票代码", "session": "信号数据日期",
    "target": "目标仓位比例", "fast": "快均线", "slow": "慢均线", "reason": "策略原因",
    "source": "数据来源", "created_at": "创建时间（含时区）", "updated_at": "更新时间（含时区）",
    "signal_id": "关联信号编号", "action": "买卖方向", "quantity": "数量（股）",
    "limit_price": "限价（美元）", "status": "订单状态", "filled": "已成交数量（股）",
    "broker_order_id": "券商订单编号", "perm_id": "券商永久订单编号", "exec_id": "券商成交编号",
    "order_id": "关联订单编号", "price": "成交价（美元）", "commission": "手续费",
    "commission_currency": "手续费币种", "executed_at": "成交时间（含时区）",
    "recorded_at": "记录时间（含时区）", "observed_at": "账户快照时间（含时区）",
    "net_liq": "账户净资产", "cash": "账户现金", "currency": "账户基础币种", "daily_pnl": "券商当日盈亏",
}
STATUS_ZH = {
    "PLANNED": "计划，未提交", "SUBMITTING": "提交中", "PRE_SUBMITTED": "券商预接受",
    "SUBMITTED": "已提交，未全部成交", "PARTIALLY_FILLED": "部分成交", "FILLED": "券商报告已成交",
    "CANCELLED": "已取消", "REJECTED": "被拒绝", "UNKNOWN": "待核对", "PENDING_CANCEL": "撤单待确认",
}


def display_value(column, value):
    if column == "action":
        return {"BUY": "买入", "SELL": "卖出"}.get(value, value)
    if column == "status":
        return STATUS_ZH.get(value, value)
    if column in {"currency", "commission_currency"}:
        return {"USD": "美元", "HKD": "港元", "CNY": "人民币", "EUR": "欧元"}.get(value, value)
    if column == "source":
        return {"IBKR ADJUSTED_LAST": "IBKR 复权日线",
                "IBKR ADJUSTED_LAST; observed at signal creation; not revised retrospectively":
                "IBKR 复权日线；按信号创建时记录，不追溯改写"}.get(value, value)
    return value
