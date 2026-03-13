# app/routers/web_auth.py
from __future__ import annotations

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
from app.core.security import verify_password

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
    print(f"login recebido: {repr(login)}")
    print(f"next_url: {repr(next_url)}")
    print(f"client_ip: {repr(client_ip)}")

    raw_user = get_user_by_login(db, login)
    print(f"user localizado: {raw_user}")

    if raw_user:
        print(f"user.id: {raw_user.id}")
        print(f"user.username: {raw_user.username}")
        print(f"user.email: {raw_user.email}")
        print(f"user.is_active: {raw_user.is_active}")

        try:
            password_ok = verify_password(password, raw_user.password_hash)
        except Exception as e:
            password_ok = False
            print(f"erro ao verificar senha/hash: {e}")

        print(f"verify_password: {password_ok}")
    else:
        print("Nenhum usuário encontrado por login.")

    user = authenticate_user(db, login, password)
    print(f"authenticate_user retorno: {user}")

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

    login_user(request, user.id)
    print(f"Sessão após login_user: {dict(request.session)}")

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

    print(
        f"Sessão antes do logout: "
        f"{dict(request.session) if 'session' in request.scope else 'sem session'}"
    )
    logout_user(request)
    print(
        f"Sessão após logout: "
        f"{dict(request.session) if 'session' in request.scope else 'sem session'}"
    )

    return RedirectResponse(url="/login", status_code=303)


@router.get("/acesso-negado", response_class=HTMLResponse)
def access_denied(request: Request):
    return templates.TemplateResponse(
        "auth/access_denied.html",
        {"request": request},
        status_code=403,
    )