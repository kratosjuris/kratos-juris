# app/core/permissions.py
from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.models.user import User


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

    Funciona se o relacionamento user.office -> office.permission_links
    estiver carregado no contexto atual.
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

    Ordem:
    1. usuário autenticado
    2. usuário ativo
    3. superuser
    4. permissão direta do usuário
    5. permissão herdada do escritório
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


def require_login_user(request: Request) -> User:
    """
    Exige que exista um usuário autenticado em request.state.current_user.
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

    return user


def require_permission(request: Request, code: str) -> User:
    """
    Exige que o usuário logado possua a permissão informada,
    seja diretamente ou herdada do escritório.
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