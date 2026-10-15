"""Run in the cloud server terminal, never in a browser page or with secrets in argv."""

import getpass
import os
from pathlib import Path
import re


def main():
    root = Path(__file__).resolve().parent
    env = root / ".env"
    secret = root / "secrets/ibkr_password"
    if env.exists() or secret.exists():
        raise SystemExit("配置文件已存在，拒绝覆盖；请在服务器上安全编辑已有配置。")
    domain = input("看板域名（不含https://）: ").strip().lower()
    username = input("IBKR模拟登录用户名（仅保存在服务器）: ").strip()
    account = input("模拟账户DU编号（可留空，连接后自动核对单一DU账户）: ").strip()
    if not re.fullmatch(r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", domain):
        raise SystemExit("请输入有效公网域名。")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username) or (account and not re.fullmatch(r"DU\d+", account)):
        raise SystemExit("用户名格式或DU模拟账户格式无效。")
    password = getpass.getpass("IBKR模拟登录密码（不回显，不写日志）: ")
    if not password or password != getpass.getpass("再次输入模拟登录密码: "):
        raise SystemExit("密码为空或两次输入不一致。")
    secret.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    secret.write_text(password + "\n")
    secret.chmod(0o600)
    if os.geteuid() == 0:
        # The pinned gateway image runs as uid/gid 1000, per its Dockerfile.
        os.chown(secret, 1000, 1000)
    elif os.geteuid() != 1000:
        secret.unlink()
        raise SystemExit("此网关镜像使用UID1000；请使用sudo运行本配置程序以设置正确文件归属。")
    template = (root / ".env.example").read_text()
    template = template.replace("DASHBOARD_DOMAIN=\n", f"DASHBOARD_DOMAIN={domain}\n")
    template = template.replace("IBKR_USERNAME=\n", f"IBKR_USERNAME={username}\n")
    template = template.replace("IBKR_PAPER_ACCOUNT=\n", f"IBKR_PAPER_ACCOUNT={account}\n")
    env.write_text(template)
    env.chmod(0o600)
    print("服务器配置已保存。密码仅在Gateway专用文件中；初始为只读监控。")


if __name__ == "__main__":
    main()
