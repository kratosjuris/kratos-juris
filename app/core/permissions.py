# app/core/permissions.py
from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.models.user import User


def user_has_permission(user: User | None, code: str) -> bool:
    if not user:
        return False
    if not user.is_active:
        return False
    if user.is_superuser:
        return True

    user_codes = {
        up.permission.code
        for up in (user.permission_links or [])
        if up.permission
    }
    return code in user_codes


def require_login_user(request: Request) -> User:
    user = getattr(request.state, "current_user", None)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Faça login para continuar.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuário inativo.",
        )

    return user


def require_permission(request: Request, code: str) -> User:
    user = require_login_user(request)

    if not user_has_permission(user, code):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Você não possui a permissão: {code}",
        )

    return user


def require_superuser(request: Request) -> User:
    user = require_login_user(request)

    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito ao superadministrador.",
        )

    return user