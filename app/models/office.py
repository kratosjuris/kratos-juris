# app/models/office.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class Office(Base):
    __tablename__ = "offices"

    id = Column(Integer, primary_key=True, index=True)

    nome = Column(String(150), nullable=False, index=True)

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

    def __repr__(self) -> str:
        return f"<Office id={self.id} nome='{self.nome}'>"