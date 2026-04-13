# app/core/permissions.py
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException, Request, status

from app.models.user import User


# intervalo mínimo para atualizar atividade do escritório (evita sobrecarga)
ACTIVITY_UPDATE_INTERVAL_MINUTES = 5


def _get_user_permission_codes(user: User) -> set[str]:
    """
    Retorna os códigos de permissão atribuídos diretamente ao usuário.
    """
    codes: set[str] = set()

    for up in (getattr(user, "permission_links", None) or []):
        perm = getattr(up, "permission", None)
        code = getattr(perm, "code", None)
        if code:
            codes.add(code)

    return codes


def _get_office_permission_codes(user: User) -> set[str]:
    """
    Retorna os códigos de permissão herdados do escritório do usuário.
    """
    codes: set[str] = set()

    office = getattr(user, "office", None)
    if not office:
        return codes

    for op in (getattr(office, "permission_links", None) or []):
        perm = getattr(op, "permission", None)
        code = getattr(perm, "code", None)
        if code:
            codes.add(code)

    return codes


def user_has_permission(user: User | None, code: str) -> bool:
    """
    Verifica se o usuário possui determinada permissão.
    """
    if not user:
        return False

    if not getattr(user, "is_active", False):
        return False

    if getattr(user, "is_superuser", False):
        return True

    user_codes = _get_user_permission_codes(user)
    if code in user_codes:
        return True

    office_codes = _get_office_permission_codes(user)
    if code in office_codes:
        return True

    return False


def _update_office_activity(request: Request, user: User) -> None:
    """
    Atualiza a última atividade do escritório de forma controlada.
    Evita commit em toda requisição.
    """
    office = getattr(user, "office", None)
    if not office:
        return

    db = getattr(request.state, "db", None)
    if not db:
        return

    now = datetime.utcnow()

    last_activity = getattr(office, "last_activity_at", None)

    if (
        not last_activity
        or (now - last_activity) >= timedelta(minutes=ACTIVITY_UPDATE_INTERVAL_MINUTES)
    ):
        office.last_activity_at = now
        office.last_user_id = user.id

        try:
            db.commit()
        except Exception:
            db.rollback()


def require_login_user(request: Request) -> User:
    """
    Exige que exista um usuário autenticado.
    Também atualiza a atividade do escritório.
    """
    user = getattr(request.state, "current_user", None)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Faça login para continuar.",
        )

    if not getattr(user, "is_active", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuário inativo.",
        )

    office = getattr(user, "office", None)
    if office is not None and not getattr(office, "is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O escritório do usuário está suspenso ou inativo.",
        )

    # 🔥 ATUALIZA ATIVIDADE DO ESCRITÓRIO
    _update_office_activity(request, user)

    return user


def require_permission(request: Request, code: str) -> User:
    """
    Exige que o usuário tenha permissão.
    """
    user = require_login_user(request)

    if not user_has_permission(user, code):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Você não possui a permissão: {code}",
        )

    return user


def require_superuser(request: Request) -> User:
    """
    Exige superusuário.
    """
    user = require_login_user(request)

    if not getattr(user, "is_superuser", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito ao superadministrador.",
        )

    return user