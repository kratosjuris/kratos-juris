# app/core/session_manager.py
from __future__ import annotations

from fastapi import Request

SESSION_USER_KEY = "user_id"


def _has_session(request: Request) -> bool:
    return "session" in request.scope


def login_user(request: Request, user_id: int) -> None:
    if not _has_session(request):
        raise RuntimeError("SessionMiddleware não está disponível nesta requisição.")
    request.session[SESSION_USER_KEY] = int(user_id)


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