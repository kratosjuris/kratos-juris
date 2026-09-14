"""
Job de verificação de prazos das tasks.

Registro sugerido no app/main.py, junto dos outros jobs (job_07h, job_12h,
job_monitorar_djen, _job_atualizar_indices):

    from app.services.jobs.verificar_prazos_tarefas_job import job_verificar_prazos_tarefas

    scheduler.add_job(
        job_verificar_prazos_tarefas,
        CronTrigger(hour=7, minute=10),
        id="job_verificar_prazos_tarefas",
        replace_existing=True,
    )

Roda com Session própria (SessionLocal), igual aos outros jobs do
BackgroundScheduler — não recebe `db` via Depends porque não está
dentro de uma requisição HTTP.
"""

from datetime import timedelta

from app.core.database import SessionLocal
from app.core.datetime_utils import now_br
from app.models.tarefa import Tarefa, STATUS_ATIVOS
from app.services import notificacao_service

DIAS_DE_ALERTA_ANTES_DO_PRAZO = (3, 1)


def job_verificar_prazos_tarefas():
    db = SessionLocal()
    try:
        _notificar_prazos_vencidos(db)
        _notificar_prazos_proximos(db)
    except Exception as e:
        print(f"[TAREFAS] erro ao verificar prazos: {e}")
    finally:
        db.close()


def _notificar_prazos_vencidos(db):
    hoje = now_br().date()
    vencidas = db.query(Tarefa).filter(
        Tarefa.prazo < hoje,
        Tarefa.status.in_(STATUS_ATIVOS),
    ).all()

    for tarefa in vencidas:
        if tarefa.responsavel_id:
            notificacao_service.criar_notificacao(
                db, usuario_id=tarefa.responsavel_id, tarefa_id=tarefa.id,
                tipo="prazo_vencido",
                mensagem=f"'{tarefa.titulo}' está com o prazo vencido",
            )
        if tarefa.delegado_por_id and tarefa.delegado_por_id != tarefa.responsavel_id:
            notificacao_service.criar_notificacao(
                db, usuario_id=tarefa.delegado_por_id, tarefa_id=tarefa.id,
                tipo="prazo_vencido",
                mensagem=f"'{tarefa.titulo}' está com o prazo vencido",
            )


def _notificar_prazos_proximos(db):
    hoje = now_br().date()
    for dias in DIAS_DE_ALERTA_ANTES_DO_PRAZO:
        data_alvo = hoje + timedelta(days=dias)
        proximas = db.query(Tarefa).filter(
            Tarefa.prazo == data_alvo,
            Tarefa.status.in_(STATUS_ATIVOS),
        ).all()

        for tarefa in proximas:
            if not tarefa.responsavel_id:
                continue
            notificacao_service.criar_notificacao(
                db, usuario_id=tarefa.responsavel_id, tarefa_id=tarefa.id,
                tipo="prazo_proximo",
                mensagem=f"'{tarefa.titulo}' vence em {dias} dia(s)",
            )