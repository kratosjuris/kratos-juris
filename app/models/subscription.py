from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.datetime_utils import now_br


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)

    office_id = Column(
        Integer,
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    mercadopago_payment_id = Column(String(100), nullable=True, index=True)
    mercadopago_email = Column(String(255), nullable=True, index=True)

    valor = Column(Float, nullable=False, default=59.90)
    status = Column(String(50), nullable=False, default="approved", index=True)

    created_at = Column(DateTime, nullable=False, default=now_br)
    updated_at = Column(DateTime, nullable=False, default=now_br, onupdate=now_br)

    office = relationship("Office")