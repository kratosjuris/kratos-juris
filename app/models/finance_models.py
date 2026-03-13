from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Date, DateTime, Float, Boolean, Text, UniqueConstraint
from app.core.database import Base


class FinanceMonth(Base):
    """
    Guarda o saldo inicial do mês (saldo em conta).
    O saldo "atual" é calculado em tela: saldo_inicial - soma_pagamentos_do_mes
    """
    __tablename__ = "finance_months"
    __table_args__ = (UniqueConstraint("ym", name="uq_finance_month_ym"),)

    id = Column(Integer, primary_key=True, index=True)
    ym = Column(String, nullable=False, index=True)  # "YYYY-MM"
    saldo_inicial = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)


class ExpenseTemplate(Base):
    """
    Modelos para facilitar lançamentos (fixas/variáveis).
    """
    __tablename__ = "expense_templates"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False, index=True)
    tipo = Column(String, nullable=False, default="FIXA")  # FIXA | VARIAVEL
    valor_padrao = Column(Float, nullable=False, default=0.0)
    observacao = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Payable(Base):
    __tablename__ = "payables"

    id = Column(Integer, primary_key=True, index=True)
    ym = Column(String, nullable=False, index=True)  # "YYYY-MM"

    descricao = Column(String, nullable=False)
    tipo = Column(String, nullable=False, default="FIXA")  # FIXA | VARIAVEL
    valor = Column(Float, nullable=False, default=0.0)
    vencimento = Column(Date, nullable=True)

    pago = Column(Boolean, nullable=False, default=False)
    pago_em = Column(Date, nullable=True)

    obs = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class Receivable(Base):
    __tablename__ = "receivables"

    id = Column(Integer, primary_key=True, index=True)
    ym = Column(String, nullable=False, index=True)  # "YYYY-MM"

    numero_processo = Column(String, nullable=False, index=True)
    parte_autora = Column(String, nullable=False)
    vara = Column(String, nullable=False)

    data_prevista = Column(Date, nullable=True)  # provável expedição alvará/pagamento

    conta = Column(String, nullable=False, default="CONTA_CSL")  # CONTA_CSL | CONTA_TARCISIO | CONTA_ANA | CONTA_TIAGO
    valor = Column(Float, nullable=False, default=0.0)

    recebido = Column(Boolean, nullable=False, default=False)
    recebido_em = Column(Date, nullable=True)

    obs = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
