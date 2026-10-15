import sqlite3

import pytest
from fastapi.testclient import TestClient

from myquant_dashboard.auth import Auth
from myquant_dashboard.store import connect
from myquant_dashboard.web import create_app
from conftest import login, PASSWORD


@pytest.mark.parametrize("path", ["/api/state", "/api/me", "/api/export/orders.csv"])
def test_private_data_requires_login(client, path):
    assert client.get(path).status_code == 401


def test_login_csrf_cookie_security_and_logout(client):
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.post("/login", data={"username": "owner", "password": PASSWORD}).status_code == 403
    response = login(client)
    assert response.status_code == 303
    cookies = response.headers.get_list("set-cookie")
    assert any("mq_session=" in value and "Secure" in value and "HttpOnly" in value and "SameSite=strict" in value for value in cookies)
    assert client.get("/api/state").status_code == 200
    assert client.post("/logout").status_code == 403
    csrf = client.get("/api/me").json()["csrf"]
    assert client.post("/logout", headers={"X-CSRF-Token": csrf, "Origin": "https://evil.invalid"}).status_code == 403
    assert client.post("/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.get("/api/state").status_code == 401


def test_refresh_export_and_navigation_cannot_create_orders_or_fills(client, store, order):
    login(client)
    before = {table: store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ["signals", "orders", "fills"]}
    for _ in range(5):
        assert client.get("/").status_code == 200
        state = client.get("/api/state").json()
        assert state["mode"] == "模拟交易"
        assert state["orders"][0]["status"] == "PLANNED"
        assert state["fills"] == []
    response = client.get("/api/export/orders.csv")
    assert response.status_code == 200 and "20日均线" in response.text
    assert "no-store" in response.headers["cache-control"]
    after = {table: store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in before}
    assert before == after
    assert client.post("/api/orders", json=order).status_code == 404
    assert client.get("/static/index.html").status_code == 404


def test_sessions_survive_web_restart_and_password_reset_revokes_them(client, settings):
    login(client)
    token = client.cookies.get("mq_session")
    with TestClient(create_app(settings), base_url="https://dashboard.test") as second:
        second.cookies.set("mq_session", token)
        assert second.get("/api/me").json()["username"] == "owner"
        Auth(settings.auth_db).set_password("owner", "new-test-password-987!")
        assert second.get("/api/me").status_code == 401


def test_login_rate_limit_persists(client, settings):
    for _ in range(5):
        assert login(client, "incorrect-test-password").status_code == 303
    assert login(client).status_code == 429
    assert Auth(settings.auth_db).login("owner", PASSWORD, "testclient")[1] is True


def test_no_credentials_in_api_and_headers_are_protective(client, monkeypatch):
    monkeypatch.setenv("TWS_PASSWORD", "NEVER_EXPOSE_THIS_TEST_VALUE")
    login(client)
    response = client.get("/api/state")
    assert "NEVER_EXPOSE" not in response.text and "TWS_PASSWORD" not in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json()["account"] is None


def test_readonly_connection_rejects_trading_writes(settings, store):
    db = connect(settings.trade_db, readonly=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM orders")
    finally:
        db.close()
