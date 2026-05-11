from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class Hearing(Base):
    __tablename__ = "hearings"

    id = Column(Integer, primary_key=True, index=True)

    office_id = Column(
        Integer,
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    process_number = Column(String(60), nullable=False, index=True)
    promovente = Column(String(255), nullable=True)
    promovido = Column(String(255), nullable=True)

    # data e hora unificados
    starts_at = Column(DateTime, nullable=False, index=True)

    modalidade = Column(String(80), nullable=True)  # Telepresencial / Presencial etc
    extension_code = Column(String(50), nullable=True)  # "Extensão", "código", etc

    source_filename = Column(String(255), nullable=True)
    source_hash = Column(String(64), nullable=True)

    # vínculo com cliente (se encontrar)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    client_name_guess = Column(String(255), nullable=True)  # nome lido do PDF

    # flags de notificação automática
    notified_client_at = Column(DateTime, nullable=True)
    notified_team_at = Column(DateTime, nullable=True)

    notes = Column(Text, nullable=True)

    client = relationship("Client", lazy="joined")

    __table_args__ = (
        UniqueConstraint(
            "office_id",
            "process_number",
            "starts_at",
            name="uq_hearing_office_process_datetime",
        ),
    )