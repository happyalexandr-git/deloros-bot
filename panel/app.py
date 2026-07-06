"""Админ-панель бота «Делорос» (FastAPI + Jinja2).

Вход — для участников с галочкой «админ» (телефон + пароль, см. tools/admins).
Вкладки: Обзор, Реестр (CRUD + назначение админов), Участник (профиль/расходы/
документы/активность), Документы, О боте. Доступ только из корп-сети.
Запуск: uvicorn panel.app:app --host 0.0.0.0 --port 8087
"""
import os
import secrets
import sys
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.roster import (
    load_roster, add_member, delete_member, rename_member, update_member,
    find_member_by_phone, normalize_phone,
)
from tools.access import verified_phones
from tools import admins, access
from tools.kb_search import KB_PATH
from panel import data

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

app = FastAPI(title="Деловая Россия · Иркутская область — панель")
app.add_middleware(
    SessionMiddleware, secret_key=os.environ.get("PANEL_SECRET_KEY", secrets.token_hex(32))
)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def _authed(request: Request) -> bool:
    return bool(request.session.get("auth"))


def _members_count() -> int:
    folder = KB_PATH / "members"
    return len(list(folder.glob("*.md"))) if folder.exists() else 0


def _member_by_token(token: str) -> dict | None:
    phone = normalize_phone(token)
    for m in load_roster():
        if m["phone"] == phone:
            return m
    return None


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return RedirectResponse("/overview" if _authed(request) else "/login")


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str = ""):
    if _authed(request):
        return RedirectResponse("/overview")
    return templates.TemplateResponse(request, "login.html", {"error": error})


@app.post("/login")
def login(request: Request, phone: str = Form(""), password: str = Form("")):
    if admins.verify(phone, password):
        request.session["auth"] = True
        m = find_member_by_phone(phone)
        request.session["name"] = (m or {}).get("name", "Админ")
        request.session["phone"] = normalize_phone(phone)
        return RedirectResponse("/overview", status_code=303)
    return RedirectResponse("/login?error=1", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


def _ctx(request, **kw):
    kw["admin_name"] = request.session.get("name", "Админ")
    return kw


@app.get("/overview", response_class=HTMLResponse)
def overview(request: Request):
    if not _authed(request):
        return RedirectResponse("/login")
    roster = load_roster()
    verified = verified_phones()
    confirmed = sum(1 for m in roster if m["phone"] in verified)
    return templates.TemplateResponse(request, "overview.html", _ctx(
        request, tab="overview", total=len(roster), confirmed=confirmed,
        profiles=_members_count(), docs=len(data.documents_all()),
    ))


@app.get("/roster", response_class=HTMLResponse)
def roster_page(request: Request, error: str = "", ok: str = ""):
    if not _authed(request):
        return RedirectResponse("/login")
    roster = load_roster()
    verified = verified_phones()
    for m in roster:
        m["confirmed"] = m["phone"] in verified
        m["is_admin"] = admins.is_admin(m["phone"])
        m["token"] = m["phone"].lstrip("+")
    return templates.TemplateResponse(request, "roster.html", _ctx(
        request, tab="roster", roster=roster, error=error, ok=ok,
    ))


@app.post("/roster/add")
def roster_add(request: Request, name: str = Form(""), phone: str = Form(""),
               birth: str = Form(""), company: str = Form(""),
               position: str = Form(""), industry: str = Form("")):
    if not _authed(request):
        return RedirectResponse("/login")
    name, phone = name.strip(), phone.strip()
    birth, company = birth.strip(), company.strip()
    position, industry = position.strip(), industry.strip()
    if not name or not phone:
        return RedirectResponse("/roster?error=Укажите имя и телефон", status_code=303)
    if add_member(name, phone, birth, company, position, industry):
        return RedirectResponse("/roster?ok=Добавлен: " + name, status_code=303)
    return RedirectResponse("/roster?error=Такой телефон уже в реестре", status_code=303)


@app.post("/roster/edit")
def roster_edit(request: Request, old_phone: str = Form(""), name: str = Form(""),
                phone: str = Form(""), birth: str = Form(""), company: str = Form(""),
                position: str = Form(""), industry: str = Form("")):
    if not _authed(request):
        return RedirectResponse("/login")
    name, phone = name.strip(), phone.strip()
    if not name or not phone:
        return RedirectResponse("/roster?error=ФИО и телефон обязательны", status_code=303)
    res = update_member(old_phone, name, phone, birth, company, position, industry)
    if res == "ok":
        # если телефон сменился — переносим админ-права и подтверждение на новый
        old_n, new_n = normalize_phone(old_phone), normalize_phone(phone)
        if old_n != new_n:
            admins.migrate_phone(old_n, new_n)
            access.migrate_phone(old_n, new_n)
        return RedirectResponse("/roster?ok=Обновлено: " + name, status_code=303)
    if res == "dup":
        return RedirectResponse("/roster?error=Такой телефон уже у другого участника", status_code=303)
    if res == "badphone":
        return RedirectResponse("/roster?error=Телефон не распознан", status_code=303)
    return RedirectResponse("/roster?error=Участник не найден", status_code=303)


@app.post("/roster/delete")
def roster_delete(request: Request, phone: str = Form("")):
    if not _authed(request):
        return RedirectResponse("/login")
    delete_member(phone)
    admins.unset_admin(phone)
    return RedirectResponse("/roster?ok=Удалено", status_code=303)


@app.post("/roster/admin")
def roster_admin(request: Request, phone: str = Form(""), make_admin: str = Form(""), password: str = Form("")):
    if not _authed(request):
        return RedirectResponse("/login")
    if make_admin:
        if len(password) < 6:
            return RedirectResponse("/roster?error=Пароль админа — минимум 6 символов", status_code=303)
        admins.set_admin(phone, password)
        return RedirectResponse("/roster?ok=Назначен админом", status_code=303)
    admins.unset_admin(phone)
    return RedirectResponse("/roster?ok=Права админа сняты", status_code=303)


@app.get("/member/{token}", response_class=HTMLResponse)
def member_page(request: Request, token: str):
    if not _authed(request):
        return RedirectResponse("/login")
    m = _member_by_token(token)
    if not m:
        return RedirectResponse("/roster?error=Участник не найден", status_code=303)
    idents = data.identifiers(m)
    return templates.TemplateResponse(request, "member.html", _ctx(
        request, tab="roster", m=m,
        profile=data.profile(m), usage=data.usage_for(idents),
        docs=data.documents_for(idents), activity=data.activity_for(idents),
        confirmed=m["phone"] in verified_phones(),
    ))


@app.get("/documents", response_class=HTMLResponse)
def documents_page(request: Request):
    if not _authed(request):
        return RedirectResponse("/login")
    return templates.TemplateResponse(request, "documents.html", _ctx(
        request, tab="documents", docs=data.documents_all(),
    ))


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    if not _authed(request):
        return RedirectResponse("/login")
    return templates.TemplateResponse(request, "about.html", _ctx(request, tab="about"))
