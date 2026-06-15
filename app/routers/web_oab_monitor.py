"""
app/routers/web_oab_monitor.py

Router de gerenciamento das OABs monitoradas automaticamente.
Rotas: GET/POST /configuracoes/oabs
"""

import re
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.datetime_utils import now_br
from app.models.oab_monitorada import OabMonitorada

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

UFS = [
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA",
    "MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN",
    "RS","RO","RR","SC","SP","SE","TO",
]


def _get_office_id(request: Request) -> int:
    office_id = request.session.get("office_id")
    if not office_id:
        raise HTTPException(status_code=403, detail="Usuário sem escritório vinculado.")
    return int(office_id)


def _redirect(msg: str) -> RedirectResponse:
    return RedirectResponse(
        url=f"/configuracoes/oabs?msg={quote(str(msg))}",
        status_code=303,
    )


def _norm_oab(numero: str, uf: str):
    num = re.sub(r"\D+", "", numero or "")
    uf_norm = re.sub(r"[^A-Za-z]", "", uf or "").upper()[:2]
    return num, uf_norm


# ---------------------------------------------------------------------------
# GET — listagem
# ---------------------------------------------------------------------------

@router.get("/configuracoes/oabs", response_class=HTMLResponse)
def oabs_view(request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)

    oabs = (
        db.query(OabMonitorada)
        .filter(OabMonitorada.office_id == office_id)
        .order_by(OabMonitorada.ativa.desc(), OabMonitorada.criado_em.asc())
        .all()
    )

    msg = request.query_params.get("msg")

    return templates.TemplateResponse(
        "configuracoes/oabs.html",
        {
            "request": request,
            "title": "OABs Monitoradas",
            "oabs": oabs,
            "ufs": UFS,
            "msg": msg,
        },
    )


# ---------------------------------------------------------------------------
# POST — cadastrar nova OAB
# ---------------------------------------------------------------------------

@router.post("/configuracoes/oabs/adicionar")
def oabs_adicionar(
    request: Request,
    numero_oab: str = Form(...),
    uf_oab: str = Form(...),
    nome_advogado: str = Form(""),
    db: Session = Depends(get_db),
):
    office_id = _get_office_id(request)
    num, uf = _norm_oab(numero_oab, uf_oab)

    if not num:
        return _redirect("Número da OAB inválido.")
    if not uf:
        return _redirect("UF inválida.")

    oab = OabMonitorada(
        office_id=office_id,
        numero_oab=num,
        uf_oab=uf,
        nome_advogado=(nome_advogado or "").strip() or None,
        ativa=True,
        criado_em=now_br(),
    )

    try:
        db.add(oab)
        db.commit()
    except IntegrityError:
        db.rollback()
        return _redirect(f"OAB {num}/{uf} já está cadastrada neste escritório.")

    return _redirect(f"OAB {num}/{uf} cadastrada e monitoramento ativado.")


# ---------------------------------------------------------------------------
# POST — ativar / desativar
# ---------------------------------------------------------------------------

@router.post("/configuracoes/oabs/{oab_id}/toggle")
def oabs_toggle(
    request: Request,
    oab_id: int,
    db: Session = Depends(get_db),
):
    office_id = _get_office_id(request)

    oab = (
        db.query(OabMonitorada)
        .filter(OabMonitorada.id == oab_id, OabMonitorada.office_id == office_id)
        .first()
    )

    if not oab:
        return _redirect("OAB não encontrada.")

    oab.ativa = not oab.ativa
    oab.atualizado_em = now_br()
    db.add(oab)
    db.commit()

    status = "ativada" if oab.ativa else "desativada"
    return _redirect(f"OAB {oab.numero_oab}/{oab.uf_oab} {status}.")


# ---------------------------------------------------------------------------
# POST — excluir
# ---------------------------------------------------------------------------

@router.post("/configuracoes/oabs/{oab_id}/excluir")
def oabs_excluir(
    request: Request,
    oab_id: int,
    db: Session = Depends(get_db),
):
    office_id = _get_office_id(request)

    oab = (
        db.query(OabMonitorada)
        .filter(OabMonitorada.id == oab_id, OabMonitorada.office_id == office_id)
        .first()
    )

    if not oab:
        return _redirect("OAB não encontrada.")

    label = f"{oab.numero_oab}/{oab.uf_oab}"
    db.delete(oab)
    db.commit()

    return _redirect(f"OAB {label} removida do monitoramento.")


# ---------------------------------------------------------------------------
# POST — rodar monitoramento manualmente agora para uma OAB específica
# ---------------------------------------------------------------------------

@router.post("/configuracoes/oabs/{oab_id}/monitorar-agora")
async def oabs_monitorar_agora(
    request: Request,
    oab_id: int,
    data_inicio: str = Form(...),
    data_fim: str = Form(...),
    db: Session = Depends(get_db),
):
    from datetime import date as date_type
    import re as _re

    office_id = _get_office_id(request)

    oab = (
        db.query(OabMonitorada)
        .filter(OabMonitorada.id == oab_id, OabMonitorada.office_id == office_id)
        .first()
    )

    if not oab:
        return _redirect("OAB não encontrada.")

    def _parse(s):
        s = (s or "").strip()
        m = _re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
        if m:
            y, mo, d = m.groups()
            return date_type(int(y), int(mo), int(d))
        return None

    di = _parse(data_inicio)
    df = _parse(data_fim)

    if not di or not df:
        return _redirect("Datas inválidas.")

    if (df - di).days > 90:
        return _redirect("Período máximo: 90 dias.")

    from app.services.monitor_djen import monitorar_oab

    try:
        resultado = await monitorar_oab(db, oab, di, df)
    except Exception as e:
        return _redirect(f"Erro ao monitorar: {e}")

    return _redirect(
        f"OAB {oab.numero_oab}/{oab.uf_oab} — "
        f"{resultado['total_inseridos']} intimação(ões) inserida(s) | "
        f"extraídas: {resultado['total_extraidos']} | "
        f"ignoradas: {resultado['total_ignorados']}."
    )