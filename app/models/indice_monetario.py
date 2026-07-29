# app/models/indice_monetario.py
from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, Numeric, String
from app.core.database import Base
from app.core.datetime_utils import now_br


class IndiceMonetario(Base):
    """
    Armazena os índices mensais de correção monetária e juros
    obtidos da API do Banco Central (BCB/SGS).

    Persiste entre deploys no PostgreSQL — substitui o cache em disco
    que se perde a cada reinicialização do Render.
    """

    __tablename__ = "indices_monetarios"

    id = Column(Integer, primary_key=True, index=True)

    # "ipca" | "inpc" | "taxa_legal"
    serie = Column(String(20), nullable=False, index=True)

    # Formato "YYYY-MM" — ex: "2024-08"
    periodo = Column(String(7), nullable=False, index=True)

    # Variação percentual mensal — ex: 0.44 (representa 0,44%)
    valor = Column(Numeric(precision=12, scale=6), nullable=False)

    atualizado_em = Column(
        DateTime(timezone=True),
        nullable=False,
        default=now_br,
        onupdate=now_br,
    )

    def __repr__(self) -> str:
        return f"<IndiceMonetario serie={self.serie} periodo={self.periodo} valor={self.valor}>"