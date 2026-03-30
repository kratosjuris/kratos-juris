from datetime import date, timedelta, datetime
import urllib.parse

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import extract, func

from app.core.database import get_db
from app.models.client import Client
from app.models.pericia_models import PericiaDiligencia
from app.models.process_item import ProcessItem
from app.models.finance_models import Payable
from app.models.hearing import Hearing

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _get_office_id(request: Request) -> int:
    office_id = request.session.get("office_id")
    if not office_id:
        raise HTTPException(status_code=403, detail="Usuário sem escritório vinculado.")
    return int(office_id)


def _with_office_filter(query, model, office_id: int):
    """
    Aplica filtro por escritório somente se o model possuir office_id.
    Evita quebrar o dashboard enquanto nem todas as tabelas foram adaptadas.
    """
    if hasattr(model, "office_id"):
        return query.filter(model.office_id == office_id)
    return query


def _normalize_phone_br(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        return None
    if digits.startswith("55"):
        return digits
    return "55" + digits


def _money_br(value) -> str:
    try:
        v = float(value or 0)
    except Exception:
        v = 0.0
    s = f"{v:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


templates.env.filters["money_br"] = _money_br


ABA_LABEL_BY_STATUS = {
    "PRAZOS": "Controle de Prazos",
    "PROCEDENTE": "Ações Procedentes",
    "EXECUCAO": "Ações em Execução",
}


def _aba_values_for_filter(aba_norm: str) -> list[str]:
    label = ABA_LABEL_BY_STATUS.get(aba_norm)
    if label:
        return [aba_norm, label]
    return [aba_norm]


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


def _dashboard_audiencias_dates(hoje: date) -> list[date]:
    return [hoje, _next_business_day(hoje)]


def _advogados_audiencias_date(hoje: date) -> date:
    return _next_business_day(hoje)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)

    hoje = date.today()
    agora = datetime.now()

    clientes_total = (
        _with_office_filter(db.query(func.count(Client.id)), Client, office_id)
        .scalar()
        or 0
    )

    bday_mes_total = (
        _with_office_filter(db.query(func.count(Client.id)), Client, office_id)
        .filter(Client.nascimento.is_not(None))
        .filter(extract("month", Client.nascimento) == hoje.month)
        .scalar()
        or 0
    )

    clientes_hoje = (
        _with_office_filter(db.query(Client), Client, office_id)
        .filter(Client.nascimento.is_not(None))
        .filter(extract("month", Client.nascimento) == hoje.month)
        .filter(extract("day", Client.nascimento) == hoje.day)
        .order_by(Client.nome.asc())
        .all()
    )

    bday_itens = []
    for c in clientes_hoje:
        fone = _normalize_phone_br(c.telefone)

        msg = (
            f"Olá, {c.nome}! 🎉\n\n"
            f"A equipe do Escritório Clementino & Silva Lopes "
            f"lhe deseja um Feliz Aniversário!\n\n"
            f"Que este novo ano de vida seja repleto de saúde, conquistas e tranquilidade. "
            f"Reafirmamos nosso compromisso de estarmos sempre à sua disposição, "
            f"lado a lado, para auxiliá-lo(a) em todas as demandas jurídicas que se fizerem necessárias.\n\n"
            f"Conte sempre conosco.\n"
            f"Atenciosamente,\n"
            f"Escritório Clementino & Silva Lopes"
        )

        wa = None
        if fone:
            wa = f"https://wa.me/{fone}?text={urllib.parse.quote(msg)}"

        bday_itens.append({"c": c, "wa": wa})

    limite_pericias = hoje + timedelta(days=7)
    pericias_proximas = (
        _with_office_filter(db.query(PericiaDiligencia), PericiaDiligencia, office_id)
        .filter(PericiaDiligencia.concluido.is_(False))
        .filter(PericiaDiligencia.data_evento.is_not(None))
        .filter(PericiaDiligencia.data_evento >= hoje)
        .filter(PericiaDiligencia.data_evento <= limite_pericias)
        .order_by(PericiaDiligencia.data_evento.asc())
        .all()
    )

    fim_semana = _fim_da_semana(hoje)
    prazos_values = _aba_values_for_filter("PRAZOS")

    prazos_rompendo_semana_total = (
        _with_office_filter(db.query(func.count(ProcessItem.id)), ProcessItem, office_id)
        .filter(ProcessItem.aba.in_(prazos_values))
        .filter(ProcessItem.cumprimento != "CUMPRIDO")
        .filter(ProcessItem.vencimento.isnot(None))
        .filter(ProcessItem.vencimento >= hoje)
        .filter(ProcessItem.vencimento <= fim_semana)
        .scalar()
        or 0
    )

    payables_alert = (
        _with_office_filter(db.query(Payable), Payable, office_id)
        .filter(Payable.pago.is_(False))
        .filter(Payable.vencimento.isnot(None))
        .filter(Payable.vencimento <= hoje)
        .order_by(Payable.vencimento.asc(), Payable.valor.desc(), Payable.id.asc())
        .all()
    )

    payables_alert_itens = []
    for p in payables_alert:
        dias_atraso = 0
        badge = "Hoje"
        if p.vencimento and p.vencimento < hoje:
            dias_atraso = (hoje - p.vencimento).days
            badge = "Atrasada"
        payables_alert_itens.append({"p": p, "badge": badge, "dias_atraso": dias_atraso})

    next_day = _next_business_day(hoje)
    datas_dashboard = _dashboard_audiencias_dates(hoje)

    audiencias = (
        _with_office_filter(db.query(Hearing), Hearing, office_id)
        .filter(func.date(Hearing.starts_at).in_(datas_dashboard))
        .order_by(Hearing.starts_at.asc(), Hearing.id.asc())
        .all()
    )

    audiencias_hoje = []
    audiencias_proximo = []

    for h in audiencias:
        if not h.starts_at:
            continue

        d = h.starts_at.date()

        if d == hoje and h.starts_at < agora:
            continue

        if d == hoje:
            audiencias_hoje.append(h)
        elif d == next_day:
            audiencias_proximo.append(h)

    audiencias_dashboard = audiencias_hoje + audiencias_proximo
    adv_target_day = _advogados_audiencias_date(hoje)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "Painel Principal",
            "hoje": hoje,
            "next_day": next_day,
            "datas_dashboard": datas_dashboard,
            "adv_target_day": adv_target_day,
            "bday_itens": bday_itens,
            "pericias_proximas": pericias_proximas,
            "payables_alert_itens": payables_alert_itens,
            "audiencias_hoje": audiencias_hoje,
            "audiencias_proximo": audiencias_proximo,
            "audiencias_dashboard": audiencias_dashboard,
            "bday_mes_total": bday_mes_total,
            "clientes_total": clientes_total,
            "prazos_rompendo_semana_total": prazos_rompendo_semana_total,
        },
    )