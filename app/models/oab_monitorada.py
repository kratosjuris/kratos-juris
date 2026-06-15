"""
app/models/oab_monitorada.py

Cadastro das OABs monitoradas por escritório.
O job diário lê esta tabela e dispara a consulta DJEN + enriquecimento
DataJud automaticamente para cada OAB ativa, sem intervenção manual.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
    Index,
)

from app.core.database import Base
from app.core.datetime_utils import now_br


class OabMonitorada(Base):
    __tablename__ = "oab_monitoradas"

    id = Column(Integer, primary_key=True, index=True)

    office_id = Column(
        Integer,
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Ex: "123456"
    numero_oab = Column(String(30), nullable=False)

    # Ex: "BA", "SP", "RJ"
    uf_oab = Column(String(2), nullable=False)

    # Nome do advogado para identificação na tela
    nome_advogado = Column(String(255), nullable=True)

    # Se False, o job ignora esta OAB
    ativa = Column(Boolean, nullable=False, default=True, server_default="1")

    # Controle do último monitoramento
    ultimo_monitoramento_em = Column(DateTime, nullable=True)
    ultimo_monitoramento_status = Column(String(20), nullable=True)   # OK | ERRO | VAZIO
    ultimo_monitoramento_resumo = Column(Text, nullable=True)         # "8 intimações encontradas"

    criado_em = Column(DateTime, nullable=False, default=now_br)
    atualizado_em = Column(DateTime, nullable=True)

    __table_args__ = (
        # Cada escritório só pode ter uma OAB cadastrada uma vez
        UniqueConstraint(
            "office_id",
            "numero_oab",
            "uf_oab",
            name="uq_oab_monitorada_office_numero_uf",
        ),
        Index("ix_oab_monitoradas_office_ativa", "office_id", "ativa"),
    )

    def __repr__(self) -> str:
        return (
            f"<OabMonitorada id={self.id} "
            f"oab={self.numero_oab}/{self.uf_oab} "
            f"office={self.office_id} "
            f"ativa={self.ativa}>"
        )