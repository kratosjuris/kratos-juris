from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.tarefa import Tarefa, STATUS_ATIVOS


def get_tarefas_dashboard(db: Session, office_id: int, usuario_id: int, limite: int = 8):
    """Retorna (total_pendentes, lista_para_o_card) para o usuário logado,
    já filtrado pelo escritório."""

    query_base = db.query(Tarefa).filter(
        Tarefa.office_id == office_id,
        Tarefa.responsavel_id == usuario_id,
        Tarefa.status.in_(STATUS_ATIVOS),
    )

    total_pendentes = query_base.count()

    tarefas = (
        query_base
        .order_by(Tarefa.prazo.asc().nulls_last(), Tarefa.prioridade.desc())
        .limit(limite)
        .all()
    )

    tarefas_proximas = [
        {
            "id": t.id,
            "titulo": t.titulo,
            "processo_numero": t.processo.numero_processo if t.processo else None,
            "delegado_por": t.delegado_por.nome if t.delegado_por else None,
            "prazo": t.prazo,
            "prioridade": t.rotulo_prioridade(),
            "status": t.status_prazo(),  # 'atrasada' | 'hoje' | 'em_dia'
        }
        for t in tarefas
    ]

    return total_pendentes, tarefas_proximas


def get_tarefas_delegadas_por_mim(db: Session, office_id: int, usuario_id: int, limite: int = 8):
    """Opcional: tasks que o usuário delegou e ainda não foram concluídas/validadas."""

    query = db.query(Tarefa).filter(
        Tarefa.office_id == office_id,
        Tarefa.delegado_por_id == usuario_id,
        Tarefa.status.in_(STATUS_ATIVOS),
    ).order_by(Tarefa.prazo.asc().nulls_last())

    total = query.count()
    tarefas = query.limit(limite).all()

    itens = [
        {
            "id": t.id,
            "titulo": t.titulo,
            "responsavel": t.responsavel.nome if t.responsavel else None,
            "prazo": t.prazo,
            "status": t.status_prazo(),
        }
        for t in tarefas
    ]
    return total, itens