# app/models/office.py
from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.datetime_utils import now_br


class Office(Base):
    __tablename__ = "offices"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(150), nullable=False, index=True)

    is_active = Column(Boolean, nullable=False, default=True, index=True)

    suspended_at = Column(DateTime, nullable=True)
    suspension_reason = Column(String(255), nullable=True)

    created_at = Column(DateTime, nullable=False, default=now_br)

    updated_at = Column(
        DateTime,
        nullable=False,
        default=now_br,
        onupdate=now_br,
    )

    last_login_at = Column(DateTime, nullable=True)
    last_activity_at = Column(DateTime, nullable=True)

    last_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    users = relationship(
        "User",
        back_populates="office",
        foreign_keys="User.office_id",
        lazy="select",
    )

    last_user = relationship(
        "User",
        foreign_keys=[last_user_id],
        lazy="joined",
        post_update=True,
    )

    permission_links = relationship(
        "OfficePermission",
        back_populates="office",
        cascade="all, delete-orphan",
        lazy="select",
    )

    hearing_contacts = relationship(
        "HearingContact",
        back_populates="office",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )

    @property
    def is_suspended(self) -> bool:
        return not bool(self.is_active)

    def suspend(self, reason: str | None = None) -> None:
        self.is_active = False
        self.suspended_at = now_br()
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