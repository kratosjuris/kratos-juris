# app/models/hearing_contact.py
from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class HearingContact(Base):
    __tablename__ = "hearing_contacts"

    __table_args__ = (
        UniqueConstraint(
            "office_id",
            "phone",
            name="uq_hearing_contact_office_phone",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    office_id = Column(
        Integer,
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name = Column(String(120), nullable=False)
    phone = Column(String(40), nullable=False)

    is_enabled = Column(
        Boolean,
        default=True,
        nullable=False,
    )

    office = relationship(
        "Office",
        back_populates="hearing_contacts",
    )