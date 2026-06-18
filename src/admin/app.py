"""管理ポータルの FastAPI アプリ。uvicorn src.admin.app:app で起動する。

画面（読み取り中心）:
  - サーバー一覧（在籍/許可ch数/msg数/chunk数/今月のコスト）
  - 取り込みジョブ状況（処理中・完了・エラー）
  - 利用量サマリ（今月の合計・種別別・サーバー別）
認証は ADMIN_PASSWORD による簡易パスワード（src/admin/auth.py）。
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

load_dotenv()

from src import db, quota
from src.admin import auth

COOKIE_NAME = "admin_session"
_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _is_authed(request: Request) -> bool:
    return auth.verify_token(request.cookies.get(COOKIE_NAME))


def create_app() -> FastAPI:
    app = FastAPI(title="remember admin")

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        if _is_authed(request):
            return RedirectResponse("/", status_code=303)
        return _TEMPLATES.TemplateResponse(
            request, "login.html", {"error": None}
        )

    @app.post("/login", response_class=HTMLResponse)
    def login_submit(request: Request, password: str = Form("")):
        if not auth.password_ok(password):
            return _TEMPLATES.TemplateResponse(
                request, "login.html",
                {"error": "パスワードが違います"},
                status_code=401,
            )
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(
            COOKIE_NAME, auth.make_token(),
            httponly=True, samesite="lax", max_age=86400,
        )
        return resp

    @app.get("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(COOKIE_NAME)
        return resp

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        if not _is_authed(request):
            return RedirectResponse("/login", status_code=303)
        try:
            conn = db.get_connection(init=True)
        except Exception as e:
            return _TEMPLATES.TemplateResponse(
                request, "error.html", {"message": str(e)},
                status_code=503,
            )
        try:
            ctx = {
                "guilds": db.fetch_guilds_overview(conn),
                "jobs": db.fetch_recent_jobs(conn, limit=50),
                "summary": db.fetch_usage_summary(conn),
            }
        finally:
            conn.close()
        return _TEMPLATES.TemplateResponse(request, "dashboard.html", ctx)

    # ---- 課金（プラン管理・OI-14 C-2）----

    @app.get("/billing", response_class=HTMLResponse)
    def billing(request: Request):
        if not _is_authed(request):
            return RedirectResponse("/login", status_code=303)
        try:
            conn = db.get_connection(init=True)
        except Exception as e:
            return _TEMPLATES.TemplateResponse(
                request, "error.html", {"message": str(e)}, status_code=503
            )
        try:
            ctx = {
                "plans": db.fetch_plan_defs(conn),
                "guilds": db.fetch_billing_overview(conn, quota.jst_day_start_utc_iso()),
            }
        finally:
            conn.close()
        return _TEMPLATES.TemplateResponse(request, "billing.html", ctx)

    @app.post("/billing/plan")
    def update_plan(
        request: Request,
        plan_key: str = Form(...),
        display_name: str = Form(...),
        channel_limit: str = Form(""),   # 空文字 = 無制限(NULL)
        daily_question_limit: int = Form(...),
        price_jpy: int = Form(...),
    ):
        if not _is_authed(request):
            return RedirectResponse("/login", status_code=303)
        ch = int(channel_limit) if channel_limit.strip() else None
        conn = db.get_connection(init=True)
        try:
            db.update_plan_def(
                conn, plan_key, display_name, ch, daily_question_limit, price_jpy
            )
        finally:
            conn.close()
        return RedirectResponse("/billing", status_code=303)

    @app.post("/billing/guild")
    def set_guild_plan(
        request: Request,
        guild_id: str = Form(...),
        plan_key: str = Form(...),
        note: str = Form(""),
    ):
        if not _is_authed(request):
            return RedirectResponse("/login", status_code=303)
        conn = db.get_connection(init=True)
        try:
            db.set_guild_plan(conn, guild_id, plan_key, note=note or None)
        finally:
            conn.close()
        return RedirectResponse("/billing", status_code=303)

    return app


app = create_app()
