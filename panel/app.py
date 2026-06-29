"""Админ-панель бота «Делорос» (FastAPI + Jinja2).

Управление реестром членов клуба, обзор, описание бота. Один админ
(логин+пароль из .env), сессия-кука. Доступ — только из корп-сети.
Запуск: uvicorn panel.app:app --host 0.0.0.0 --port 8080
"""
import hmac
import os
import secrets
import sys
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

# доступ к общим модулям проекта (tools/)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.roster import load_roster, add_member, delete_member
from tools.access import verified_phones
from tools.kb_search import KB_PATH

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

app = FastAPI(title="Делорос — админ-панель")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("PANEL_SECRET_KEY", secrets.token_hex(32)),
)


def _authed(request: Request) -> bool:
    return bool(request.session.get("auth"))


def _members_count() -> int:
    folder = KB_PATH / "members"
    return len(list(folder.glob("*.md"))) if folder.exists() else 0


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return RedirectResponse("/overview" if _authed(request) else "/login")


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str = ""):
    if _authed(request):
        return RedirectResponse("/overview")
    return templates.TemplateResponse(request, "login.html", {"error": error})


@app.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form("")):
    ok = (
        ADMIN_PASSWORD
        and hmac.compare_digest(username, ADMIN_USER)
        and hmac.compare_digest(password, ADMIN_PASSWORD)
    )
    if not ok:
        return RedirectResponse("/login?error=1", status_code=303)
    request.session["auth"] = True
    return RedirectResponse("/overview", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/overview", response_class=HTMLResponse)
def overview(request: Request):
    if not _authed(request):
        return RedirectResponse("/login")
    roster = load_roster()
    verified = verified_phones()
    confirmed = sum(1 for m in roster if m["phone"] in verified)
    return templates.TemplateResponse(request, "overview.html", {
        "tab": "overview",
        "total": len(roster), "confirmed": confirmed, "profiles": _members_count(),
        "recent": list(reversed(roster))[:5],
    })


@app.get("/roster", response_class=HTMLResponse)
def roster_page(request: Request, error: str = "", ok: str = ""):
    if not _authed(request):
        return RedirectResponse("/login")
    roster = load_roster()
    verified = verified_phones()
    for m in roster:
        m["confirmed"] = m["phone"] in verified
    return templates.TemplateResponse(request, "roster.html", {
        "tab": "roster", "roster": roster, "error": error, "ok": ok,
    })


@app.post("/roster/add")
def roster_add(request: Request, name: str = Form(""), phone: str = Form("")):
    if not _authed(request):
        return RedirectResponse("/login")
    name, phone = name.strip(), phone.strip()
    if not name or not phone:
        return RedirectResponse("/roster?error=Укажите имя и телефон", status_code=303)
    if add_member(name, phone):
        return RedirectResponse("/roster?ok=Добавлен: " + name, status_code=303)
    return RedirectResponse("/roster?error=Такой телефон уже в реестре", status_code=303)


@app.post("/roster/delete")
def roster_delete(request: Request, phone: str = Form("")):
    if not _authed(request):
        return RedirectResponse("/login")
    delete_member(phone)
    return RedirectResponse("/roster?ok=Удалено", status_code=303)


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    if not _authed(request):
        return RedirectResponse("/login")
    return templates.TemplateResponse(request, "about.html", {"tab": "about"})
