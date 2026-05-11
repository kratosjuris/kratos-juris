from datetime import date
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.datetime_utils import now_br

from app.core.database import get_db
from app.models.pericia_models import PericiaDiligencia

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _get_office_id(request: Request) -> int:
    office_id = request.session.get("office_id")
    if not office_id:
        raise HTTPException(status_code=403, detail="Usuário sem escritório vinculado.")
    return int(office_id)


def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        y, m, d = value.split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


# ==========================
# LISTAGEM
# ==========================
@router.get("/pericias", response_class=HTMLResponse)
def pericias_list(
    request: Request,
    status: str = "PENDENTE",
    db: Session = Depends(get_db),
):
    office_id = _get_office_id(request)
    status = status.upper()

    q = db.query(PericiaDiligencia).filter(PericiaDiligencia.office_id == office_id)

    if status == "PENDENTE":
        q = q.filter(PericiaDiligencia.concluido.is_(False))
    elif status == "CONCLUIDA":
        q = q.filter(PericiaDiligencia.concluido.is_(True))
    else:
        status = "TODAS"

    rows = q.order_by(
        PericiaDiligencia.data_evento.asc().nulls_last(),
        PericiaDiligencia.nome_parte.asc(),
    ).all()

    return templates.TemplateResponse(
        "pericias/list.html",
        {
            "request": request,
            "title": "Perícias & Diligências",
            "rows": rows,
            "status": status,
            "hoje": now_br().date(),
        },
    )


# ==========================
# NOVO REGISTRO
# ==========================
@router.post("/pericias/novo")
def pericias_novo(
    request: Request,
    db: Session = Depends(get_db),
    numero_processo: str = Form(...),
    nome_parte: str = Form(...),
    observacao: str = Form(""),
    local: str = Form(""),
    data_evento: str = Form(""),
):
    office_id = _get_office_id(request)

    item = PericiaDiligencia(
        office_id=office_id,
        numero_processo=numero_processo.strip(),
        nome_parte=nome_parte.strip(),
        observacao=observacao.strip() or None,
        local=local.strip() or None,
        data_evento=_parse_date(data_evento),
        concluido=False,
        concluido_em=None,
    )

    db.add(item)
    db.commit()

    return RedirectResponse(url="/pericias", status_code=303)


# ==========================
# EDITAR
# ==========================
@router.post("/pericias/{pid}/editar")
def pericias_editar(
    request: Request,
    pid: int,
    db: Session = Depends(get_db),
    numero_processo: str = Form(...),
    nome_parte: str = Form(...),
    observacao: str = Form(""),
    local: str = Form(""),
    data_evento: str = Form(""),
):
    office_id = _get_office_id(request)

    item = (
        db.query(PericiaDiligencia)
        .filter(
            PericiaDiligencia.id == pid,
            PericiaDiligencia.office_id == office_id,
        )
        .first()
    )
    if not item:
        return RedirectResponse(url="/pericias", status_code=303)

    item.numero_processo = numero_processo.strip()
    item.nome_parte = nome_parte.strip()
    item.observacao = observacao.strip() or None
    item.local = local.strip() or None
    item.data_evento = _parse_date(data_evento)

    db.commit()
    return RedirectResponse(url="/pericias", status_code=303)


# ==========================
# CONCLUIR / REABRIR
# ==========================
@router.post("/pericias/{pid}/toggle")
def pericias_toggle(request: Request, pid: int, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)

    item = (
        db.query(PericiaDiligencia)
        .filter(
            PericiaDiligencia.id == pid,
            PericiaDiligencia.office_id == office_id,
        )
        .first()
    )
    if item:
        item.concluido = not item.concluido
        item.concluido_em = now_br().date() if item.concluido else None
        db.commit()

    return RedirectResponse(url="/pericias", status_code=303)


# ==========================
# EXCLUIR
# ==========================
@router.post("/pericias/{pid}/excluir")
def pericias_excluir(request: Request, pid: int, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)

    item = (
        db.query(PericiaDiligencia)
        .filter(
            PericiaDiligencia.id == pid,
            PericiaDiligencia.office_id == office_id,
        )
        .first()
    )
    if item:
        db.delete(item)
        db.commit()

    return RedirectResponse(url="/pericias", status_code=303)