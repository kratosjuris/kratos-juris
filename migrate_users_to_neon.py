# migrate_users_to_neon.py
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models.user import User
from app.core.database import Base

# ========= CONFIGURAÇÕES =========
BASE_DIR = Path(__file__).resolve().parent
SQLITE_PATH = BASE_DIR / "escritorio.db"

SQLITE_URL = f"sqlite:///{SQLITE_PATH.as_posix()}"

POSTGRES_USER = "neondb_owner"
POSTGRES_PASSWORD = quote_plus("npg_3BO5YgUHpQlF")
POSTGRES_HOST = "ep-winter-unit-acjz4j3y-pooler.sa-east-1.aws.neon.tech"
POSTGRES_DB = "neondb"

POSTGRES_URL = (
    f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}/{POSTGRES_DB}?sslmode=require&channel_binding=require"
)
# ================================

sqlite_engine = create_engine(
    SQLITE_URL,
    connect_args={"check_same_thread": False},
)

postgres_engine = create_engine(
    POSTGRES_URL,
    pool_pre_ping=True,
)

SQLiteSession = sessionmaker(autocommit=False, autoflush=False, bind=sqlite_engine)
PostgresSession = sessionmaker(autocommit=False, autoflush=False, bind=postgres_engine)


def testar_conexao_postgres():
    print("Testando conexão com Neon/Postgres...")
    print(
        "URL montada: "
        f"postgresql+psycopg2://{POSTGRES_USER}:***@{POSTGRES_HOST}/{POSTGRES_DB}"
        "?sslmode=require&channel_binding=require"
    )

    with postgres_engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    print("[OK] Conexão com Neon estabelecida com sucesso.")


def main():
    print(f"BANCO SQLITE LOCAL EM USO: {SQLITE_PATH}")

    if not SQLITE_PATH.exists():
        raise FileNotFoundError(f"Banco SQLite não encontrado em: {SQLITE_PATH}")

    testar_conexao_postgres()

    print("Criando tabelas no Postgres, se não existirem...")
    Base.metadata.create_all(bind=postgres_engine)

    sqlite_db = SQLiteSession()
    postgres_db = PostgresSession()

    try:
        users = sqlite_db.query(User).order_by(User.id.asc()).all()
        print(f"Usuários encontrados no SQLite: {len(users)}")

        migrated = 0
        skipped = 0

        for user in users:
            existing = (
                postgres_db.query(User)
                .filter(
                    (User.username == user.username) | (User.email == user.email)
                )
                .first()
            )

            if existing:
                print(f"[IGNORADO] Já existe no Postgres: {user.username} / {user.email}")
                skipped += 1
                continue

            novo = User(
                id=user.id,
                nome=user.nome,
                email=user.email,
                username=user.username,
                password_hash=user.password_hash,
                is_active=user.is_active,
                is_superuser=user.is_superuser,
                must_change_password=user.must_change_password,
                created_at=user.created_at,
                updated_at=user.updated_at,
                last_login_at=user.last_login_at,
            )

            postgres_db.add(novo)
            migrated += 1
            print(f"[MIGRADO] {user.username} / {user.email}")

        postgres_db.commit()

        print("=" * 60)
        print(f"[OK] Usuários migrados: {migrated}")
        print(f"[OK] Usuários ignorados: {skipped}")
        print("=" * 60)

    except Exception as e:
        postgres_db.rollback()
        print(f"[ERRO] Falha durante a migração: {e}")
        raise
    finally:
        sqlite_db.close()
        postgres_db.close()


if __name__ == "__main__":
    main()