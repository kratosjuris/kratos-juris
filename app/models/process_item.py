from datetime import date

from sqlalchemy import Column, Integer, String, Date, DateTime, Text, ForeignKey

from app.core.database import Base
from app.core.datetime_utils import now_br


# abas: PROCEDENTE | EXECUCAO | PRAZOS
# cumprimento (para PRAZOS): PENDENTE | CUMPRIDO | ROMPIDO
# para PROCEDENTE: PENDENTE | TRANSITADO | RECURSO


class ProcessItem(Base):
    __tablename__ = "process_items"

    id = Column(Integer, primary_key=True, index=True)

    # 🔥 VÍNCULO COM ESCRITÓRIO
    office_id = Column(
        Integer,
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # identifica em qual aba o registro existe
    aba = Column(String, nullable=False, index=True)

    numero_processo = Column(String, nullable=False, index=True)
    parte_autora = Column(String, nullable=False)
    vara = Column(String, nullable=False)

    data_intimacao = Column(Date, nullable=True)   # DJEN
    prazo_dias = Column(Integer, nullable=True)

    # ✅ NOVO:
    # uteis   = regra padrão do processo civil
    # corridos = usado quando o prazo correr em dias corridos
    tipo_contagem = Column(String(20), nullable=False, default="uteis", index=True)

    vencimento = Column(Date, nullable=True)

    # observação livre
    obs = Column(Text, nullable=True)

    cumprimento = Column(String, nullable=False, default="PENDENTE")

    created_at = Column(DateTime, nullable=False, default=now_br)