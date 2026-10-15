"""Actual Chromium verification against a separate HTTP server, with labeled test data."""

from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

import httpx
import pytest
from playwright.sync_api import sync_playwright

from myquant_dashboard.auth import Auth
from myquant_dashboard.store import utcnow
from conftest import PASSWORD


@pytest.mark.skipif(shutil.which("chromium") is None, reason="System Chromium is required for the real-browser check")
def test_actual_login_chart_records_refresh_and_mobile(settings, store, order, tmp_path):
    Auth(settings.auth_db).set_password("owner",PASSWORD)
    now=utcnow()
    store.account_snapshot({"account":"DU123","currency":"USD","net_liq":100000,"cash":100000,
        "unrealized_pnl":0,"realized_pnl":0,"daily_pnl":0,"positions":[],"updated_at":"2024-07-05T13:58:00+00:00","strategy_budget_usd":100000})
    store.account_snapshot({"account":"DU123","currency":"USD","net_liq":100010.25,"cash":99602.25,
        "unrealized_pnl":11,"realized_pnl":0,"daily_pnl":10.25,"updated_at":"2024-07-05T14:02:00+00:00","strategy_budget_usd":100000,
        "positions":[{"symbol":"AAPL","quantity":4,"average_cost":99.25,"market_price":102,
                      "market_value":408,"unrealized_pnl":11,"currency":"USD"}]})
    with store.db:
        store.db.execute("UPDATE orders SET status='PARTIALLY_FILLED',filled=4")
    store.fill({"exec_id":"browser-fixture-exec","order_id":order["id"],"account":"DU123","symbol":"AAPL",
                "action":"BUY","quantity":4,"price":99.25,"executed_at":"2024-07-05T14:01:00+00:00","recorded_at":now})
    store.commission("browser-fixture-exec",.75,"USD")
    store.heartbeat(True,"界面测试样本 · 非真实 IBKR 账户数据",orders_enabled=False,latest_completed_session="2024-07-03")
    sock=socket.socket();sock.bind(("127.0.0.1",0));port=sock.getsockname()[1];sock.close()
    environment={**os.environ,"TRADE_DB":str(settings.trade_db),"AUTH_DB":str(settings.auth_db),
        "DASHBOARD_BASE_URL":f"http://localhost:{port}","DASHBOARD_LOCAL_DEV":"1"}
    output=(tmp_path/"web.log").open("w")
    python=Path(__import__('sys').executable)
    process=subprocess.Popen([str(python),"-c",f"from myquant_dashboard.web import main; main(['--port','{port}'])"],
                             env=environment,stdout=output,stderr=output)
    screenshots=Path(os.environ.get("DASHBOARD_SCREENSHOTS",str(tmp_path/"screenshots")))
    screenshots.mkdir(parents=True,exist_ok=True)
    try:
        for _ in range(50):
            try:
                if httpx.get(f"http://localhost:{port}/healthz").status_code==200:break
            except httpx.ConnectError:time.sleep(.1)
        else:raise AssertionError("HTTP server did not become ready")
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(executable_path=shutil.which("chromium"),headless=True,args=["--no-sandbox"])
            context=browser.new_context(viewport={"width":1440,"height":1100},timezone_id="America/Chicago")
            page=context.new_page();errors=[];page.on("pageerror",lambda error:errors.append(str(error)))
            page.goto(f"http://localhost:{port}")
            page.locator("#username").fill("owner");page.locator("#password").fill(PASSWORD)
            page.get_by_role("button",name="登录看板").click()
            page.wait_for_url(f"http://localhost:{port}/")
            page.locator("#net-liq").filter(has_text="100,010.25").wait_for()
            assert page.get_by_role("heading",name="模拟交易看板").is_visible()
            assert page.locator("#equity-chart polyline").count()==1
            assert page.locator("#equity-chart").is_visible()
            page.locator('[data-curve="daily_pnl"]').click()
            assert "每日重置" in page.locator("#curve-note").text_content()
            assert page.locator("#equity-chart").is_visible()
            page.locator('[data-curve="net_liq"]').click()
            page.get_by_role("tab",name="订单记录").click()
            assert page.locator("#records").get_by_text("部分成交").is_visible()
            page.locator("#records details summary").first.click()
            assert page.locator("#records").get_by_text("20日均线高于60日均线，目标20%").is_visible()
            page.screenshot(path=str(screenshots/"dashboard-test-fixture-desktop.png"),full_page=True)
            page.get_by_role("tab",name="成交记录").click()
            assert page.locator("#records").get_by_text("$ 0.75").is_visible()
            before=store.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            page.reload();page.locator("#net-liq").filter(has_text="100,010.25").wait_for()
            page.locator("#refresh").click();page.wait_for_timeout(300)
            assert store.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]==before
            page.set_viewport_size({"width":390,"height":844})
            page.wait_for_timeout(100)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(screenshots/"dashboard-test-fixture-mobile.png"),full_page=True)
            assert errors==[]
            page.locator("#logout").click();page.wait_for_url("**/login")
            browser.close()
    finally:
        process.terminate();process.wait(timeout=10);output.close()
