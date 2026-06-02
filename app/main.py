from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.orm import joinedload

from app.core.config import (
    SECRET_KEY,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    SECURE_COOKIES,
)
from app.core.database import create_tables, SessionLocal, engine
from app.core.permission_seed import seed_permissions
from app.core.session_manager import get_session_user_id, get_session_office_id

from app.models.user import User
from app.models.user_permission import UserPermission
from app.models.office import Office
from app.models.office_permission import OfficePermission
from app.models.document_template import OfficeDocumentTemplate  # noqa: F401
from app.models.hearing_contact import HearingContact  # noqa: F401

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
from app.routers.web_doc_templates import router as web_doc_templates_router
from app.routers.web_signup import router as signup_router
from app.routers import web_superadmin_assinantes
from app.routers import web_auth, web_users, web_account
from app.routers import web_offices
from app.routers import web_whatsapp_templates

# =========================================================
# NOVO: MERCADO PAGO
# =========================================================
from app.routers.web_mp import router as mp_router


# =========================================================
# APP / PATHS
# =========================================================
BASE_DIR = Path(__file__).resolve().parent

STATIC_DIR = BASE_DIR / "static"

FAVICON_PATH = STATIC_DIR / "favicon.ico"


# =========================================================
# HELPERS
# =========================================================
def _is_public_path(path: str):
    public_prefixes = (
        "/login",
        "/logout",
        "/acesso-negado",
        "/static",
        "/favicon.ico",
        "/ping",

        # cadastro público cliente
        "/clientes/cadastro",
        "/clientes/cadastro/",

        # MERCADO PAGO
        "/mp",
        "/mp/",

        # ASSINATURA PÚBLICA
        "/assinar",
        "/assinar/",

        # TERMOS DE USO
        "/termos",
        "/termos/",
    )

    return path.startswith(public_prefixes)


def _load_user_from_session(request: Request):

    request.state.current_user = None
    request.state.current_office_id = None

    if "session" not in request.scope:
        print("[SESSION] request.scope sem 'session'")
        return None

    print(f"[SESSION] conteúdo bruto: {dict(request.session)}")

    user_id = get_session_user_id(request)
    session_office_id = get_session_office_id(request)

    print(f"[SESSION] user_id lido da sessão: {user_id}")
    print(f"[SESSION] office_id lido da sessão: {session_office_id}")

    if not user_id:
        return None

    db = SessionLocal()

    try:

        user = (
            db.query(User)
            .options(
                joinedload(User.permission_links)
                .joinedload(UserPermission.permission),

                joinedload(User.office)
                .joinedload(Office.permission_links)
                .joinedload(OfficePermission.permission),
            )
            .filter(User.id == user_id)
            .first()
        )

        if user:

            print(
                f"[SESSION] usuário encontrado: "
                f"id={user.id}, "
                f"username={user.username}, "
                f"is_active={user.is_active}, "
                f"office_id={getattr(user, 'office_id', None)}"
            )

            office = getattr(user, "office", None)

            if office:

                office_perm_codes = []

                for op in getattr(office, "permission_links", []) or []:

                    perm = getattr(op, "permission", None)

                    code = getattr(perm, "code", None)

                    if code:
                        office_perm_codes.append(code)

                print(
                    f"[SESSION] escritório carregado: "
                    f"id={office.id}, "
                    f"nome={office.nome}, "
                    f"is_active={office.is_active}, "
                    f"permissions={office_perm_codes}"
                )

        if user and user.is_active:

            request.state.current_user = user

            if session_office_id is not None:
                request.state.current_office_id = session_office_id
            else:
                request.state.current_office_id = getattr(user, "office_id", None)

            return user

        return None

    finally:
        db.close()


# =========================================================
# MIGRAÇÕES SIMPLES DE COLUNAS
# =========================================================
def _ensure_offices_finance_password_hash_column() -> None:
    """
    Garante a existência da coluna offices.finance_password_hash.
    """

    try:

        inspector = inspect(engine)

        columns = [c["name"] for c in inspector.get_columns("offices")]

        if "finance_password_hash" in columns:
            print("[DB] coluna offices.finance_password_hash já existe")
            return

        dialect = engine.dialect.name

        if dialect == "postgresql":
            ddl = (
                "ALTER TABLE offices "
                "ADD COLUMN finance_password_hash VARCHAR(255)"
            )
        else:
            ddl = (
                "ALTER TABLE offices "
                "ADD COLUMN finance_password_hash VARCHAR(255)"
            )

        with engine.begin() as conn:
            conn.execute(text(ddl))

        print("[DB] coluna offices.finance_password_hash criada com sucesso")

    except Exception as e:
        print(
            "[DB] erro ao garantir coluna "
            f"offices.finance_password_hash: {e}"
        )


# =========================================================
# MIDDLEWARE CUSTOMIZADO DE AUTENTICAÇÃO
# =========================================================
class AuthenticationMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        path = request.url.path or ""

        if _is_public_path(path):
            return await call_next(request)

        current_user = _load_user_from_session(request)

        if not current_user:

            next_url = request.url.path or "/"

            if request.url.query:
                next_url += f"?{request.url.query}"

            print(
                f"[AUTH] acesso bloqueado em {path}; "
                f"redirecionando para /login"
            )

            return RedirectResponse(
                url=f"/login?next={next_url}",
                status_code=303,
            )

        return await call_next(request)


app = FastAPI(title="Sistema do Escritório")


# =========================================================
# STATIC
# =========================================================
app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)


# =========================================================
# MIDDLEWARES
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

    _ensure_offices_finance_password_hash_column()

    print("=" * 70)
    print("APP STARTUP")

    print(f"SESSION_COOKIE_NAME = {SESSION_COOKIE_NAME}")
    print(f"SESSION_MAX_AGE     = {SESSION_MAX_AGE}")
    print(f"SECURE_COOKIES      = {SECURE_COOKIES}")

    db = SessionLocal()

    try:

        created, existing = seed_permissions(db)

        print(
            f"[PERMISSIONS] criadas={created} "
            f"existentes={existing}"
        )

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

app.include_router(web_account.router)

app.include_router(web_offices.router)

app.include_router(web_whatsapp_templates.router)

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

app.include_router(web_doc_templates_router)

# =========================================================
# NOVO: MERCADO PAGO
# =========================================================
app.include_router(mp_router)

# =========================================================
# SUPERADMIN - ASSINANTES
# =========================================================
app.include_router(web_superadmin_assinantes.router)

# =========================================================
# NOVO: ASSINATURA PÚBLICA
# =========================================================
app.include_router(signup_router)


# =========================================================
# PING (KEEP ALIVE)
# =========================================================
@app.get("/ping", include_in_schema=False)
def ping():
    return {"status": "ok"}


# =========================================================
# REDIRECTS
# =========================================================
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard")


@app.get("/escritorio", include_in_schema=False)
def escritorio():
    return RedirectResponse(url="/dashboard")


# =========================================================
# FAVICON
# =========================================================
@app.get("/favicon.ico", include_in_schema=False)
def favicon():

    if FAVICON_PATH.exists():
        return FileResponse(FAVICON_PATH)

    return Response(status_code=204)