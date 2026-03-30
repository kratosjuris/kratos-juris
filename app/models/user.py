# app/models/user.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    nome = Column(String(150), nullable=False)

    email = Column(String(150), nullable=False, unique=True, index=True)

    username = Column(String(80), nullable=False, unique=True, index=True)

    # vínculo com escritório (multiempresa / multi-tenant)
    # nullable=True nesta primeira etapa para não quebrar usuários já existentes
    office_id = Column(
        Integer,
        ForeignKey("offices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # senha armazenada com hash
    password_hash = Column(String(255), nullable=False)

    is_active = Column(Boolean, nullable=False, default=True)

    is_superuser = Column(Boolean, nullable=False, default=False)

    must_change_password = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    last_login_at = Column(DateTime, nullable=True)

    # relacionamento com escritório
    office = relationship(
        "Office",
        back_populates="users",
        lazy="joined",
    )

    # relacionamento com permissões
    permission_links = relationship(
        "UserPermission",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    # logs de auditoria
    audit_logs = relationship(
        "AuditLog",
        back_populates="user",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<User id={self.id} username='{self.username}' "
            f"office_id={self.office_id}>"
        )