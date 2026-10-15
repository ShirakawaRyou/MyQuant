import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from myquant_dashboard.auth import Auth
from myquant_dashboard.settings import Settings
from myquant_dashboard.store import Store
from myquant_dashboard.web import create_app

ROOT = Path(__file__).resolve().parents[3]
PASSWORD = "test-only-Password-941!"


@pytest.fixture
def settings(tmp_path):
    protocol = json.loads((ROOT / "research/protocol.json").read_text())
    protocol["universe"] = ["AAPL"]
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(protocol))
    return Settings(tmp_path / "trading/paper.sqlite3", tmp_path / "auth/auth.sqlite3",
                    base_url="https://dashboard.test", protocol=path)


@pytest.fixture
def store(settings):
    value = Store(settings.trade_db)
    yield value
    value.close()


@pytest.fixture
def client(settings, store):
    Auth(settings.auth_db).set_password("owner", PASSWORD)
    with TestClient(create_app(settings), base_url="https://dashboard.test") as client:
        yield client


def login(client, password=PASSWORD):
    import re
    response = client.get("/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', response.text)[1]
    return client.post("/login", data={"csrf": csrf, "username": "owner", "password": password},
                       headers={"Origin": "https://dashboard.test"}, follow_redirects=False)


@pytest.fixture
def order(store):
    signal = {"id": "signal-1", "account": "DU123", "symbol": "AAPL", "session": "2024-07-03",
              "target": .2, "fast": 110, "slow": 100, "reason": "20日均线高于60日均线，目标20%",
              "created_at": "2024-07-05T14:00:00+00:00", "source": "TEST FIXTURE ONLY"}
    store.signal(signal)
    item = {"id": "MQP-signal-1", "signal_id": signal["id"], "account": "DU123", "symbol": "AAPL",
            "action": "BUY", "quantity": 10, "limit_price": 100, "reason": signal["reason"],
            "created_at": "2024-07-05T14:00:00+00:00"}
    store.plan(item)
    return item
