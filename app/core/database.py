# app/core/database.py
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "escritorio.db"

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URL = DATABASE_URL
    connect_args = {}
    print("BANCO POSTGRESQL (RENDER/NEON) EM USO")
else:
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"
    connect_args = {"check_same_thread": False}
    print("BANCO SQLITE LOCAL EM USO:", DB_PATH)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
        from app.models.finance_models import FinanceMonth, ExpenseTemplate, Payable, Receivable
    except Exception:
        pass

    Base.metadata.create_all(bind=engine)