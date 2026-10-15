"""Server-terminal user administration; never accepts a password in argv."""

import argparse
import getpass
from pathlib import Path
import sqlite3

from .auth import Auth
from .settings import Settings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["set-password", "backup"])
    parser.add_argument("--username", default="owner")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.command == "set-password":
        first = getpass.getpass("新看板密码（至少14字符，不回显）: ")
        second = getpass.getpass("再次输入: ")
        if first != second:
            raise SystemExit("两次密码不一致")
        Auth(settings.auth_db).set_password(args.username, first)
        print("登录用户已保存；旧登录会话已失效。密码未写入日志。")
    else:
        if args.out is None or args.out.exists():
            raise SystemExit("为备份指定一个不存在的 --out 路径")
        args.out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        source = sqlite3.connect(f"{settings.trade_db.resolve().as_uri()}?mode=ro", uri=True)
        target = sqlite3.connect(args.out)
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
        args.out.chmod(0o600)
        print("模拟交易账本一致性备份完成。")
