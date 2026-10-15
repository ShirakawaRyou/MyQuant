"""本地登录边界及真实独立进程测试；不冒充 Windows 或券商联调。"""

from dataclasses import replace
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

from fastapi.testclient import TestClient
from filelock import FileLock
import psutil
import pytest

from myquant_dashboard import local
from myquant_dashboard.auth import Auth
from myquant_dashboard.settings import Settings
from myquant_dashboard.web import create_app
from conftest import PASSWORD, login


@pytest.mark.parametrize("url", ["http://example.com", "http://localhost.evil.test", "http://192.168.1.2"])
def test_local_flag_cannot_enable_public_http(monkeypatch, url):
    monkeypatch.setenv("DASHBOARD_LOCAL_DEV", "1")
    monkeypatch.setenv("DASHBOARD_BASE_URL", url)
    with pytest.raises(ValueError, match="HTTPS"):
        Settings.from_env()


def test_local_http_login_works_without_weakening_public_cookies(settings):
    value = replace(settings, base_url="http://localhost:8090", local_dev=True)
    Auth(value.auth_db).set_password("owner", PASSWORD)
    with TestClient(create_app(value), base_url=value.base_url) as client:
        response = login(client)
        # The existing helper sends its HTTPS fixture Origin; reject that mismatch.
        assert response.status_code == 403
        import re
        token = re.search(r'name="csrf" value="([^"]+)"', client.get("/login").text)[1]
        response = client.post("/login", data={"csrf": token, "username": "owner", "password": PASSWORD},
                               headers={"Origin": value.base_url}, follow_redirects=False)
        assert response.status_code == 303
        assert "Secure" not in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=strict" in response.headers["set-cookie"]
        assert client.get("/api/state").status_code == 200


def test_duplicate_worker_cannot_pass_cross_process_lock(settings, monkeypatch):
    monkeypatch.setenv("TRADE_DB", str(settings.trade_db))
    settings.trade_db.parent.mkdir(parents=True)
    with FileLock(settings.trade_db.parent / "worker.lock"):
        result = subprocess.run([sys.executable, "-c", "from myquant_dashboard.worker import main; main(['--once'])"],
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode != 0 and "拒绝重复启动" in result.stderr


@pytest.fixture
def local_root(tmp_path, monkeypatch):
    root = tmp_path / "本地 交易记录"
    monkeypatch.setenv("MYQUANT_LOCAL_RUNTIME", str(root))
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    assert local.main(["configure", "--dashboard-port", str(port)]) == 0
    yield root
    local.stop(root, "all")


def test_local_settings_override_inherited_trading_configuration(local_root, monkeypatch):
    monkeypatch.setenv("PAPER_ORDERS_ENABLED", "true")
    monkeypatch.setenv("IBKR_HOST", "remote.example.com")
    value = local.environment(local_root, local.config(local_root))
    assert value["PAPER_ORDERS_ENABLED"] == "false" and value["IBKR_HOST"] == "127.0.0.1"
    assert value["MYQUANT_RUNTIME"] == str(local_root)
    assert value["PYTHONUTF8"] == "1"
    assert local.main(["configure", "--account", "U123"]) == 1
    assert not local.config(local_root)["orders_enabled"]


def test_pid_reuse_never_terminates_unrelated_process(local_root):
    me = psutil.Process()
    local.write_json(local_root / "processes.json", {"web": {"pid": me.pid, "created": me.create_time(), "instance": "wrong"}})
    try:
        with pytest.raises(ValueError, match="身份"):
            local.stop(local_root, "web")
        assert me.is_running()
    finally:
        (local_root / "processes.json").unlink()


def test_actual_local_services_duplicate_start_web_stop_and_restart(local_root):
    Auth(local_root / "auth/auth.sqlite3").set_password("owner", PASSWORD)
    assert local.main(["start"]) == 0
    initial = local.records(local_root)
    assert local.main(["start"]) == 0
    assert local.records(local_root) == initial
    for _ in range(60):
        if local.status(local_root)["heartbeat_at"]:
            break
        time.sleep(.1)
    assert local.status(local_root)["heartbeat_at"]
    assert local.status(local_root)["has_account"] is False
    assert local.main(["configure"]) == 1
    assert local.main(["stop", "--service", "web"]) == 0
    value = local.status(local_root)
    assert value["processes"] == {"worker": True, "web": False}
    assert local.records(local_root)["worker"] == initial["worker"]
    assert local.main(["start", "--service", "web"]) == 0
    assert local.status(local_root)["processes"] == {"worker": True, "web": True}
    assert (local_root / "trading/paper.sqlite3").exists()
