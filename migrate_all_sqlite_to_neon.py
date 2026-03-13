from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    Time,
    BigInteger,
    create_engine,
    inspect,
    text,
)

# =========================================================
# CONFIGURAÇÕES
# =========================================================
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

SKIP_NON_EMPTY_TABLES = True

IGNORE_TABLES = {
    "alembic_version",
}
# =========================================================

sqlite_engine = create_engine(
    SQLITE_URL,
    connect_args={"check_same_thread": False},
)

postgres_engine = create_engine(
    POSTGRES_URL,
    pool_pre_ping=True,
    connect_args={
        "sslmode": "require",
        "connect_timeout": 10,
    },
)


def test_connections():
    print(f"BANCO SQLITE LOCAL EM USO: {SQLITE_PATH}")

    if not SQLITE_PATH.exists():
        raise FileNotFoundError(f"Banco SQLite não encontrado em: {SQLITE_PATH}")

    with sqlite_engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("[OK] Conexão com SQLite estabelecida.")

    with postgres_engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("[OK] Conexão com Neon/Postgres estabelecida.")


def reflect_sqlite_metadata() -> MetaData:
    print("Lendo estrutura do SQLite...")
    source_metadata = MetaData()
    source_metadata.reflect(bind=sqlite_engine)
    print(f"[OK] Tabelas encontradas no SQLite: {len(source_metadata.tables)}")
    return source_metadata


def normalize_type(col_type):
    type_name = col_type.__class__.__name__.upper()

    if isinstance(col_type, String):
        try:
            return String(length=col_type.length) if col_type.length else Text()
        except Exception:
            return Text()

    if isinstance(col_type, Text):
        return Text()

    if isinstance(col_type, Integer):
        return Integer()

    if isinstance(col_type, SmallInteger):
        return SmallInteger()

    if isinstance(col_type, BigInteger):
        return BigInteger()

    if isinstance(col_type, Boolean):
        return Boolean()

    if isinstance(col_type, DateTime) or type_name == "DATETIME":
        return DateTime()

    if isinstance(col_type, Date) or type_name == "DATE":
        return Date()

    if isinstance(col_type, Time) or type_name == "TIME":
        return Time()

    if isinstance(col_type, Float):
        return Float()

    if isinstance(col_type, Numeric):
        try:
            return Numeric(
                precision=getattr(col_type, "precision", None),
                scale=getattr(col_type, "scale", None),
            )
        except Exception:
            return Numeric()

    if isinstance(col_type, LargeBinary):
        return LargeBinary()

    return Text()


def clone_table_without_constraints(source_table, target_metadata: MetaData):
    new_columns = []
    pk_names = {col.name for col in source_table.primary_key.columns}

    for col in source_table.columns:
        new_col = Column(
            col.name,
            normalize_type(col.type),
            primary_key=(col.name in pk_names),
            nullable=col.nullable,
        )
        new_columns.append(new_col)

    Table(source_table.name, target_metadata, *new_columns)


def create_tables_in_postgres(source_metadata: MetaData) -> MetaData:
    print("Criando estrutura no Neon/Postgres...")
    target_metadata = MetaData()

    for table in source_metadata.sorted_tables:
        if table.name in IGNORE_TABLES:
            print(f"[IGNORADO] Estrutura da tabela {table.name}")
            continue

        clone_table_without_constraints(table, target_metadata)

    target_metadata.create_all(bind=postgres_engine)
    print("[OK] Estrutura criada/garantida no Neon.")
    return target_metadata


def is_table_non_empty_pg(table_name: str) -> bool:
    with postgres_engine.connect() as conn:
        count = conn.execute(
            text(f'SELECT COUNT(*) FROM "{table_name}"')
        ).scalar() or 0
    return count > 0


def get_pg_column_limits(table_name: str) -> dict[str, int | None]:
    inspector = inspect(postgres_engine)
    limits: dict[str, int | None] = {}

    for col in inspector.get_columns(table_name):
        col_type = col.get("type")
        length = getattr(col_type, "length", None)
        limits[col["name"]] = length

    return limits


def sanitize_value(value, max_len: int | None, table_name: str, col_name: str):
    if value is None:
        return None

    if isinstance(value, (datetime, date, time, int, float, Decimal, bool, bytes)):
        return value

    if not isinstance(value, str):
        value = str(value)

    if max_len is not None and len(value) > max_len:
        print(
            f"[TRUNCADO] {table_name}.{col_name} "
            f"({len(value)} -> {max_len})"
        )
        return value[:max_len]

    return value


def copy_table_data(source_table, target_metadata: MetaData):
    table_name = source_table.name

    if table_name in IGNORE_TABLES:
        print(f"[IGNORADO] Dados da tabela {table_name}")
        return

    if SKIP_NON_EMPTY_TABLES and is_table_non_empty_pg(table_name):
        print(f"[IGNORADO] Tabela {table_name} já possui dados no Postgres.")
        return

    target_table = target_metadata.tables.get(table_name)
    if target_table is None:
        print(f"[IGNORADO] Tabela {table_name} não existe no metadata de destino.")
        return

    with sqlite_engine.connect() as src_conn:
        rows = src_conn.execute(source_table.select()).mappings().all()

    if not rows:
        print(f"[VAZIA] Tabela {table_name} sem registros no SQLite.")
        return

    limits = get_pg_column_limits(table_name)

    batch = []
    for row in rows:
        cleaned = {}
        for col_name, value in dict(row).items():
            cleaned[col_name] = sanitize_value(
                value=value,
                max_len=limits.get(col_name),
                table_name=table_name,
                col_name=col_name,
            )
        batch.append(cleaned)

    with postgres_engine.begin() as dst_conn:
        dst_conn.execute(target_table.insert(), batch)

    print(f"[MIGRADA] {table_name}: {len(batch)} registros")


def reset_postgres_sequences():
    print("Ajustando sequences/autoincrement do Postgres...")
    inspector = inspect(postgres_engine)

    with postgres_engine.begin() as conn:
        for table_name in inspector.get_table_names():
            if table_name in IGNORE_TABLES:
                continue

            pk = inspector.get_pk_constraint(table_name) or {}
            pk_cols = pk.get("constrained_columns") or []

            if len(pk_cols) != 1:
                continue

            pk_col = pk_cols[0]

            seq_sql = text(
                f"""SELECT pg_get_serial_sequence('"public"."{table_name}"', '{pk_col}')"""
            )
            seq_name = conn.execute(seq_sql).scalar()

            if not seq_name:
                continue

            reset_sql = text(
                f"""
                SELECT setval(
                    '{seq_name}',
                    COALESCE((SELECT MAX("{pk_col}") FROM "{table_name}"), 0) + 1,
                    false
                )
                """
            )
            conn.execute(reset_sql)
            print(f"[OK] Sequence ajustada: {table_name}.{pk_col}")

    print("[OK] Sequences ajustadas.")


def show_summary(source_metadata: MetaData):
    print("=" * 70)
    print("RESUMO DE CONTAGEM")
    print("=" * 70)

    with sqlite_engine.connect() as src_conn, postgres_engine.connect() as dst_conn:
        for table in source_metadata.sorted_tables:
            if table.name in IGNORE_TABLES:
                continue

            sqlite_count = src_conn.execute(
                text(f'SELECT COUNT(*) FROM "{table.name}"')
            ).scalar() or 0

            pg_count = dst_conn.execute(
                text(f'SELECT COUNT(*) FROM "{table.name}"')
            ).scalar() or 0

            print(f"{table.name:<35} SQLite={sqlite_count:<8} Postgres={pg_count:<8}")

    print("=" * 70)


def main():
    test_connections()

    source_metadata = reflect_sqlite_metadata()
    target_metadata = create_tables_in_postgres(source_metadata)

    print("Iniciando cópia dos dados...")
    for table in source_metadata.sorted_tables:
        copy_table_data(table, target_metadata)

    reset_postgres_sequences()
    show_summary(source_metadata)

    print("[OK] Migração completa finalizada com sucesso.")


if __name__ == "__main__":
    main()