from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Date, DateTime, Text
from app.core.database import Base

# abas: PROCEDENTE | EXECUCAO | PRAZOS
# cumprimento (para PRAZOS): PENDENTE | CUMPRIDO | ROMPIDO
# para PROCEDENTE: PENDENTE | TRANSITADO | RECURSO

class ProcessItem(Base):
    __tablename__ = "process_items"

    id = Column(Integer, primary_key=True, index=True)

    # identifica em qual aba o registro existe
    aba = Column(String, nullable=False, index=True)

    numero_processo = Column(String, nullable=False, index=True)
    parte_autora = Column(String, nullable=False)
    vara = Column(String, nullable=False)

    data_intimacao = Column(Date, nullable=True)   # DJEN
    prazo_dias = Column(Integer, nullable=True)
    vencimento = Column(Date, nullable=True)

    # >>> NOVO: observação livre (o que precisa fazer no processo)
    obs = Column(Text, nullable=True)

    cumprimento = Column(String, nullable=False, default="PENDENTE")
    created_at = Column(DateTime, default=datetime.utcnow)
