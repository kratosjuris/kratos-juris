from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class MigrationBatch(Base):
    __tablename__ = "migration_batches"

    id = Column(Integer, primary_key=True, index=True)

    # Período: 22/01/2026 até 25/01/2026
    periodo_inicio = Column(Date, nullable=True)
    periodo_fim = Column(Date, nullable=True)

    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    rows = relationship("MigrationRow", back_populates="batch")


class MigrationRow(Base):
    __tablename__ = "migration_rows"

    id = Column(Integer, primary_key=True, index=True)

    batch_id = Column(Integer, ForeignKey("migration_batches.id"), nullable=False)
    batch = relationship("MigrationBatch", back_populates="rows")

    data_disponibilizacao = Column(Date, nullable=True, index=True)
    data_publicacao = Column(Date, nullable=True, index=True)

    # ✅ NÃO pode ser UNIQUE globalmente, pois o mesmo processo pode aparecer em outros dias/lotes.
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

    # ✅ ÚNICO APENAS DENTRO DO MESMO LOTE (batch)
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "numero_processo",
            name="uq_migration_batch_numero_processo",
        ),
    )
