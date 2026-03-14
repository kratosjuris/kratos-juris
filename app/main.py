# app/main.py
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import joinedload

from app.core.config import (
    SECRET_KEY,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    SECURE_COOKIES,
)
from app.core.database import create_tables, SessionLocal
from app.core.permission_seed import seed_permissions
from app.core.session_manager import get_session_user_id
from app.models.user import User
from app.models.user_permission import UserPermission

from app.routers import (
    web_dashboard,
    web_clients,
    web_birthdays,
    web_processes,
    web_finance,
    web_reports,
    web_pericias,
    web_migrations,
    hearings,
)
from app.routers.web_doc import router as web_doc_router
from app.routers import web_auth, web_users


# =========================================================
# HELPERS
# =========================================================
def _is_public_path(path: str) -> bool:
    public_prefixes = (
        "/login",
        "/logout",
        "/acesso-negado",
        "/static",
        "/favicon.ico",
    )
    return path.startswith(public_prefixes)


def _load_user_from_session(request: Request):
    request.state.current_user = None

    if "session" not in request.scope:
        print("[SESSION] request.scope sem 'session'")
        return None

    print(f"[SESSION] conteúdo bruto: {dict(request.session)}")

    user_id = get_session_user_id(request)
    print(f"[SESSION] user_id lido da sessão: {user_id}")

    if not user_id:
        return None

    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .options(
                joinedload(User.permission_links).joinedload(UserPermission.permission)
            )
            .filter(User.id == user_id)
            .first()
        )

        if user:
            print(
                f"[SESSION] usuário encontrado: id={user.id}, "
                f"username={user.username}, is_active={user.is_active}"
            )

        if user and user.is_active:
            request.state.current_user = user
            return user

        return None
    finally:
        db.close()


# =========================================================
# MIDDLEWARE CUSTOMIZADO DE AUTENTICAÇÃO
# =========================================================
class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path or ""

        current_user = _load_user_from_session(request)

        if not _is_public_path(path) and not current_user:
            next_url = request.url.path or "/"
            if request.url.query:
                next_url += f"?{request.url.query}"
            print(f"[AUTH] acesso bloqueado em {path}; redirecionando para /login")
            return RedirectResponse(url=f"/login?next={next_url}", status_code=303)

        return await call_next(request)


app = FastAPI(title="Sistema do Escritório")


# =========================================================
# STATIC
# =========================================================
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# =========================================================
# MIDDLEWARES
# IMPORTANTE:
# O SessionMiddleware DEVE ser adicionado por último,
# para executar primeiro e disponibilizar request.session.
# =========================================================
app.add_middleware(AuthenticationMiddleware)

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie=SESSION_COOKIE_NAME,
    max_age=SESSION_MAX_AGE,
    same_site="lax",
    https_only=SECURE_COOKIES,
)


# =========================================================
# STARTUP
# =========================================================
@app.on_event("startup")
def on_startup():
    create_tables()

    print("=" * 70)
    print("APP STARTUP")
    print(f"SESSION_COOKIE_NAME = {SESSION_COOKIE_NAME}")
    print(f"SESSION_MAX_AGE     = {SESSION_MAX_AGE}")
    print(f"SECURE_COOKIES      = {SECURE_COOKIES}")

    db = SessionLocal()
    try:
        created, existing = seed_permissions(db)
        print(f"[PERMISSIONS] criadas={created} existentes={existing}")
    except Exception as e:
        print(f"[PERMISSIONS] erro ao aplicar seed: {e}")
    finally:
        db.close()

    print("=" * 70)


# =========================================================
# ROUTERS
# =========================================================
app.include_router(web_auth.router)
app.include_router(web_users.router)

app.include_router(web_dashboard.router)
app.include_router(web_clients.router)
app.include_router(web_birthdays.router)
app.include_router(web_processes.router)
app.include_router(web_finance.router)
app.include_router(web_reports.router)
app.include_router(web_pericias.router)
app.include_router(web_migrations.router)
app.include_router(hearings.router)
app.include_router(web_doc_router)


# =========================================================
# REDIRECTS
# =========================================================
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard")


@app.get("/escritorio", include_in_schema=False)
def escritorio():
    return RedirectResponse(url="/dashboard")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)