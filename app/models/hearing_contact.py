from sqlalchemy import Column, Integer, String, Boolean
from app.core.database import Base


class HearingContact(Base):
    __tablename__ = "hearing_contacts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    phone = Column(String(40), nullable=False)  # formato livre; vamos normalizar no envio
    is_enabled = Column(Boolean, default=True, nullable=False)