from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, DateTime, Boolean, Text, ForeignKey
from app.core.database import Base


class PericiaDiligencia(Base):
    __tablename__ = "pericias_diligencias"

    id = Column(Integer, primary_key=True, index=True)

    # vínculo com escritório
    office_id = Column(
        Integer,
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    numero_processo = Column(String, nullable=False, index=True)
    nome_parte = Column(String, nullable=False, index=True)

    observacao = Column(Text, nullable=True)
    local = Column(String, nullable=True)

    data_evento = Column(Date, nullable=False, index=True)

    concluido = Column(Boolean, nullable=False, default=False)
    concluido_em = Column(Date, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)