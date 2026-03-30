# app/models/office.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class Office(Base):
    __tablename__ = "offices"

    id = Column(Integer, primary_key=True, index=True)

    nome = Column(String(150), nullable=False, index=True)

    # controle administrativo do escritório
    # True = ativo | False = suspenso/bloqueado
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    suspended_at = Column(DateTime, nullable=True)
    suspension_reason = Column(String(255), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # relacionamento com usuários do escritório
    users = relationship(
        "User",
        back_populates="office",
        lazy="select",
    )

    @property
    def is_suspended(self) -> bool:
        return not bool(self.is_active)

    def suspend(self, reason: str | None = None) -> None:
        self.is_active = False
        self.suspended_at = datetime.utcnow()
        self.suspension_reason = (reason or "").strip() or None

    def reactivate(self) -> None:
        self.is_active = True
        self.suspended_at = None
        self.suspension_reason = None

    def __repr__(self) -> str:
        return (
            f"<Office id={self.id} nome='{self.nome}' "
            f"is_active={self.is_active}>"
        )