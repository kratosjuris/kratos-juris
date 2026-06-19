"""
app/models/oab_monitorada.py

Cadastro das OABs monitoradas + tarefas de monitoramento pendentes
para execução pelo browser do advogado no login.
"""

from sqlalchemy import (
    Column, Integer, String, Boolean, Date, DateTime, Text,
    ForeignKey, UniqueConstraint, Index,
)
from app.core.database import Base
from app.core.datetime_utils import now_br


class OabMonitorada(Base):
    __tablename__ = "oab_monitoradas"

    id            = Column(Integer, primary_key=True, index=True)
    office_id     = Column(Integer, ForeignKey("offices.id", ondelete="CASCADE"), nullable=False, index=True)
    numero_oab    = Column(String(30), nullable=False)
    uf_oab        = Column(String(2),  nullable=False)
    nome_advogado = Column(String(255), nullable=True)
    ativa         = Column(Boolean, nullable=False, default=True, server_default="1")

    ultimo_monitoramento_em     = Column(DateTime, nullable=True)
    ultimo_monitoramento_status = Column(String(20), nullable=True)
    ultimo_monitoramento_resumo = Column(Text, nullable=True)

    criado_em    = Column(DateTime, nullable=False, default=now_br)
    atualizado_em = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("office_id", "numero_oab", "uf_oab",
                         name="uq_oab_monitorada_office_numero_uf"),
        Index("ix_oab_monitoradas_office_ativa", "office_id", "ativa"),
    )

    def __repr__(self):
        return f"<OabMonitorada id={self.id} oab={self.numero_oab}/{self.uf_oab} office={self.office_id}>"


class MonitorTarefa(Base):
    """
    Tarefa criada pelo job das 7h15.
    Fica PENDENTE até o advogado fazer login —
    o browser executa a consulta DJEN automaticamente e
    marca como CONCLUIDA, exibindo o resumo na tela.
    """
    __tablename__ = "monitor_tarefas"

    id        = Column(Integer, primary_key=True, index=True)
    office_id = Column(Integer, ForeignKey("offices.id", ondelete="CASCADE"), nullable=False, index=True)
    oab_id    = Column(Integer, ForeignKey("oab_monitoradas.id", ondelete="CASCADE"), nullable=False, index=True)

    numero_oab = Column(String(30), nullable=False)
    uf_oab     = Column(String(2),  nullable=False)

    # Período que o browser deve consultar no DJEN
    data_inicio = Column(Date, nullable=False)
    data_fim    = Column(Date, nullable=False)

    # PENDENTE → CONCLUIDA | ERRO
    status = Column(String(20), nullable=False, default="PENDENTE", server_default="PENDENTE", index=True)

    # Preenchido pelo browser após execução
    resultado_inseridos = Column(Integer, nullable=True)
    resultado_ignorados = Column(Integer, nullable=True)
    resultado_extraidos = Column(Integer, nullable=True)
    resultado_erro      = Column(Text, nullable=True)

    criado_em    = Column(DateTime, nullable=False, default=now_br)
    executado_em = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_monitor_tarefas_office_status", "office_id", "status"),
        Index("ix_monitor_tarefas_criado", "criado_em"),
    )