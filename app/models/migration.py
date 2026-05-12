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


class BatchStatus:
    PENDENTE = "PENDENTE"
    PROCESSANDO = "PROCESSANDO"
    CONCLUIDO = "CONCLUIDO"
    ERRO = "ERRO"

    ALL = (PENDENTE, PROCESSANDO, CONCLUIDO, ERRO)


class MigrationBatch(Base):
    __tablename__ = "migration_batches"

    id = Column(Integer, primary_key=True, index=True)

    office_id = Column(
        Integer,
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    periodo_inicio = Column(Date, nullable=True)
    periodo_fim = Column(Date, nullable=True)

    criado_em = Column(DateTime, nullable=False, default=now_br)

    status = Column(
        String(30),
        nullable=False,
        default=BatchStatus.PENDENTE,
        server_default=BatchStatus.PENDENTE,
        index=True,
    )

    arquivo_nome = Column(String(255), nullable=True)
    erro_processamento = Column(Text, nullable=True)
    processado_em = Column(DateTime, nullable=True)

    total_extraidos = Column(Integer, nullable=False, default=0, server_default="0")
    total_inseridos = Column(Integer, nullable=False, default=0, server_default="0")
    total_ignorados = Column(Integer, nullable=False, default=0, server_default="0")

    rows = relationship(
        "MigrationRow",
        back_populates="batch",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDENTE', 'PROCESSANDO', 'CONCLUIDO', 'ERRO')",
            name="ck_migration_batches_status_valido",
        ),
        Index("ix_migration_batches_office_criado", "office_id", "criado_em"),
    )


class MigrationRow(Base):
    __tablename__ = "migration_rows"

    id = Column(Integer, primary_key=True, index=True)

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
        index=True,
    )

    batch = relationship("MigrationBatch", back_populates="rows")

    data_disponibilizacao = Column(Date, nullable=True, index=True)
    data_publicacao = Column(Date, nullable=True, index=True)

    numero_processo = Column(String, nullable=False, index=True)

    diario = Column(Text, nullable=True)

    cliente = Column(String, nullable=True)
    vara_tramitacao = Column(String, nullable=True)
    observacao = Column(Text, nullable=True)
    rompe_em_dias = Column(Integer, nullable=True)

    # ✅ NOVO:
    # uteis   = regra padrão do processo civil
    # corridos = usado para criminal / demais prazos corridos
    tipo_contagem = Column(
        String(20),
        nullable=False,
        default="uteis",
        server_default="uteis",
        index=True,
    )

    enviar_para = Column(String, nullable=True)

    enviado_em = Column(DateTime, nullable=True)
    enviado_para_status = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "office_id",
            "batch_id",
            "numero_processo",
            name="uq_migration_office_batch_numero_processo",
        ),
        Index(
            "ix_migration_rows_office_enviado",
            "office_id",
            "enviado_em",
        ),
        Index(
            "ix_migration_rows_office_batch",
            "office_id",
            "batch_id",
        ),

        # ✅ NOVO
        Index(
            "ix_migration_rows_tipo_contagem",
            "tipo_contagem",
        ),
    )