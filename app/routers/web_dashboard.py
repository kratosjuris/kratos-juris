from datetime import date, timedelta, datetime

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
from app.models.user import User
from app.services.whatsapp import build_message_by_tipo, build_wa_me_link

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# =========================
# 🔐 OFFICE
# =========================
def _get_office_id(request: Request) -> int:
    office_id = request.session.get("office_id")
    if not office_id:
        raise HTTPException(status_code=403, detail="Usuário sem escritório vinculado.")
    return int(office_id)


def _get_user_id(request: Request) -> int | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return int(user_id)


def _get_office_name(request: Request) -> str:
    current_user = getattr(request.state, "current_user", None)
    office = getattr(current_user, "office", None) if current_user else None
    office_name = getattr(office, "nome", None) if office else None
    return (office_name or "Escritório").strip()


def _is_superadmin(request: Request, db: Session) -> bool:
    """
    Detecta se o usuário logado é superadministrador.
    Tenta primeiro pela sessão; se não encontrar, consulta no banco.
    """
    session_flag = request.session.get("is_superuser")
    if session_flag is not None:
        return bool(session_flag)

    user_id = request.session.get("user_id")
    if not user_id:
        return False

    user = db.query(User).filter(User.id == user_id).first()
    return bool(user and getattr(user, "is_superuser", False))


# =========================
# HELPERS
# =========================
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
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


templates.env.filters["money_br"] = _money_br


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


# =========================
# DASHBOARD
# =========================
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)
    user_id = _get_user_id(request)
    office_name = _get_office_name(request)
    is_superadmin = _is_superadmin(request, db)

    hoje = date.today()
    agora = datetime.now()

    # =========================
    # CLIENTES
    # =========================
    clientes_total = (
        db.query(func.count(Client.id))
        .filter(Client.office_id == office_id)
        .scalar() or 0
    )

    bday_mes_total = (
        db.query(func.count(Client.id))
        .filter(
            Client.office_id == office_id,
            Client.nascimento.is_not(None),
            extract("month", Client.nascimento) == hoje.month,
        )
        .scalar() or 0
    )

    clientes_hoje = (
        db.query(Client)
        .filter(
            Client.office_id == office_id,
            Client.nascimento.is_not(None),
            extract("month", Client.nascimento) == hoje.month,
            extract("day", Client.nascimento) == hoje.day,
        )
        .order_by(Client.nome.asc())
        .all()
    )

    bday_itens = []
    for c in clientes_hoje:
        fone = _normalize_phone_br(
            getattr(c, "telefone", None) or getattr(c, "phone", None)
        )

        msg = build_message_by_tipo(
            db=db,
            office_id=office_id,
            tipo="aniversario_cliente",
            client_name=getattr(c, "nome", None) or getattr(c, "name", None) or "Cliente",
            process_number="",
            promovido="",
            starts_at=None,
            modalidade="",
            extension_code=None,
            office_name=office_name,
            user_id=user_id,
        )

        wa = None
        if fone:
            wa = build_wa_me_link(fone, msg)

        bday_itens.append({"c": c, "wa": wa})

    # =========================
    # PERÍCIAS
    # =========================
    limite_pericias = hoje + timedelta(days=7)

    pericias_proximas = (
        db.query(PericiaDiligencia)
        .filter(
            PericiaDiligencia.office_id == office_id,
            PericiaDiligencia.concluido.is_(False),
            PericiaDiligencia.data_evento.is_not(None),
            PericiaDiligencia.data_evento >= hoje,
            PericiaDiligencia.data_evento <= limite_pericias,
        )
        .order_by(PericiaDiligencia.data_evento.asc())
        .all()
    )

    # =========================
    # PRAZOS
    # =========================
    fim_semana = _fim_da_semana(hoje)

    prazos_rompendo_semana_total = (
        db.query(func.count(ProcessItem.id))
        .filter(
            ProcessItem.office_id == office_id,
            ProcessItem.aba.in_(["PRAZOS", "Controle de Prazos"]),
            ProcessItem.cumprimento != "CUMPRIDO",
            ProcessItem.vencimento.isnot(None),
            ProcessItem.vencimento >= hoje,
            ProcessItem.vencimento <= fim_semana,
        )
        .scalar() or 0
    )

    # =========================
    # FINANCEIRO
    # ✅ SOMENTE SUPERADMINISTRADOR
    # =========================
    payables_alert_itens = []

    if is_superadmin:
        payables_alert = (
            db.query(Payable)
            .filter(
                Payable.office_id == office_id,
                Payable.pago.is_(False),
                Payable.vencimento.isnot(None),
                Payable.vencimento <= hoje,
            )
            .order_by(Payable.vencimento.asc())
            .all()
        )

        for p in payables_alert:
            dias_atraso = 0
            badge = "Hoje"

            if p.vencimento and p.vencimento < hoje:
                dias_atraso = (hoje - p.vencimento).days
                badge = "Atrasada"

            payables_alert_itens.append({
                "p": p,
                "badge": badge,
                "dias_atraso": dias_atraso
            })

    # =========================
    # AUDIÊNCIAS
    # =========================
    inicio = datetime.combine(hoje, datetime.min.time())
    fim = datetime.combine(hoje + timedelta(days=2), datetime.min.time())

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

    audiencias_hoje = []
    audiencias_proximo = []

    next_day = _next_business_day(hoje)

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

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "Painel Principal",
            "hoje": hoje,
            "next_day": next_day,
            "bday_itens": bday_itens,
            "pericias_proximas": pericias_proximas,
            "payables_alert_itens": payables_alert_itens,
            "audiencias_hoje": audiencias_hoje,
            "audiencias_proximo": audiencias_proximo,
            "audiencias_dashboard": audiencias_dashboard,
            "bday_mes_total": bday_mes_total,
            "clientes_total": clientes_total,
            "prazos_rompendo_semana_total": prazos_rompendo_semana_total,
            "is_superadmin": is_superadmin,
        },
    )