# app/scripts/create_admin.py
from __future__ import annotations

from getpass import getpass

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User


def main():
    db = SessionLocal()
    try:
        username = input("Username do admin: ").strip().lower()
        email = input("E-mail do admin: ").strip().lower()
        nome = input("Nome do admin: ").strip()
        password = getpass("Senha: ")
        confirm = getpass("Confirmar senha: ")

        if password != confirm:
            print("As senhas não conferem.")
            return

        exists_user = db.query(User).filter((User.username == username) | (User.email == email)).first()
        if exists_user:
            print("Já existe usuário com esse username ou e-mail.")
            return

        user = User(
            nome=nome,
            email=email,
            username=username,
            password_hash=hash_password(password),
            is_active=True,
            is_superuser=True,
            must_change_password=False,
        )
        db.add(user)
        db.commit()
        print("Superadministrador criado com sucesso.")
    finally:
        db.close()


if __name__ == "__main__":
    main()