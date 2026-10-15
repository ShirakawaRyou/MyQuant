"""本机模拟交易入口：凭据只在官方 TWS/Gateway 登录，后台与网页独立运行。"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser

from filelock import FileLock
import psutil

from .store import public_state

PROJECT = Path(__file__).resolve().parents[4]
MODULE = "myquant_dashboard.local"
ROLES = ("worker", "web")


def runtime_path():
    default = (Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "MyQuant"
               if os.name == "nt" else Path.home() / ".local/state/MyQuant")
    return Path(os.environ.get("MYQUANT_LOCAL_RUNTIME", str(default))).resolve()


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def config(root):
    path = root / "local.json"
    if not path.exists():
        raise ValueError("尚未配置，请先运行 Setup-Windows.cmd")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (value.get("schema") != 1 or value.get("api_port") not in {7497, 4002}
            or type(value.get("dashboard_port")) is not int
            or not 1024 <= value["dashboard_port"] <= 65535
            or value["dashboard_port"] == value["api_port"]
            or type(value.get("orders_enabled")) is not bool
            or not re.fullmatch(r"(?:DU\d+)?", value.get("account", ""))):
        raise ValueError("本机配置无效；仅支持模拟端口 7497/4002、DU 账户和本机看板")
    return value


def records(root):
    path = root / "processes.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def own_process(item, role):
    if not item:
        return None
    try:
        process = psutil.Process(item["pid"])
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return None
        if (abs(process.create_time() - item["created"]) > .01
                or process.cmdline()[-3:] != ["_run", role, item["instance"]]
                or MODULE not in process.cmdline()):
            raise ValueError("进程编号已被复用或身份不符；不会停止或覆盖未知进程，请先人工核对")
        return process
    except psutil.NoSuchProcess:
        return None
    except psutil.AccessDenied:
        raise ValueError("无法核对进程身份；不会停止未知进程")


def environment(root, value):
    # Overrides inherited broker/trading settings; opening the web never enables orders.
    return {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
            "MYQUANT_RUNTIME": str(root), "TRADE_DB": str(root / "trading/paper.sqlite3"),
            "AUTH_DB": str(root / "auth/auth.sqlite3"), "RESEARCH_PROTOCOL": str(PROJECT / "research/protocol.json"),
            "DASHBOARD_BASE_URL": f"http://localhost:{value['dashboard_port']}", "DASHBOARD_LOCAL_DEV": "1",
            "IBKR_HOST": "127.0.0.1", "IBKR_PORT": str(value["api_port"]), "IBKR_CLIENT_ID": "71",
            "IBKR_PAPER_ACCOUNT": value["account"], "PAPER_ORDERS_ENABLED": str(value["orders_enabled"]).lower()}


def status(root):
    value = config(root)
    saved = records(root)
    state = public_state(root / "trading/paper.sqlite3")
    processes = {role: own_process(saved.get(role), role) is not None for role in ROLES}
    heartbeat = state["worker"].get("heartbeat_at")
    fresh = heartbeat and 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat)).total_seconds() < 180
    return {"processes": processes,
            "connected": bool(processes["worker"] and fresh and state["worker"].get("connected", False)),
            "heartbeat_at": state["worker"].get("heartbeat_at"),
            "message": state["worker"].get("message"), "has_account": state["account"] is not None,
            "orders_enabled": value["orders_enabled"], "runtime": str(root)}


def show_status(root):
    value = status(root)
    print(f"策略后台：{'运行中' if value['processes']['worker'] else '已停止'}；"
          f"看板：{'运行中' if value['processes']['web'] else '已停止'}")
    print(f"IBKR 模拟账户：{'已连接' if value['connected'] else '未连接'}；"
          f"账户快照：{'已获取' if value['has_account'] else '尚无数据'}")
    print(f"执行模式：{'允许模拟下单' if value['orders_enabled'] else '仅监控，不自动下单'}")
    print(f"后台心跳：{value['heartbeat_at'] or '等待后台初始化'}；{value['message'] or ''}")
    print(f"本机记录与日志：{root}")


def healthy(value):
    try:
        # Do not send loopback health checks through a user's system proxy.
        with build_opener(ProxyHandler({})).open(f"http://127.0.0.1:{value['dashboard_port']}/healthz", timeout=1) as response:
            return response.status == 200
    except (URLError, OSError):
        return False


def stop(root, selected):
    saved = records(root)
    matched = [(role, own_process(saved.get(role), role)) for role in ROLES if selected in {"all", role}]
    for role, process in matched:
        if process:
            process.terminate()
            try:
                process.wait(timeout=15)
            except psutil.TimeoutExpired:
                raise ValueError("进程未按时退出，未强制结束；请核对任务管理器和本机日志")
        saved.pop(role, None)
    write_json(root / "processes.json", saved)


def start(root, value, selected):
    saved = records(root)
    active = {role: own_process(saved.get(role), role) for role in ROLES}
    if selected in {"all", "web"} and not active["web"]:
        auth = root / "auth/auth.sqlite3"
        if not auth.exists():
            raise ValueError("请先运行安装脚本设置看板密码")
        with sqlite3.connect(f"{auth.as_uri()}?mode=ro", uri=True) as db:
            if not db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                raise ValueError("请先设置看板登录用户")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", value["dashboard_port"]))
    launched = []
    try:
        for role in ROLES:
            if selected not in {"all", role} or active[role]:
                continue
            token = secrets.token_hex(16)
            command = [sys.executable, "-m", MODULE, "_run", role, token]
            options = ({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
                       if os.name == "nt" else {"start_new_session": True})
            with (root / f"{role}.log").open("ab") as log:
                process = subprocess.Popen(command, cwd=PROJECT, env=environment(root, value),
                                           stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
            saved[role] = {"pid": process.pid, "created": psutil.Process(process.pid).create_time(), "instance": token}
            launched.append(role)
            write_json(root / "processes.json", saved)
        if selected in {"all", "web"}:
            for _ in range(100):
                if healthy(value):
                    break
                if own_process(saved.get("web"), "web") is None:
                    raise ValueError(f"看板启动失败，请查看 {root / 'web.log'}")
                time.sleep(.1)
            else:
                raise ValueError("看板未就绪，请检查本机日志")
    except Exception:
        for role in launched:
            stop(root, role)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("configure", help="配置本机模拟账户连接，不保存 IBKR 密码")
    setup.add_argument("--api-port", type=int, choices=[7497, 4002], default=7497)
    setup.add_argument("--dashboard-port", type=int, default=8090)
    setup.add_argument("--account", default="")
    setup.add_argument("--paper-orders", choices=["disabled", "enabled"], default="disabled")
    commands.add_parser("password", help="设置独立看板密码，不是 IBKR 密码")
    for name in ("start", "stop"):
        sub = commands.add_parser(name)
        sub.add_argument("--service", choices=["all", "web", "worker"], default="all")
        if name == "start":
            sub.add_argument("--open", action="store_true", help="在本机浏览器打开看板")
    commands.add_parser("open", help="在本机浏览器打开看板")
    inspect = commands.add_parser("status", help="查看进程及连接状态")
    inspect.add_argument("--json", action="store_true")
    backtest = commands.add_parser("backtest", help="使用随包缓存运行中文历史回测，不需要 IBKR")
    backtest.add_argument("--stage", choices=["development", "validation", "holdout"], default="holdout")
    internal = commands.add_parser("_run", help=argparse.SUPPRESS)
    internal.add_argument("role", choices=ROLES)
    internal.add_argument("instance")
    args = parser.parse_args(argv)
    if args.command == "_run":
        if args.role == "worker":
            from .worker import main as run
            run([])
        else:
            from .web import main as run
            from .settings import Settings
            from urllib.parse import urlsplit
            run(["--host", "127.0.0.1", "--port", str(urlsplit(Settings.from_env().base_url).port)])
        return 0
    root = runtime_path()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with FileLock(root / "launcher.lock", timeout=0):
            if args.command == "configure":
                if any(own_process(records(root).get(role), role) for role in ROLES):
                    raise ValueError("修改配置前请先停止本机后台和看板")
                value = {"schema": 1, "api_port": args.api_port, "dashboard_port": args.dashboard_port,
                         "account": args.account, "orders_enabled": args.paper_orders == "enabled"}
                if (not re.fullmatch(r"(?:DU\d+)?", args.account) or not 1024 <= args.dashboard_port <= 65535
                        or args.dashboard_port == args.api_port):
                    raise ValueError("账户必须为 DU 模拟账户，且看板端口必须有效并与 API 端口不同")
                write_json(root / "local.json", value)
                print("本机配置已保存；" + ("允许模拟下单，仍需 TWS/Gateway 开放写入权限。" if value["orders_enabled"] else "默认仅监控，不自动下单。"))
                return 0
            value = config(root)
            if args.command == "password":
                return subprocess.call([sys.executable, "-c", "from myquant_dashboard.admin import main; main(['set-password'])"],
                                       cwd=PROJECT, env=environment(root, value))
            if args.command == "start":
                start(root, value, args.service)
                show_status(root)
            elif args.command == "stop":
                stop(root, args.service)
                print("指定本机服务已停止；已提交到 IBKR 的订单不会因此自动撤销。")
            elif args.command == "status":
                print(json.dumps(status(root), ensure_ascii=False)) if args.json else show_status(root)
            elif args.command == "backtest":
                out = root / "reports" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + secrets.token_hex(3))
                return subprocess.call([sys.executable, "-m", "myquant.cli", "study", "--config", str(PROJECT / "research/protocol.json"),
                    "--data", str(PROJECT / "data/research-20261015"), "--freeze", str(PROJECT / "research/frozen-20261015-portable.json"),
                    "--stage", args.stage, "--out", str(out)], cwd=PROJECT, env=environment(root, value))
            if args.command == "open" or (args.command == "start" and args.open):
                if not own_process(records(root).get("web"), "web") or not healthy(value):
                    raise ValueError("本机看板尚未启动")
                webbrowser.open(f"http://localhost:{value['dashboard_port']}")
        return 0
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        print(f"本机操作失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
