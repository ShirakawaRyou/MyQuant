"""Authenticated read-only dashboard. Never imports or starts the broker worker."""

import argparse
import csv
from io import StringIO
from pathlib import Path
import secrets
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import Auth
from .localization import COLUMNS_ZH, display_value
from .settings import Settings
from .store import connect, public_state

STATIC = Path(__file__).parent / "static"
TEMPLATES = Path(__file__).parent / "templates"


def create_app(settings=None):
    settings = settings or Settings.from_env()
    auth = Auth(settings.auth_db)
    secure_cookie = not settings.loopback_http
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(settings.base_url).hostname, "localhost", "127.0.0.1"])

    def session(request):
        value = auth.session(request.cookies.get("mq_session"))
        if not value:
            raise HTTPException(401, "请登录后查看模拟账户")
        return value

    def same_origin(request):
        if request.headers.get("origin") not in (None, settings.base_url):
            raise HTTPException(403, "请求来源无效")

    @app.middleware("http")
    async def security(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        return response

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        if auth.session(request.cookies.get("mq_session")):
            return RedirectResponse("/", status_code=303)
        csrf = secrets.token_urlsafe(32)
        response = HTMLResponse((TEMPLATES / "login.html").read_text(encoding="utf-8").replace("__CSRF__", csrf))
        response.set_cookie("mq_login_csrf", csrf, secure=secure_cookie, httponly=True, samesite="strict", max_age=600, path="/login")
        return response

    @app.post("/login")
    async def login(request: Request):
        same_origin(request)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8192:
                raise HTTPException(413, "请求过大")
        try:
            values = parse_qs(body.decode("utf-8"))
        except UnicodeDecodeError:
            raise HTTPException(400, "登录表单编码无效")
        def field(name):
            return values.get(name, [""])[0]
        if not field("csrf") or not secrets.compare_digest(field("csrf"), request.cookies.get("mq_login_csrf", "")):
            raise HTTPException(403, "登录页面已过期，请刷新后重试")
        username, password = field("username"), field("password")
        if len(username) > 64 or len(password) > 4096:
            raise HTTPException(400, "用户名或密码无效")
        token, limited = auth.login(username, password, request.client.host)
        if limited:
            return HTMLResponse("登录尝试过多，请五分钟后重试。", status_code=429, headers={"Retry-After": "300"})
        if not token:
            return RedirectResponse("/login?error=1", status_code=303)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("mq_session", token, secure=secure_cookie, httponly=True, samesite="strict", max_age=8 * 3600)
        response.delete_cookie("mq_login_csrf", path="/login", secure=secure_cookie, httponly=True, samesite="strict")
        return response

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        if not auth.session(request.cookies.get("mq_session")):
            return RedirectResponse("/login", status_code=303)
        return HTMLResponse((TEMPLATES / "index.html").read_text(encoding="utf-8"))

    @app.get("/api/me")
    def me(request: Request):
        user = session(request)
        return {"username": user["username"], "csrf": user["csrf"]}

    @app.post("/logout")
    def logout(request: Request):
        user = session(request)
        same_origin(request)
        if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), user["csrf"]):
            raise HTTPException(403, "请求无效")
        auth.logout(request.cookies["mq_session"])
        response = JSONResponse({"logged_out": True})
        response.delete_cookie("mq_session", secure=secure_cookie, httponly=True, samesite="strict")
        return response

    @app.get("/api/state")
    def state(request: Request):
        session(request)
        try:
            return public_state(settings.trade_db)
        except OSError:
            raise HTTPException(503, "持久账本暂不可读，后台状态未改变")

    @app.get("/api/export/{table}.csv")
    def export(table: str, request: Request, language: str = "zh"):
        session(request)
        if language not in {"zh", "en"}:
            raise HTTPException(400, "导出语言只支持 zh（中文）或 en（原始字段）")
        if table not in {"signals", "orders", "fills", "equity"}:
            raise HTTPException(404)
        if not settings.trade_db.exists():
            raise HTTPException(404, "尚无账户记录")

        def rows():
            db = connect(settings.trade_db, readonly=True)
            try:
                query = ("SELECT f.*,o.reason,o.signal_id FROM fills f LEFT JOIN orders o ON o.id=f.order_id"
                         if table == "fills" else f"SELECT * FROM {table}")
                cursor = db.execute(query)
                buffer = StringIO()
                writer = csv.writer(buffer)
                columns = [column[0] for column in cursor.description]
                if language == "zh":
                    yield "\ufeff"
                writer.writerow([COLUMNS_ZH.get(column, column) if language == "zh" else column for column in columns])
                yield buffer.getvalue()
                for row in cursor:
                    buffer.seek(0)
                    buffer.truncate(0)
                    # Prevent spreadsheet formula execution in exported reason text.
                    values = [display_value(column, value) if language == "zh" else value for column, value in zip(columns, row)]
                    writer.writerow(["'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value for value in values])
                    yield buffer.getvalue()
            finally:
                db.close()
        return StreamingResponse(rows(), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="paper-{table}.csv"'})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def main(argv=None):
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if settings.loopback_http and args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("本地 HTTP 模式只允许绑定本机回环地址")
    uvicorn.run(create_app(settings), host=args.host, port=args.port,
                proxy_headers=not settings.loopback_http, forwarded_allow_ips="127.0.0.1")
