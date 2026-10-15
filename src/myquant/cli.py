"""云端美股历史研究与回测；本命令不连接交易账户。"""

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

from .data import demo_bars, write_bars
from .engine import Config, run_backtest
from .reporting import format_summary, save_result
from .research_data import fetch_snapshot, sha256, validate_actions
from .study import freeze, import_snapshot, read_protocol, run_stage, STAGES


def strategy_arguments(parser):
    parser.add_argument("--fast", type=int, default=20, help="快均线天数，默认 20")
    parser.add_argument("--slow", type=int, default=60, help="慢均线天数，默认 60")
    parser.add_argument("--allocation", type=float, default=0.20, help="单只股票目标仓位，默认 0.2")
    parser.add_argument("--cash", type=float, default=100_000, help="初始资金（美元），默认 100000")
    parser.add_argument("--commission-per-share", type=float, default=0.005, help="每股手续费（美元）")
    parser.add_argument("--minimum-commission", type=float, default=1.0, help="每笔最低手续费（美元）")
    parser.add_argument("--slippage-bps", type=float, default=5.0, help="单边滑点（基点），默认 5")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="myquant", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, title="可用命令")
    demo = commands.add_parser("demo", help="生成合成日线，仅用于验证软件")
    demo.add_argument("--output", type=Path, default=Path("data/demo-v2.csv"))
    backtest = commands.add_parser("backtest", help="单个 CSV 的探索性回测，需要显式公司行动数据")
    backtest.add_argument("--csv", type=Path, required=True)
    backtest.add_argument("--out", type=Path, required=True)
    backtest.add_argument("--price-basis", choices=["as-traded"], help="无元数据的 CSV 必须声明价格为当时实际单位")
    strategy_arguments(backtest)
    for name, description in {"fetch": "下载并校验历史数据快照", "import-csv": "导入并校验历史 CSV",
                              "freeze": "保存不可覆盖的实验冻结记录", "study": "按固定规则运行指定研究区间"}.items():
        subparser = commands.add_parser(name, help=description, description=description)
        subparser.add_argument("--config", type=Path, default=Path("research/protocol.json"), help="研究规则配置文件")
        subparser.add_argument("--out", type=Path, required=True, help="新的输出路径，已有结果不会覆盖")
        if name in ("freeze", "study"):
            subparser.add_argument("--data", type=Path, required=True, help="已校验的数据快照目录")
        if name == "import-csv":
            subparser.add_argument("--input-dir", type=Path, required=True)
            subparser.add_argument("--source-label", required=True)
            subparser.add_argument("--price-basis", choices=["as-traded"], required=True)
        if name == "study":
            subparser.add_argument("--freeze", type=Path, required=True, help="与当前代码一致的冻结记录")
            subparser.add_argument("--stage", choices=STAGES, default="development", help="development 开发；validation 验证；holdout 最终检验")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            metadata_path = args.output.with_suffix(args.output.suffix + ".json")
            if args.output.exists() or metadata_path.exists():
                raise ValueError("Output already exists; choose a new path")
            write_bars(demo_bars(), args.output)
            metadata_path.write_text(json.dumps({"source": "synthetic", "seed": 42,
                                                "price_basis": "as_traded", "actions": "explicit_no_events"}) + "\n")
            print(f"已保存 400 根合成日线（仅用于验证软件）：{args.output}")
        elif args.command == "backtest":
            sidecar = args.csv.with_suffix(args.csv.suffix + ".json")
            metadata = json.loads(sidecar.read_text()) if sidecar.exists() else {"source": "user_csv"}
            if metadata.get("price_basis") != "as_traded" and args.price_basis != "as-traded":
                raise ValueError("Declare as-traded OHLC and explicit actions; adjusted prices cannot be assumed raw")
            bars = validate_actions(pd.read_csv(args.csv))
            result = run_backtest(bars, Config(
                fast=args.fast, slow=args.slow, allocation=args.allocation, initial_cash=args.cash,
                commission_per_share=args.commission_per_share, minimum_commission=args.minimum_commission,
                slippage_bps=args.slippage_bps))
            result.summary.update({"input_csv": str(args.csv.resolve()), "input_sha256": sha256(args.csv),
                                   "data_source": metadata, "evaluation": "single CSV exploratory run; not held-out research"})
            save_result(result, args.out)
            print(format_summary(result.summary, args.out))
        elif args.command == "fetch":
            protocol = read_protocol(args.config)
            manifest = fetch_snapshot(protocol["universe"], protocol["history_start"],
                                      protocol["history_end_exclusive"], args.out)
            print(f"历史数据下载及校验完成：{len(manifest['symbols'])} 只股票；目录：{args.out}")
        elif args.command == "import-csv":
            manifest = import_snapshot(args.config, args.input_dir, args.out, args.source_label)
            print(f"历史 CSV 导入及校验完成：{len(manifest['symbols'])} 只股票；目录：{args.out}")
        elif args.command == "freeze":
            record = freeze(args.config, args.data, args.out)
            print(f"实验冻结记录已保存：{args.out}\n代码校验值：{record['code_sha256']}\n未进行参数搜索。")
        elif args.command == "study":
            if args.out.exists() and any(args.out.iterdir()):
                raise ValueError("Report path already contains files")
            result = run_stage(args.config, args.data, args.freeze, args.stage)
            save_result(result, args.out)
            print(format_summary(result.summary, args.out))
        return 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
        print(f"运行失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
