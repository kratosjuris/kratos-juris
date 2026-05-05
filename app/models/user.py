# app/models/user.py
from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.datetime_utils import now_br


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    nome = Column(String(150), nullable=False)

    email = Column(String(150), nullable=False, unique=True, index=True)

    username = Column(String(80), nullable=False, unique=True, index=True)

    office_id = Column(
        Integer,
        ForeignKey("offices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    password_hash = Column(String(255), nullable=False)

    is_active = Column(Boolean, nullable=False, default=True, index=True)

    is_superuser = Column(Boolean, nullable=False, default=False)

    must_change_password = Column(Boolean, nullable=False, default=False)

    deactivated_at = Column(DateTime(timezone=True), nullable=True)
    deactivation_reason = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=now_br)

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=now_br,
        onupdate=now_br,
    )

    last_login_at = Column(DateTime(timezone=True), nullable=True)

    office = relationship(
        "Office",
        back_populates="users",
        foreign_keys=[office_id],
        lazy="joined",
    )

    permission_links = relationship(
        "UserPermission",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    audit_logs = relationship(
        "AuditLog",
        back_populates="user",
        lazy="select",
    )

    @property
    def is_suspended(self) -> bool:
        return not bool(self.is_active)

    def suspend(self, reason: str | None = None) -> None:
        self.is_active = False
        self.deactivated_at = now_br()
        self.deactivation_reason = (reason or "").strip() or None

    def reactivate(self) -> None:
        self.is_active = True
        self.deactivated_at = None
        self.deactivation_reason = None

    def __repr__(self) -> str:
        return (
            f"<User id={self.id} username='{self.username}' "
            f"office_id={self.office_id} is_active={self.is_active}>"
        )