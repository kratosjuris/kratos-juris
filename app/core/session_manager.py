# app/core/session_manager.py
from __future__ import annotations

from fastapi import Request

SESSION_USER_KEY = "user_id"
SESSION_OFFICE_KEY = "office_id"


def _has_session(request: Request) -> bool:
    return "session" in request.scope


def login_user(request: Request, user_id: int, office_id: int | None = None) -> None:
    """
    Cria a sessão do usuário.

    Agora também suporta office_id (multiempresa).
    """
    if not _has_session(request):
        raise RuntimeError("SessionMiddleware não está disponível nesta requisição.")

    request.session[SESSION_USER_KEY] = int(user_id)

    # novo: salva office_id na sessão
    if office_id is not None:
        request.session[SESSION_OFFICE_KEY] = int(office_id)
    else:
        # compatibilidade com usuários antigos
        request.session[SESSION_OFFICE_KEY] = None


def logout_user(request: Request) -> None:
    if not _has_session(request):
        return

    request.session.clear()


def get_session_user_id(request: Request) -> int | None:
    if not _has_session(request):
        return None

    value = request.session.get(SESSION_USER_KEY)
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_session_office_id(request: Request) -> int | None:
    """
    Recupera o office_id da sessão.
    """
    if not _has_session(request):
        return None

    value = request.session.get(SESSION_OFFICE_KEY)
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None