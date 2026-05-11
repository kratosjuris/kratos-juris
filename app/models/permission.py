# app/models/permission.py
from __future__ import annotations

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(120), nullable=False, unique=True, index=True)
    name = Column(String(150), nullable=False)
    module = Column(String(80), nullable=False, index=True)
    description = Column(String(255), nullable=True)

    user_links = relationship(
        "UserPermission",
        back_populates="permission",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Permission code={self.code!r}>"