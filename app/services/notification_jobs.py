from __future__ import annotations

"""
Jobs de notificação do Kratos Juris.

CRONOGRAMA (timezone America/Sao_Paulo):

  07:00  -> audiências do DIA
         -> aniversariantes do dia
         -> prazos rompendo na SEMANA (contagem)
         -> perícias/diligências da SEMANA + as do DIA

  12:00  -> audiências do DIA
         -> aniversariantes do dia

  20:00  -> audiências do DIA SEGUINTE
         -> aniversariantes do dia

As consultas abaixo usam EXATAMENTE a mesma regra do web_dashboard.py.
Nada do sistema é alterado: aqui apenas LEMOS os dados e enviamos push.
As notificações vão para todos os usuários inscritos de cada escritório.
"""

from datetime import date, datetime, timedelta

from app.core.database import SessionLocal
from app.core.datetime_utils import now_br

from app.models.client import Client
from app.models.hearing import Hearing
from app.models.pericia_models import PericiaDiligencia
from app.models.process_item import ProcessItem
from app.models.push_subscription import PushSubscription

from app.services.push_service import send_push_to_office


# =========================================================
# URLs DE DESTINO (ajuste se as rotas reais forem outras)
# =========================================================
URL_DASHBOARD = "/dashboard"
URL_AUDIENCIAS = "/dashboard"
URL_ANIVERSARIOS = "/dashboard"
URL_PRAZOS = "/dashboard"
URL_PERICIAS = "/dashboard"


# =========================================================
# HELPERS DE DATA (iguais aos do dashboard)
# =========================================================
def _hoje() -> date:
    return now_br().date()


def _to_naive_datetime(dt):
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        return dt.replace(tzinfo=None)
    return dt


def _fim_da_semana(d: date) -> date:
    return d + timedelta(days=(6 - d.weekday()))


def _next_business_day(d: date) -> date:
    wd = d.weekday()
    if wd == 4:
        return d + timedelta(days=3)
    if wd == 5:
        return d + timedelta(days=2)
    if wd == 6:
        return d + timedelta(days=1)
    return d + timedelta(days=1)


def _txt(obj, *attrs) -> str:
    """Retorna o primeiro atributo que for uma string não vazia."""
    for a in attrs:
        v = getattr(obj, a, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


# =========================================================
# ESCRITÓRIOS QUE TÊM INSCRIÇÕES (só processa quem recebe)
# =========================================================
def _offices_com_inscricao(db) -> list[int]:
    rows = (
        db.query(PushSubscription.office_id)
        .filter(PushSubscription.office_id.isnot(None))
        .distinct()
        .all()
    )
    return [r[0] for r in rows if r[0] is not None]


# =========================================================
# CONSULTAS (regra idêntica ao dashboard)
# =========================================================
def _audiencias_do_dia(db, office_id, dia, pular_passadas):
    inicio = datetime.combine(dia, datetime.min.time())
    fim = datetime.combine(dia + timedelta(days=1), datetime.min.time())

    audiencias = (
        db.query(Hearing)
        .filter(
            Hearing.office_id == office_id,
            Hearing.starts_at >= inicio,
            Hearing.starts_at < fim,
        )
        .order_by(Hearing.starts_at.asc())
        .all()
    )

    agora_cmp = _to_naive_datetime(now_br())
    out = []
    for h in audiencias:
        if not h.starts_at:
            continue
        s = _to_naive_datetime(h.starts_at)
        if not s:
            continue
        if pular_passadas and agora_cmp and s < agora_cmp:
            continue
        out.append((s, h))
    return out


def _prazos_semana_total(db, office_id, dia):
    from sqlalchemy import func
    fim_semana = _fim_da_semana(dia)
    return (
        db.query(func.count(ProcessItem.id))
        .filter(
            ProcessItem.office_id == office_id,
            ProcessItem.aba.in_(["PRAZOS", "Controle de Prazos"]),
            ProcessItem.cumprimento != "CUMPRIDO",
            ProcessItem.vencimento.isnot(None),
            ProcessItem.vencimento >= dia,
            ProcessItem.vencimento <= fim_semana,
        )
        .scalar() or 0
    )


def _pericias_semana(db, office_id, dia):
    limite = dia + timedelta(days=7)
    return (
        db.query(PericiaDiligencia)
        .filter(
            PericiaDiligencia.office_id == office_id,
            PericiaDiligencia.concluido.is_(False),
            PericiaDiligencia.data_evento.is_not(None),
            PericiaDiligencia.data_evento >= dia,
            PericiaDiligencia.data_evento <= limite,
        )
        .order_by(PericiaDiligencia.data_evento.asc())
        .all()
    )


def _pericias_do_dia(db, office_id, dia):
    return (
        db.query(PericiaDiligencia)
        .filter(
            PericiaDiligencia.office_id == office_id,
            PericiaDiligencia.concluido.is_(False),
            PericiaDiligencia.data_evento == dia,
        )
        .order_by(PericiaDiligencia.data_evento.asc())
        .all()
    )


# =========================================================
# MONTAGEM DE TEXTO
# =========================================================
def _fmt_audiencia(s_dt, h) -> str:
    hora = s_dt.strftime("%H:%M") if s_dt else ""
    desc = _txt(h, "promovido", "cliente_nome", "parte", "titulo", "descricao", "assunto")
    return f"{hora} – {desc}".strip(" –") if (hora or desc) else "audiência"


def _fmt_pericia(p) -> str:
    d = getattr(p, "data_evento", None)
    data = d.strftime("%d/%m") if d else ""
    desc = _txt(p, "titulo", "descricao", "tipo", "cliente_nome", "parte", "nome")
    return f"{data} – {desc}".strip(" –") if (data or desc) else "perícia/diligência"


# =========================================================
# ENVIO POR ESCRITÓRIO
# =========================================================
def _send(office_id, title, body, url, tag):
    if not body:
        return 0
    return send_push_to_office(
        office_id,
        {"title": title, "body": body, "url": url, "tag": tag},
    )


def _notif_audiencias(db, office_id, dia, rotulo, pular_passadas):
    itens = _audiencias_do_dia(db, office_id, dia, pular_passadas)
    if not itens:
        return
    n = len(itens)
    linhas = [_fmt_audiencia(s, h) for s, h in itens[:3]]
    extra = f" (+{n - 3})" if n > 3 else ""
    body = f"{n} audiência(s) {rotulo}: " + "; ".join(linhas) + extra
    _send(office_id, "📅 Audiências", body, URL_AUDIENCIAS, f"audiencias-{rotulo}")


def _notif_aniversariantes(db, office_id, dia):
    # filtro por mês/dia feito aqui para reaproveitar a query base
    from sqlalchemy import extract
    clientes = (
        db.query(Client)
        .filter(
            Client.office_id == office_id,
            Client.nascimento.is_not(None),
            extract("month", Client.nascimento) == dia.month,
            extract("day", Client.nascimento) == dia.day,
        )
        .order_by(Client.nome.asc())
        .all()
    )
    if not clientes:
        return
    nomes = [
        (_txt(c, "nome", "name") or "Cliente") for c in clientes[:6]
    ]
    n = len(clientes)
    extra = f" e mais {n - 6}" if n > 6 else ""
    body = f"{n} cliente(s) fazem aniversário hoje: " + ", ".join(nomes) + extra
    _send(office_id, "🎂 Aniversariantes", body, URL_ANIVERSARIOS, "aniversarios")


def _notif_prazos(db, office_id, dia):
    n = _prazos_semana_total(db, office_id, dia)
    if not n:
        return
    body = f"{n} processo(s) com prazo rompendo nesta semana."
    _send(office_id, "⚠️ Controle de Prazos", body, URL_PRAZOS, "prazos-semana")


def _notif_pericias(db, office_id, dia):
    # da semana (contagem + próximas)
    semana = _pericias_semana(db, office_id, dia)
    if semana:
        n = len(semana)
        linhas = [_fmt_pericia(p) for p in semana[:3]]
        extra = f" (+{n - 3})" if n > 3 else ""
        body = f"{n} perícia(s)/diligência(s) nos próximos 7 dias: " + "; ".join(linhas) + extra
        _send(office_id, "🔬 Perícias & Diligências", body, URL_PERICIAS, "pericias-semana")

    # as de hoje (lembrete do dia)
    dia_itens = _pericias_do_dia(db, office_id, dia)
    if dia_itens:
        linhas = [_fmt_pericia(p) for p in dia_itens[:3]]
        body = "Hoje: " + "; ".join(linhas)
        _send(office_id, "🔬 Perícia/diligência HOJE", body, URL_PERICIAS, "pericias-dia")


# =========================================================
# JOBS POR HORÁRIO (chamados pelo agendador no main.py)
# =========================================================
def job_07h():
    print("[JOBS] iniciando rotina das 07h")
    db = SessionLocal()
    try:
        hoje = _hoje()
        for office_id in _offices_com_inscricao(db):
            _notif_audiencias(db, office_id, hoje, "hoje", pular_passadas=True)
            _notif_aniversariantes(db, office_id, hoje)
            _notif_prazos(db, office_id, hoje)
            _notif_pericias(db, office_id, hoje)
        print("[JOBS] 07h concluída")
    except Exception as e:
        print(f"[JOBS] erro na rotina das 07h: {e}")
    finally:
        db.close()


def job_12h():
    print("[JOBS] iniciando rotina das 12h")
    db = SessionLocal()
    try:
        hoje = _hoje()
        for office_id in _offices_com_inscricao(db):
            _notif_audiencias(db, office_id, hoje, "hoje", pular_passadas=True)
            _notif_aniversariantes(db, office_id, hoje)
        print("[JOBS] 12h concluída")
    except Exception as e:
        print(f"[JOBS] erro na rotina das 12h: {e}")
    finally:
        db.close()


def job_20h():
    print("[JOBS] iniciando rotina das 20h")
    db = SessionLocal()
    try:
        hoje = _hoje()
        amanha = hoje + timedelta(days=1)
        for office_id in _offices_com_inscricao(db):
            _notif_audiencias(db, office_id, amanha, "amanhã", pular_passadas=False)
            _notif_aniversariantes(db, office_id, hoje)
        print("[JOBS] 20h concluída")
    except Exception as e:
        print(f"[JOBS] erro na rotina das 20h: {e}")
    finally:
        db.close()