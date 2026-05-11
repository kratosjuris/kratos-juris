from __future__ import annotations

import sqlite3
from pathlib import Path

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# =========================
# CONFIGURAÇÕES
# =========================
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "escritorio.db"

# informe aqui o login do usuário que você quer resetar
LOGIN_ALVO = "03791012541"   # pode ser username ou email

# informe aqui a nova senha
NOVA_SENHA = "81211801"

# deixar como True para ativar o usuário
ATIVAR_USUARIO = True

# deixar como True para tornar superusuário
TORNAR_SUPERUSER = True


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def table_exists(cur: sqlite3.Cursor, table_name: str) -> bool:
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cur.fetchone() is not None


def column_exists(cur: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
    cur.execute(f"PRAGMA table_info({table_name})")
    cols = cur.fetchall()
    return any(col[1] == column_name for col in cols)


def main() -> None:
    print("=" * 70)
    print("RESET DE SENHA - KRATOS JURIS")
    print("=" * 70)
    print(f"Banco em uso: {DB_PATH}")

    if not DB_PATH.exists():
        print("ERRO: arquivo escritorio.db não encontrado.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    if not table_exists(cur, "users"):
        print("ERRO: tabela 'users' não encontrada no banco.")
        conn.close()
        return

    print("\nUsuários encontrados no banco:")
    try:
        cur.execute(
            """
            SELECT id, nome, username, email, is_active, is_superuser
            FROM users
            ORDER BY id
            """
        )
        rows = cur.fetchall()

        if not rows:
            print("Nenhum usuário encontrado na tabela users.")
            conn.close()
            return

        for row in rows:
            print(
                f"id={row[0]} | nome={row[1]} | username={row[2]} | "
                f"email={row[3]} | active={row[4]} | superuser={row[5]}"
            )

    except Exception as e:
        print(f"Erro ao listar usuários: {e}")
        conn.close()
        return

    print("\nProcurando usuário alvo...")
    cur.execute(
        """
        SELECT id, nome, username, email
        FROM users
        WHERE username = ? OR email = ?
        LIMIT 1
        """,
        (LOGIN_ALVO, LOGIN_ALVO),
    )
    user = cur.fetchone()

    if not user:
        print(f"ERRO: nenhum usuário encontrado com login '{LOGIN_ALVO}'.")
        conn.close()
        return

    user_id, nome, username, email = user
    print(f"Usuário encontrado: id={user_id} | nome={nome} | username={username} | email={email}")

    novo_hash = hash_password(NOVA_SENHA)

    updates = ["password_hash = ?"]
    params = [novo_hash]

    if ATIVAR_USUARIO and column_exists(cur, "users", "is_active"):
        updates.append("is_active = 1")

    if TORNAR_SUPERUSER and column_exists(cur, "users", "is_superuser"):
        updates.append("is_superuser = 1")

    if column_exists(cur, "users", "must_change_password"):
        updates.append("must_change_password = 0")

    sql = f"""
        UPDATE users
        SET {", ".join(updates)}
        WHERE id = ?
    """
    params.append(user_id)

    try:
        cur.execute(sql, params)
        conn.commit()
        print("\nSenha redefinida com sucesso.")
        print(f"Login: {username} ou {email}")
        print(f"Nova senha: {NOVA_SENHA}")
    except Exception as e:
        print(f"Erro ao atualizar usuário: {e}")
    finally:
        conn.close()

    print("=" * 70)


if __name__ == "__main__":
    main()