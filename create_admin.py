from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

# IMPORTANTE: importar os models antes do create_tables
from app.models.user import User
from app.models.user_permission import UserPermission
from app.models.permission import Permission

from app.core.database import SessionLocal, create_tables
from app.core.security import hash_password


# =========================================================
# DADOS DO ADMIN
# =========================================================
ADMIN_NOME = "Administrador"
ADMIN_USERNAME = "03791012541"
ADMIN_EMAIL = "tarcisio_ios@hotmail.com"
ADMIN_PASSWORD = "81211801"


# =========================================================
# HELPERS
# =========================================================
def pick_field(model, *names):
    cols = set(model.__table__.columns.keys())
    for name in names:
        if name in cols:
            return name
    return None


def set_if_exists(data: dict, field_name: str | None, value):
    if field_name:
        data[field_name] = value


# =========================================================
# START
# =========================================================
create_tables()
db = SessionLocal()

try:
    field_name = pick_field(User, "name", "nome", "full_name", "username")
    field_login = pick_field(User, "login", "username", "user_name")
    field_email = pick_field(User, "email")
    field_password_hash = pick_field(User, "password_hash", "hashed_password", "senha_hash")
    field_password_plain = pick_field(User, "password", "senha")
    field_is_active = pick_field(User, "is_active", "ativo")
    field_is_admin = pick_field(User, "is_admin", "is_superuser", "is_staff", "admin")
    field_must_change_password = pick_field(User, "must_change_password")

    print("Campos encontrados em User:")
    print(list(User.__table__.columns.keys()))
    print()

    if not field_login and not field_email:
        raise RuntimeError("Não encontrei campo de login/email no model User.")

    # =====================================================
    # 1) LOCALIZA USUÁRIOS ANTIGOS DE ADMIN
    # =====================================================
    filtros = []

    if field_login:
        filtros.append(getattr(User, field_login) == "admin")
        filtros.append(getattr(User, field_login) == ADMIN_USERNAME)

    if field_email:
        filtros.append(getattr(User, field_email) == "admin@admin.com")
        filtros.append(getattr(User, field_email) == ADMIN_EMAIL)

    if field_is_admin:
        filtros.append(getattr(User, field_is_admin) == True)  # noqa: E712

    users_to_delete = []
    if filtros:
        users_to_delete = db.query(User).filter(or_(*filtros)).all()

    # remove duplicados por id, caso o mesmo usuário bata em mais de um filtro
    unique_users = {}
    for u in users_to_delete:
        unique_users[u.id] = u
    users_to_delete = list(unique_users.values())

    if users_to_delete:
        print("Usuários antigos encontrados para exclusão:")
        for u in users_to_delete:
            print(
                f" - id={u.id} | username={getattr(u, field_login, None)} | "
                f"email={getattr(u, field_email, None)}"
            )
        print()

        # =================================================
        # 2) REMOVE VÍNCULOS RELACIONADOS, SE NECESSÁRIO
        # =================================================
        user_ids = [u.id for u in users_to_delete]

        # remove permissões vinculadas
        if user_ids:
            deleted_links = (
                db.query(UserPermission)
                .filter(UserPermission.user_id.in_(user_ids))
                .delete(synchronize_session=False)
            )
            print(f"Permissões removidas: {deleted_links}")

        # remove usuários antigos
        for u in users_to_delete:
            db.delete(u)

        db.commit()
        print(f"Usuários admins antigos removidos: {len(users_to_delete)}")
        print()
    else:
        print("Nenhum admin antigo encontrado para exclusão.")
        print()

    # =====================================================
    # 3) RECRIA ADMIN LIMPO
    # =====================================================
    data = {}

    if field_name == "username" and not field_login:
        data[field_name] = ADMIN_USERNAME
    else:
        set_if_exists(data, field_name, ADMIN_NOME)

    if field_login:
        data[field_login] = ADMIN_USERNAME

    set_if_exists(data, field_email, ADMIN_EMAIL)

    if field_password_hash:
        data[field_password_hash] = hash_password(ADMIN_PASSWORD)
    elif field_password_plain:
        data[field_password_plain] = ADMIN_PASSWORD
    else:
        raise RuntimeError("Não encontrei campo de senha no model User.")

    set_if_exists(data, field_is_active, True)
    set_if_exists(data, field_is_admin, True)
    set_if_exists(data, field_must_change_password, False)

    new_user = User(**data)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    print("Usuário administrador recriado com sucesso!")
    print(f"ID: {new_user.id}")
    print(f"Login: {ADMIN_USERNAME}")
    print(f"Senha: {ADMIN_PASSWORD}")
    print(f"E-mail: {ADMIN_EMAIL}")

except IntegrityError as e:
    db.rollback()
    print("Erro de integridade ao recriar administrador.")
    print(str(e))

except Exception as e:
    db.rollback()
    print("Erro ao recriar administrador:")
    print(type(e).__name__, "-", str(e))

finally:
    db.close()