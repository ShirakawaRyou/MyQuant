"""中文研究报告；原始 CSV 和 JSON 字段保持稳定，供程序复核。"""

import hashlib
import json
import os
from pathlib import Path
import tempfile

STAGES_ZH = {"development": "开发区间", "validation": "验证区间", "holdout": "最终检验区间"}
COLUMNS_ZH = {
    "date": "日期", "symbol": "股票代码", "action": "买卖方向", "quantity": "成交数量（股）",
    "price": "成交价（美元，已含滑点）", "commission": "手续费（美元）",
    "slippage_cost": "滑点成本（美元）", "cash_after": "成交后可用现金（美元）",
    "shares_after": "操作后持股（股）", "shares_before": "操作前持股（股）",
    "cash": "策略可用现金（美元）", "distribution_reserve": "策略隔离分红（美元）",
    "market_value": "策略持仓市值（美元）", "equity": "策略净资产（美元）",
    "exposure": "策略仓位比例", "benchmark_equity": "基准净资产（美元）",
    "benchmark_cash": "基准可用现金（美元）", "benchmark_distribution_reserve": "基准隔离分红（美元）",
    "benchmark_exposure": "基准仓位比例", "benchmark_net": "基准扣费后净资产（美元）",
    "strategy_drawdown": "策略回撤比例（负值）", "benchmark_drawdown": "基准回撤比例（负值）",
    "kind": "公司行动类型", "ratio": "拆股比例（新股数除以旧股数）",
    "distribution_credit": "计入隔离余额的分红（美元）", "book": "所属组合",
    "reason": "未成交原因", "shares": "持股数量（股）",
}
VALUES_ZH = {
    "action": {"BUY": "买入", "SELL": "卖出"},
    "kind": {"split": "拆股", "distribution": "现金分红"},
    "book": {"strategy": "策略", "benchmark": "买入持有基准"},
    "reason": {"insufficient_cash_for_costs": "现金不足以支付成交金额和手续费"},
}


def chinese_table(frame, include_date=False):
    frame = frame.reset_index() if include_date else frame.copy()
    for column, mapping in VALUES_ZH.items():
        if column in frame:
            frame[column] = frame[column].map(lambda value: mapping.get(value, value))
    return frame.rename(columns=COLUMNS_ZH)


def format_summary(summary, output=None):
    stage = STAGES_ZH.get(summary.get("stage"), "历史回测")
    baseline = summary["benchmark"]
    lines = [f"{stage}运行完成：{summary['start']} 至 {summary['end']}（{summary['bars']} 个交易日）",
             f"策略累计收益：{summary['net_return']:.2%}；年化收益：{summary['annualized_return']:.2%}；"
             f"最大回撤：{summary['max_drawdown']:.2%}",
             f"买入持有基准累计收益：{baseline['net_return']:.2%}；最大回撤：{baseline['max_drawdown']:.2%}",
             f"策略成交：{summary['fills']} 笔；手续费：{summary['commissions']:,.2f} 美元；"
             f"滑点成本：{summary['slippage_cost']:,.2f} 美元",
             f"未成交记录：{summary['rejected_orders']} 条（策略与基准合计）"]
    if output is not None:
        lines += [f"中文报告：{output / 'report.md'}", f"中文逐笔成交：{output / '成交记录.csv'}"]
    return "\n".join(lines)


def save_result(result, output: Path) -> None:
    if output.exists() and any(output.iterdir()):
        raise ValueError("报告目录已有文件，请使用新的 --out 路径")
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "myquant-matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    # A licensed bundled font avoids desktop installation, CDNs and missing CJK glyphs.
    font = Path(__file__).parent / "fonts" / "NotoSansCJKsc-Regular.otf"
    font_manager.fontManager.addfont(str(font))
    family = font_manager.FontProperties(fname=font).get_name()
    output.mkdir(parents=True, exist_ok=True)
    for frame, raw, chinese, dated in [
        (result.equity, "equity.csv", "资产曲线.csv", True),
        (result.trades, "trades.csv", "成交记录.csv", False),
        (result.benchmark_trades, "benchmark_trades.csv", "基准成交记录.csv", False),
        (result.positions, "positions.csv", "每日持仓.csv", True),
        (result.actions, "corporate_actions.csv", "公司行动.csv", False),
        (result.rejected, "rejections.csv", "未成交记录.csv", False),
    ]:
        frame.to_csv(output / raw, index=dated, index_label="date" if dated else None)
        translated = chinese_table(frame, dated)
        if raw == "rejections.csv":
            translated = translated.rename(columns={"成交数量（股）": "未成交数量（股）"})
        translated.to_csv(output / chinese, index=False, encoding="utf-8-sig")
    summary, baseline = result.summary, result.summary["benchmark"]
    (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (output / "display.json").write_text(json.dumps({"language": "zh-CN", "font": font.name,
        "font_sha256": hashlib.sha256(font.read_bytes()).hexdigest(),
        "csv_encoding": "utf-8-sig", "machine_data": "Original CSV and summary.json are unchanged"},
        indent=2) + "\n", encoding="utf-8")
    stage = STAGES_ZH.get(summary.get("stage"), "历史回测")
    with plt.rc_context({"font.family": family, "axes.unicode_minus": False}):
        figure, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]})
        for column, label in [("equity", "策略（扣除费用）"), ("benchmark_net", "买入持有基准（扣除费用）")]:
            axes[0].plot(result.equity.index, result.equity[column], label=label, linewidth=1.4)
        for column, label in [("strategy_drawdown", "策略"), ("benchmark_drawdown", "买入持有基准")]:
            axes[1].plot(result.equity.index, result.equity[column] * 100, label=label)
        axes[0].set(title=f"{stage}｜相同初始资金、手续费与滑点模型", ylabel="净资产（美元）")
        axes[1].set(ylabel="回撤（%）", xlabel="日期")
        for axis in axes:
            axis.grid(alpha=0.25)
            axis.legend(loc="best")
        figure.autofmt_xdate()
        figure.tight_layout()
        figure.savefig(output / "equity.png", dpi=160)
        plt.close(figure)
    lines = [f"# {stage}回测报告", "", f"回测日期：{summary['start']} 至 {summary['end']}。"
             f"共 {summary['bars']} 个交易日；金额单位为美元。", "",
             "| 指标 | 策略（扣除费用） | 买入持有基准（扣除费用） |", "|---|---:|---:|"]
    for label, key in [("累计收益", "net_return"), ("年化收益", "annualized_return"),
                       ("最大回撤", "max_drawdown"), ("平均仓位", "average_exposure"),
                       ("年化波动率", "annualized_volatility")]:
        lines.append(f"| {label} | {summary[key]:.2%} | {baseline[key]:.2%} |")
    for label, key in [("期初净资产", "initial_equity"), ("期末净资产", "final_equity"),
                       ("手续费合计", "commissions"), ("滑点成本合计", "slippage_cost"),
                       ("隔离分红余额", "distributions_not_reinvested"),
                       ("夏普比率（无风险利率按零计）", "sharpe_zero_risk_free")]:
        lines.append(f"| {label} | {summary[key]:,.2f} | {baseline[key]:,.2f} |")
    lines += [f"| 成交笔数 | {summary['fills']} | {baseline['fills']} |", "",
              "![策略与买入持有基准的净资产及回撤曲线](equity.png)", "",
              "## 查看每笔操作", "",
              "[中文成交记录](成交记录.csv) · [基准成交记录](基准成交记录.csv) · "
              "[每日持仓](每日持仓.csv) · [资产曲线](资产曲线.csv) · "
              "[拆股及分红](公司行动.csv) · [未成交记录](未成交记录.csv)", "",
              "成交记录中每行是一笔模拟成交，不是一轮完整买卖。成交价已包含滑点；"
              "滑点成本是其中不利价差的单独披露，不能再次扣除。手续费另计。"
              "成交后现金不包括隔离分红。仓位与回撤表中的比例使用小数表示，例如 0.2 为 20%。", "",
              "## 策略与计算口径", "",
              f"股票池：{'、'.join(summary['universe'])}。快均线 {summary['config']['fast']} 日，"
              f"慢均线 {summary['config']['slow']} 日；快线高于慢线时目标仓位 "
              f"{summary['config']['allocation']:.0%}，否则目标为零。"
              "收盘判断，下一交易日开盘再平衡；先卖后买，共享现金，不融资、不做空。", "",
              "已显式处理拆股与分红。分红在除息日计入隔离权益，期间不再投资；"
              "期末按市价估值，不强制卖出。基准使用同样的初始资金和费用模型。", "",
              "历史结果不代表未来收益。固定存续股票池存在幸存者与选择偏差；"
              "当前数据快照可能含事后修订。日线模型不完整模拟税、利息、交收、市场冲击或成交量限制。", "",
              "原始英文字段 CSV 与 summary.json 用于程序读取及溯源；中文表格采用带字节顺序标记的 UTF-8 编码。", ""]
    if summary.get("data_source", {}).get("source") == "synthetic":
        lines += ["本报告使用合成数据，仅验证软件流程，不能证明策略有效。", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
