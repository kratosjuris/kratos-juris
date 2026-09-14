from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.tarefa import Notificacao


def criar_notificacao(db: Session, usuario_id: int, tipo: str, mensagem: str, tarefa_id: int | None = None, ator_id: int | None = None) -> Notificacao:
    notificacao = Notificacao(
        usuario_destinatario_id=usuario_id,
        tarefa_id=tarefa_id,
        ator_id=ator_id,
        tipo=tipo,
        mensagem=mensagem,
    )
    db.add(notificacao)
    db.commit()
    db.refresh(notificacao)
    return notificacao


def listar_notificacoes(db: Session, usuario_id: int, apenas_nao_lidas: bool = False, limite: int = 20):
    query = db.query(Notificacao).filter(Notificacao.usuario_destinatario_id == usuario_id)
    if apenas_nao_lidas:
        query = query.filter(Notificacao.lida.is_(False))
    return query.order_by(Notificacao.criado_em.desc()).limit(limite).all()


def contar_nao_lidas(db: Session, usuario_id: int) -> int:
    return (
        db.query(Notificacao)
        .filter(Notificacao.usuario_destinatario_id == usuario_id, Notificacao.lida.is_(False))
        .count()
    )


def marcar_como_lida(db: Session, notificacao_id: int, usuario_id: int) -> Notificacao | None:
    notificacao = (
        db.query(Notificacao)
        .filter(Notificacao.id == notificacao_id, Notificacao.usuario_destinatario_id == usuario_id)
        .first()
    )
    if not notificacao:
        return None
    notificacao.lida = True
    db.commit()
    db.refresh(notificacao)
    return notificacao


def marcar_todas_como_lidas(db: Session, usuario_id: int) -> None:
    (
        db.query(Notificacao)
        .filter(Notificacao.usuario_destinatario_id == usuario_id, Notificacao.lida.is_(False))
        .update({"lida": True})
    )
    db.commit()