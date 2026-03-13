# app/core/database.py
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# =====================================================
# CAMINHO BASE
# =====================================================

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "escritorio.db"

# =====================================================
# CONFIGURAÇÃO DO NEON (POSTGRESQL)
# =====================================================

POSTGRES_USER = "neondb_owner"
POSTGRES_PASSWORD = quote_plus("npg_3BO5YgUHpQlF")
POSTGRES_HOST = "ep-winter-unit-acjz4j3y-pooler.sa-east-1.aws.neon.tech"
POSTGRES_DB = "neondb"

NEON_DATABASE_URL = (
    f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}/{POSTGRES_DB}?sslmode=require"
)

# =====================================================
# DETECTA SE VAI USAR NEON OU SQLITE
# =====================================================

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URL = DATABASE_URL
    connect_args = {}

    print("BANCO POSTGRESQL VIA DATABASE_URL")

else:
    # usa Neon como padrão
    SQLALCHEMY_DATABASE_URL = NEON_DATABASE_URL
    connect_args = {}

    print("BANCO NEON POSTGRESQL EM USO")

# =====================================================
# ENGINE
# =====================================================

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()

# =====================================================
# DEPENDÊNCIA FASTAPI
# =====================================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =====================================================
# CRIAÇÃO DE TABELAS
# =====================================================

def create_tables():
    from app.models.user import User
    from app.models.permission import Permission
    from app.models.user_permission import UserPermission
    from app.models.audit_log import AuditLog

    try:
        from app.models.client import Client
    except Exception:
        pass

    try:
        from app.models.hearing import Hearing
    except Exception:
        pass

    try:
        from app.models.hearing_contact import HearingContact
    except Exception:
        pass

    try:
        from app.models.finance_models import (
            FinanceMonth,
            ExpenseTemplate,
            Payable,
            Receivable,
        )
    except Exception:
        pass

    Base.metadata.create_all(bind=engine)