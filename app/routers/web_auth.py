# app/routers/web_auth.py
from __future__ import annotations
from app.core.datetime_utils import now_br

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.database import get_db
from app.core.session_manager import login_user, logout_user
from app.services.auth_service import (
    authenticate_user,
    get_user_by_login,
    register_login_failure,
    register_login_success,
    register_logout,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _safe_next_url(next_url: str | None) -> str:
    next_url = (next_url or "").strip()

    if not next_url:
        return "/dashboard"

    if not next_url.startswith("/"):
        return "/dashboard"

    if next_url.startswith("//"):
        return "/dashboard"

    return next_url


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    current_user = getattr(request.state, "current_user", None)
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=303)

    next_url = _safe_next_url(request.query_params.get("next", "/dashboard"))

    return templates.TemplateResponse(
        "auth/login.html",
        {
            "request": request,
            "error": None,
            "next_url": next_url,
        },
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    next_url: str = Form("/dashboard"),
    db: Session = Depends(get_db),
):
    login = (login or "").strip()
    password = (password or "").strip()
    next_url = _safe_next_url(next_url)
    client_ip = request.client.host if request.client else None

    print("\n" + "=" * 70)
    print("DEBUG LOGIN")

    raw_user = get_user_by_login(db, login)

    # =========================
    # 🔥 VALIDAÇÕES NOVAS AQUI
    # =========================
    if raw_user:
        # 🚫 BLOQUEIO: USUÁRIO SUSPENSO
        if not raw_user.is_active:
            print("LOGIN BLOQUEADO: usuário suspenso")
            return templates.TemplateResponse(
                "auth/login.html",
                {
                    "request": request,
                    "error": "Seu acesso está suspenso. Entre em contato com o suporte.",
                    "next_url": next_url,
                },
                status_code=403,
            )

        # 🚫 BLOQUEIO: ESCRITÓRIO SUSPENSO
        if raw_user.office and not raw_user.office.is_active:
            print("LOGIN BLOQUEADO: escritório suspenso")
            return templates.TemplateResponse(
                "auth/login.html",
                {
                    "request": request,
                    "error": "Este escritório está suspenso. Regularize a situação para acessar o sistema.",
                    "next_url": next_url,
                },
                status_code=403,
            )

    user = authenticate_user(db, login, password)

    if not user:
        register_login_failure(db, login=login, ip_address=client_ip)
        print("LOGIN FALHOU")
        print("=" * 70 + "\n")

        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "error": "Usuário/e-mail ou senha inválidos.",
                "next_url": next_url,
            },
            status_code=400,
        )

    # =========================
    # 🔥 SEGURANÇA DUPLA (fallback)
    # =========================
    if not user.is_active:
        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "error": "Seu acesso está suspenso.",
                "next_url": next_url,
            },
            status_code=403,
        )

    if user.office and not user.office.is_active:
        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "error": "Este escritório está suspenso.",
                "next_url": next_url,
            },
            status_code=403,
        )

    # =========================
    # 🔥 LOGIN NORMAL
    # =========================
    login_user(request, user.id, user.office_id)

    if "session" in request.scope:
        request.session["office_id"] = getattr(user, "office_id", None)

    # =========================
    # 🔥 ATUALIZA USUÁRIO E ESCRITÓRIO
    # =========================
    now = now_br()

    # atualiza usuário
    user.last_login_at = now

    # atualiza escritório
    if user.office_id:
        office = user.office  # lazy="joined" no model User

        if office:
            office.last_login_at = now
            office.last_activity_at = now
            office.last_user_id = user.id

    db.commit()

    # =========================
    # 🔥 AUDITORIA
    # =========================
    register_login_success(db, user=user, ip_address=client_ip)

    print(f"Sessão criada para user_id={user.id}")
    print("=" * 70 + "\n")

    return RedirectResponse(url=next_url, status_code=303)


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    current_user = getattr(request.state, "current_user", None)
    client_ip = request.client.host if request.client else None

    if current_user:
        register_logout(db, current_user, ip_address=client_ip)

    logout_user(request)

    return RedirectResponse(url="/login", status_code=303)


@router.get("/acesso-negado", response_class=HTMLResponse)
def access_denied(request: Request):
    return templates.TemplateResponse(
        "auth/access_denied.html",
        {"request": request},
        status_code=403,
    )