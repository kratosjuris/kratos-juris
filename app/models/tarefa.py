from __future__ import annotations

from sqlalchemy import Column, Integer, String, Date, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.datetime_utils import now_br


# status: pendente_aceite | em_execucao | concluida | validada | reprovada | recusada
# prioridade: baixa | media | alta | urgente
# tipo: juridica | administrativa

STATUS_ATIVOS = ["pendente_aceite", "em_execucao", "reprovada"]

STATUS_LABELS = {
    "pendente_aceite": "Aguardando aceite",
    "em_execucao": "Em execução",
    "concluida": "Concluída",
    "validada": "Validada",
    "reprovada": "Reprovada",
    "recusada": "Recusada",
}

PRIORIDADE_LABELS = {
    "baixa": "Baixa",
    "media": "Média",
    "alta": "Alta",
    "urgente": "Urgente",
}


class Tarefa(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)

    # 🔥 vínculo com escritório — mesmo padrão do ProcessItem
    office_id = Column(
        Integer,
        ForeignKey("offices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    titulo = Column(String(255), nullable=False)
    descricao = Column(Text, nullable=True)
    tipo = Column(String(20), nullable=False, default="juridica", index=True)

    status = Column(String(30), nullable=False, default="pendente_aceite", index=True)
    prioridade = Column(String(20), nullable=False, default="media", index=True)
    prazo = Column(Date, nullable=True, index=True)

    processo_id = Column(
        Integer,
        ForeignKey("process_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    processo = relationship("ProcessItem", lazy="joined")

    criado_por_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    criado_por = relationship("User", foreign_keys=[criado_por_id], lazy="joined")

    # responsável atual (quem está executando agora)
    responsavel_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    responsavel = relationship("User", foreign_keys=[responsavel_id], lazy="joined")

    # quem delegou por último — delegação livre: qualquer usuário -> qualquer usuário
    delegado_por_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    delegado_por = relationship("User", foreign_keys=[delegado_por_id], lazy="joined")

    created_at = Column(DateTime, nullable=False, default=now_br)
    updated_at = Column(DateTime, nullable=False, default=now_br, onupdate=now_br)

    historico = relationship(
        "HistoricoStatusTarefa",
        back_populates="tarefa",
        cascade="all, delete-orphan",
        order_by="HistoricoStatusTarefa.alterado_em.desc()",
    )
    comentarios = relationship(
        "ComentarioTarefa",
        back_populates="tarefa",
        cascade="all, delete-orphan",
        order_by="ComentarioTarefa.criado_em.asc()",
    )
    anexos = relationship(
        "AnexoTarefa",
        back_populates="tarefa",
        cascade="all, delete-orphan",
        order_by="AnexoTarefa.enviado_em.desc()",
    )

    # ---- helpers de apresentação / regra de negócio ----

    def esta_atrasada(self) -> bool:
        if not self.prazo:
            return False
        return self.prazo < now_br().date() and self.status not in ("concluida", "validada")

    def vence_hoje(self) -> bool:
        return self.prazo == now_br().date() if self.prazo else False

    def status_prazo(self) -> str:
        """'atrasada' | 'hoje' | 'em_dia' — usado nos badges dos templates."""
        if self.esta_atrasada():
            return "atrasada"
        if self.vence_hoje():
            return "hoje"
        return "em_dia"

    def rotulo_status(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    def rotulo_prioridade(self) -> str:
        return PRIORIDADE_LABELS.get(self.prioridade, self.prioridade)

    def __repr__(self) -> str:
        return f"<Tarefa id={self.id} titulo='{self.titulo}' status={self.status}>"


class HistoricoStatusTarefa(Base):
    __tablename__ = "tarefas_historico"

    id = Column(Integer, primary_key=True, index=True)
    tarefa_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    tarefa = relationship("Tarefa", back_populates="historico")

    status_anterior = Column(String(30), nullable=True)
    status_novo = Column(String(30), nullable=False)

    alterado_por_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    alterado_por = relationship("User", lazy="joined")

    alterado_em = Column(DateTime, nullable=False, default=now_br)
    observacao = Column(Text, nullable=True)


class ComentarioTarefa(Base):
    __tablename__ = "tarefas_comentarios"

    id = Column(Integer, primary_key=True, index=True)
    tarefa_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    tarefa = relationship("Tarefa", back_populates="comentarios")

    autor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    autor = relationship("User", lazy="joined")

    texto = Column(Text, nullable=False)
    criado_em = Column(DateTime, nullable=False, default=now_br)


class AnexoTarefa(Base):
    __tablename__ = "tarefas_anexos"

    id = Column(Integer, primary_key=True, index=True)
    tarefa_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    tarefa = relationship("Tarefa", back_populates="anexos")

    enviado_por_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    enviado_por = relationship("User", lazy="joined")

    nome_arquivo = Column(String(255), nullable=False)
    caminho_arquivo = Column(String(500), nullable=False)
    enviado_em = Column(DateTime, nullable=False, default=now_br)


class Notificacao(Base):
    __tablename__ = "notificacoes"

    id = Column(Integer, primary_key=True, index=True)

    usuario_destinatario_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    usuario_destinatario = relationship(
        "User", foreign_keys=[usuario_destinatario_id], lazy="joined"
    )

    tarefa_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True)
    tarefa = relationship("Tarefa", lazy="joined")

    ator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    ator = relationship("User", foreign_keys=[ator_id], lazy="joined")

    tipo = Column(String(30), nullable=False)
    mensagem = Column(String(500), nullable=False)
    lida = Column(Boolean, nullable=False, default=False, index=True)
    criado_em = Column(DateTime, nullable=False, default=now_br)