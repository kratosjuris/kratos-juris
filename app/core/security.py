# app/core/security.py
from __future__ import annotations

from passlib.context import CryptContext

# =========================================================
# CONTEXTO DE HASH
# =========================================================

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


# =========================================================
# SENHAS
# =========================================================

def hash_password(password: str) -> str:
    """
    Gera hash seguro da senha.
    """
    password = (password or "").strip()

    return pwd_context.hash(password)


def verify_password(
    plain_password: str,
    password_hash: str | None,
) -> bool:
    """
    Verifica se a senha informada corresponde ao hash salvo.
    """

    if not plain_password:
        return False

    if not password_hash:
        return False

    try:
        return pwd_context.verify(
            plain_password.strip(),
            password_hash,
        )
    except Exception:
        return False


# =========================================================
# HELPERS
# =========================================================

def needs_password_change(user) -> bool:
    """
    Verifica se o usuário deve alterar a senha.
    """

    return bool(
        getattr(user, "must_change_password", False)
    )


def validate_new_password(
    password: str,
    confirm_password: str,
) -> tuple[bool, str]:
    """
    Valida nova senha.
    """

    password = (password or "").strip()
    confirm_password = (confirm_password or "").strip()

    if not password:
        return False, "A nova senha não foi informada."

    if len(password) < 6:
        return False, "A senha deve possuir no mínimo 6 caracteres."

    if password != confirm_password:
        return False, "A confirmação da senha não confere."

    return True, ""