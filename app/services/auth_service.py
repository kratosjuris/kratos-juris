# app/services/auth_service.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.models.audit_log import AuditLog
from app.models.user import User


def _only_digits(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def get_user_by_login(db: Session, login: str) -> User | None:
    login = (login or "").strip()
    if not login:
        return None

    login_digits = _only_digits(login)

    filtros = [
        User.email == login,
        User.username == login,
    ]

    if login_digits and login_digits != login:
        filtros.append(User.username == login_digits)

    return db.query(User).filter(or_(*filtros)).first()


def authenticate_user(db: Session, login: str, password: str) -> User | None:
    login = (login or "").strip()
    password = password or ""

    user = get_user_by_login(db, login)
    if not user:
        return None

    if not user.is_active:
        return None

    try:
        password_ok = verify_password(password, user.password_hash)
    except Exception as e:
        print(f"[AUTH] erro ao verificar hash do usuário {user.username}: {e}")
        return None

    if not password_ok:
        return None

    return user


def register_login_success(
    db: Session,
    user: User,
    ip_address: str | None = None,
) -> None:
    user.last_login_at = datetime.utcnow()

    log = AuditLog(
        user_id=user.id,
        action="login_success",
        module="auth",
        description=f"Login realizado por {user.username}",
        ip_address=ip_address,
    )
    db.add(log)
    db.commit()


def register_login_failure(
    db: Session,
    login: str,
    ip_address: str | None = None,
) -> None:
    log = AuditLog(
        user_id=None,
        action="login_failure",
        module="auth",
        description=f"Tentativa de login inválida para: {login}",
        ip_address=ip_address,
    )
    db.add(log)
    db.commit()


def register_logout(
    db: Session,
    user: User,
    ip_address: str | None = None,
) -> None:
    log = AuditLog(
        user_id=user.id,
        action="logout",
        module="auth",
        description=f"Logout realizado por {user.username}",
        ip_address=ip_address,
    )
    db.add(log)
    db.commit()