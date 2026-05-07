"""
app/models/migration.py
========================
Modelo atualizado com as 7 colunas novas que foram adicionadas no banco via ALTER TABLE.

Mudanças aplicadas:
1. Adicionadas as 7 colunas novas em MigrationBatch (status, arquivo_nome, etc.)
2. Default de 'status' corrigido para 'PENDENTE' (em vez de 'CONCLUIDO')
3. Constantes de status para evitar strings mágicas espalhadas pelo código
4. Índice composto em (office_id, criado_em) para acelerar a consulta de "lotes de hoje"
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
    Index,
    CheckConstraint,
)
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.datetime_utils import now_br


# ==========================================================
# ✅ Constantes de status (evitam strings mágicas no código)
# ==========================================================
class BatchStatus:
    PENDENTE = "PENDENTE"
    PROCESSANDO = "PROCESSANDO"
    CONCLUIDO = "CONCLUIDO"
    ERRO = "ERRO"

    ALL = (PENDENTE, PROCESSANDO, CONCLUIDO, ERRO)


class MigrationBatch(Base):
    __tablename__ = "migration_batches"

    id = Column(Integer, primary_key=True, index=True)

    # Vínculo com escritório
    office_id = Column(
        Integer,
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Período: 22/01/2026 até 25/01/2026
    periodo_inicio = Column(Date, nullable=True)
    periodo_fim = Column(Date, nullable=True)

    criado_em = Column(DateTime, default=now_br, nullable=False)

    # ==========================================================
    # ✅ NOVAS COLUNAS — agora mapeadas no ORM e USADAS pelo código
    # ==========================================================
    # Status do lote: PENDENTE → PROCESSANDO → CONCLUIDO ou ERRO
    status = Column(
        String(30),
        nullable=False,
        default=BatchStatus.PENDENTE,
        server_default=BatchStatus.PENDENTE,  # default do Postgres também
        index=True,
    )

    # Nome do arquivo enviado (para auditoria/suporte)
    arquivo_nome = Column(String(255), nullable=True)

    # Mensagem de erro completa, se status == 'ERRO'
    erro_processamento = Column(Text, nullable=True)

    # Timestamp de quando terminou (sucesso ou falha)
    processado_em = Column(DateTime, nullable=True)

    # Estatísticas do lote
    total_extraidos = Column(Integer, nullable=False, default=0, server_default="0")
    total_inseridos = Column(Integer, nullable=False, default=0, server_default="0")
    total_ignorados = Column(Integer, nullable=False, default=0, server_default="0")

    rows = relationship(
        "MigrationRow",
        back_populates="batch",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # Garante que o status só pode ser um dos valores válidos
        CheckConstraint(
            f"status IN {BatchStatus.ALL}",
            name="ck_migration_batches_status_valido",
        ),
        # Índice composto para acelerar consulta "lotes do escritório de hoje"
        Index("ix_migration_batches_office_criado", "office_id", "criado_em"),
    )


class MigrationRow(Base):
    __tablename__ = "migration_rows"

    id = Column(Integer, primary_key=True, index=True)

    # Vínculo com escritório
    office_id = Column(
        Integer,
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    batch_id = Column(
        Integer,
        ForeignKey("migration_batches.id", ondelete="CASCADE"),
        nullable=False,
    )

    batch = relationship("MigrationBatch", back_populates="rows")

    data_disponibilizacao = Column(Date, nullable=True, index=True)
    data_publicacao = Column(Date, nullable=True, index=True)

    # NÃO é UNIQUE globalmente
    numero_processo = Column(String, nullable=False, index=True)

    diario = Column(Text, nullable=True)

    # preenchido pelo usuário antes de enviar
    cliente = Column(String, nullable=True)
    vara_tramitacao = Column(String, nullable=True)
    observacao = Column(Text, nullable=True)
    rompe_em_dias = Column(Integer, nullable=True)

    enviar_para = Column(String, nullable=True)  # PRAZOS / PROCEDENTE / EXECUCAO

    enviado_em = Column(DateTime, nullable=True)
    enviado_para_status = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "office_id",
            "batch_id",
            "numero_processo",
            name="uq_migration_office_batch_numero_processo",
        ),
        # Índice composto para acelerar busca de pendentes do escritório
        Index(
            "ix_migration_rows_office_enviado",
            "office_id",
            "enviado_em",
        ),
    )
