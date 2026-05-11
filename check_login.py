from __future__ import annotations

from app.core.database import SessionLocal
from app.models.user import User
from app.core.security import verify_password
from app.services.auth_service import get_user_by_login, authenticate_user

LOGIN_TESTE = "03791012541"
SENHA_TESTE = "81211801"


def main():
    db = SessionLocal()
    try:
        print("=" * 60)
        print("TESTE DIRETO DE LOGIN")
        print("=" * 60)

        users = db.query(User).all()
        print(f"Total de usuários no banco: {len(users)}")
        print()

        for u in users:
            print(
                f"id={u.id} | nome={u.nome} | email={u.email} | "
                f"username={u.username} | is_active={u.is_active} | "
                f"is_superuser={u.is_superuser}"
            )
            print(f"password_hash={u.password_hash}")
            print("-" * 60)

        print()
        print("1) Buscando usuário por login...")
        user = get_user_by_login(db, LOGIN_TESTE)
        print("Resultado get_user_by_login:", user)

        if user:
            print()
            print("2) Testando verify_password...")
            ok = verify_password(SENHA_TESTE, user.password_hash)
            print("verify_password =", ok)

        print()
        print("3) Testando authenticate_user...")
        auth_user = authenticate_user(db, LOGIN_TESTE, SENHA_TESTE)
        print("authenticate_user =", auth_user)

        print("=" * 60)

    finally:
        db.close()


if __name__ == "__main__":
    main()