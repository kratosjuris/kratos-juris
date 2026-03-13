# app/models/client.py
from sqlalchemy import Column, Integer, String, Date, DateTime, func
from app.core.database import Base


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)

    # ===== DADOS PRINCIPAIS =====
    nome = Column(String, nullable=False, index=True)
    cpf_cnpj = Column(String, nullable=True, index=True)

    # ===== NOVOS CAMPOS (CADASTRO COMPLETO) =====
    rg = Column(String, nullable=True, index=True)
    ssp_uf = Column(String, nullable=True)          # Ex.: SSP/BA
    estado_civil = Column(String, nullable=True)    # Ex.: Solteiro(a)
    profissao = Column(String, nullable=True)

    # ===== CONTATO =====
    telefone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    endereco = Column(String, nullable=True)

    # ===== OUTROS =====
    nascimento = Column(Date, nullable=True)
    obs = Column(String, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
