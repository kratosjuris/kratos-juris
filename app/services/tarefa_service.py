from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.tarefa import Tarefa, HistoricoStatusTarefa, ComentarioTarefa, AnexoTarefa


def criar_tarefa(
    db: Session,
    office_id: int,
    titulo: str,
    descricao: str | None,
    tipo: str,
    prioridade: str,
    prazo,
    processo_id: int | None,
    criado_por_id: int,
    responsavel_id: int | None = None,
) -> Tarefa:
    tem_delegacao = bool(responsavel_id) and responsavel_id != criado_por_id

    tarefa = Tarefa(
        office_id=office_id,
        titulo=titulo,
        descricao=descricao,
        tipo=tipo,
        prioridade=prioridade,
        prazo=prazo,
        processo_id=processo_id,
        criado_por_id=criado_por_id,
        responsavel_id=responsavel_id or criado_por_id,
        delegado_por_id=criado_por_id if tem_delegacao else None,
        status="pendente_aceite" if tem_delegacao else "em_execucao",
    )
    db.add(tarefa)
    db.commit()
    db.refresh(tarefa)
    return tarefa


def delegar_tarefa(db: Session, tarefa_id: int, office_id: int, novo_responsavel_id: int, delegado_por_id: int) -> Tarefa:
    tarefa = _get_tarefa_do_office(db, tarefa_id, office_id)

    tarefa.responsavel_id = novo_responsavel_id
    tarefa.delegado_por_id = delegado_por_id
    tarefa.status = "pendente_aceite"

    db.commit()
    db.refresh(tarefa)
    return tarefa


def responder_delegacao(db: Session, tarefa_id: int, office_id: int, usuario_id: int, aceitar: bool, justificativa: str | None = None) -> Tarefa:
    tarefa = _get_tarefa_do_office(db, tarefa_id, office_id)

    tarefa.status = "em_execucao" if aceitar else "recusada"
    db.commit()
    db.refresh(tarefa)
    return tarefa


def concluir_tarefa(db: Session, tarefa_id: int, office_id: int, usuario_id: int) -> Tarefa:
    tarefa = _get_tarefa_do_office(db, tarefa_id, office_id)

    tarefa.status = "concluida"
    db.commit()
    db.refresh(tarefa)
    return tarefa


def validar_tarefa(db: Session, tarefa_id: int, office_id: int, usuario_id: int, aprovado: bool, observacao: str | None = None) -> Tarefa:
    tarefa = _get_tarefa_do_office(db, tarefa_id, office_id)

    tarefa.status = "validada" if aprovado else "reprovada"
    db.commit()
    db.refresh(tarefa)
    return tarefa


def reabrir_para_execucao(db: Session, tarefa_id: int, office_id: int, usuario_id: int) -> Tarefa:
    tarefa = _get_tarefa_do_office(db, tarefa_id, office_id)
    tarefa.status = "em_execucao"
    db.commit()
    db.refresh(tarefa)
    return tarefa


def adicionar_comentario(db: Session, tarefa_id: int, office_id: int, autor_id: int, texto: str) -> ComentarioTarefa:
    tarefa = _get_tarefa_do_office(db, tarefa_id, office_id)

    comentario = ComentarioTarefa(tarefa_id=tarefa.id, autor_id=autor_id, texto=texto)
    db.add(comentario)
    db.commit()
    db.refresh(comentario)
    return comentario


def adicionar_anexo(db: Session, tarefa_id: int, office_id: int, enviado_por_id: int, nome_arquivo: str, caminho_arquivo: str) -> AnexoTarefa:
    tarefa = _get_tarefa_do_office(db, tarefa_id, office_id)
    anexo = AnexoTarefa(
        tarefa_id=tarefa.id, enviado_por_id=enviado_por_id,
        nome_arquivo=nome_arquivo, caminho_arquivo=caminho_arquivo,
    )
    db.add(anexo)
    db.commit()
    db.refresh(anexo)
    return anexo


def excluir_tarefa(db: Session, tarefa_id: int, office_id: int) -> None:
    tarefa = _get_tarefa_do_office(db, tarefa_id, office_id)
    db.delete(tarefa)
    db.commit()


def _get_tarefa_do_office(db: Session, tarefa_id: int, office_id: int) -> Tarefa:
    tarefa = (
        db.query(Tarefa)
        .filter(Tarefa.id == tarefa_id, Tarefa.office_id == office_id)
        .first()
    )
    if not tarefa:
        raise ValueError("Tarefa nao encontrada neste escritorio.")
    return tarefa