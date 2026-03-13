from datetime import date, timedelta
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.models.process_item import ProcessItem

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# =========================================================
# CALENDÁRIO (dias não úteis):
#  - Finais de semana
#  - Recesso forense: 20/12 a 20/01 (inclusive)
#  - Feriados nacionais (inclui Paixão de Cristo)
# =========================================================

def is_recesso_forense(d: date) -> bool:
    return (d.month == 12 and d.day >= 20) or (d.month == 1 and d.day <= 20)


def easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def national_holidays(year: int) -> set[date]:
    fixed = {
        date(year, 1, 1),
        date(year, 4, 21),
        date(year, 5, 1),
        date(year, 9, 7),
        date(year, 10, 12),
        date(year, 11, 2),
        date(year, 11, 15),
        date(year, 12, 25),
    }
    pascoa = easter_date(year)
    paixao = pascoa - timedelta(days=2)
    return fixed | {paixao}


def is_business_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    if is_recesso_forense(d):
        return False
    if d in national_holidays(d.year):
        return False
    return True


def add_business_days(start: date, days: int) -> date:
    if days <= 0:
        return start
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if is_business_day(current):
            added += 1
    return current


def dias_restantes(vencimento: date | None) -> int | None:
    if not vencimento:
        return None
    return (vencimento - date.today()).days


def cor_por_item(aba_norm: str, p: ProcessItem) -> str | None:
    if not getattr(p, "vencimento", None):
        return None

    dias = (p.vencimento - date.today()).days

    if aba_norm == "PRAZOS" and getattr(p, "cumprimento", None) == "CUMPRIDO":
        return "success"

    if dias < 0:
        return "danger"
    if dias <= 5:
        return "warning"
    return None


# -----------------------------
# Mapeamento: código -> rótulo
# -----------------------------
ABA_LABEL_BY_STATUS = {
    "PRAZOS": "Controle de Prazos",
    "PROCEDENTE": "Ações Procedentes",
    "EXECUCAO": "Ações em Execução",
}

STATUS_BY_ABA_LABEL_UP = {v.upper(): k for k, v in ABA_LABEL_BY_STATUS.items()}


def _titulo_por_aba_norm(aba_norm: str) -> str:
    return ABA_LABEL_BY_STATUS.get(aba_norm, "Processos")


def _normalize_aba(value: str | None) -> str:
    """
    Aceita:
      - "PROCEDENTE" / "EXECUCAO" / "PRAZOS"
      - "Ações Procedentes" / "Ações em Execução" / "Controle de Prazos"
    Retorna sempre o CÓDIGO: "PROCEDENTE|EXECUCAO|PRAZOS"
    """
    raw = (value or "PROCEDENTE").strip()
    up = raw.upper()

    if up in ("PROCEDENTE", "EXECUCAO", "PRAZOS"):
        return up

    if up in STATUS_BY_ABA_LABEL_UP:
        return STATUS_BY_ABA_LABEL_UP[up]

    return "PROCEDENTE"


def _aba_values_for_filter(aba_norm: str) -> list[str]:
    """
    Como no seu banco a coluna é 'aba', ela pode ter:
      - o código antigo (PRAZOS/PROCEDENTE/EXECUCAO)
      - o rótulo novo ("Controle de Prazos" etc.)
    Então filtramos pelos dois.
    """
    label = ABA_LABEL_BY_STATUS.get(aba_norm)
    if label:
        return [aba_norm, label]
    return [aba_norm]


def _normalize_filtro_prazos(value: str | None) -> str:
    f = (value or "PENDENTES").upper().strip()
    if f not in ("PENDENTES", "CUMPRIDOS", "TODOS"):
        f = "PENDENTES"
    return f


def _fim_da_semana(d: date) -> date:
    return d + timedelta(days=(6 - d.weekday()))


def _inicio_da_semana(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _contadores_por_aba(db: Session, aba_norm: str) -> dict | None:
    """
    Contadores:
      - PRAZOS: total, concluidos, vence_hoje, vence_semana, vence_proxima_semana, atrasados
      - PROCEDENTE/EXECUCAO: total, vence_hoje, vence_semana, vence_proxima_semana, atrasados
    Observação: Para manter a mesma lógica do controle de prazos:
      - PRAZOS ignora CUMPRIDO nos vencimentos/atrasados.
      - PROCEDENTE e EXECUCAO contam tudo da aba (não filtram por cumprimento),
        mas só consideram vencimento quando vencimento IS NOT NULL.
    """
    hoje = date.today()

    fim_semana = _fim_da_semana(hoje)
    inicio_proxima = fim_semana + timedelta(days=1)
    fim_proxima = inicio_proxima + timedelta(days=6)

    aba_values = _aba_values_for_filter(aba_norm)

    # TOTAL (sempre)
    total = (
        db.query(func.count(ProcessItem.id))
        .filter(ProcessItem.aba.in_(aba_values))
        .scalar()
        or 0
    )

    if aba_norm == "PRAZOS":
        concluidos = (
            db.query(func.count(ProcessItem.id))
            .filter(ProcessItem.aba.in_(aba_values))
            .filter(ProcessItem.cumprimento == "CUMPRIDO")
            .scalar()
            or 0
        )

        vence_hoje = (
            db.query(func.count(ProcessItem.id))
            .filter(ProcessItem.aba.in_(aba_values))
            .filter(ProcessItem.cumprimento != "CUMPRIDO")
            .filter(ProcessItem.vencimento == hoje)
            .scalar()
            or 0
        )

        vence_semana = (
            db.query(func.count(ProcessItem.id))
            .filter(ProcessItem.aba.in_(aba_values))
            .filter(ProcessItem.cumprimento != "CUMPRIDO")
            .filter(ProcessItem.vencimento.isnot(None))
            .filter(ProcessItem.vencimento >= hoje)
            .filter(ProcessItem.vencimento <= fim_semana)
            .scalar()
            or 0
        )

        vence_proxima_semana = (
            db.query(func.count(ProcessItem.id))
            .filter(ProcessItem.aba.in_(aba_values))
            .filter(ProcessItem.cumprimento != "CUMPRIDO")
            .filter(ProcessItem.vencimento.isnot(None))
            .filter(ProcessItem.vencimento >= inicio_proxima)
            .filter(ProcessItem.vencimento <= fim_proxima)
            .scalar()
            or 0
        )

        atrasados = (
            db.query(func.count(ProcessItem.id))
            .filter(ProcessItem.aba.in_(aba_values))
            .filter(ProcessItem.cumprimento != "CUMPRIDO")
            .filter(ProcessItem.vencimento.isnot(None))
            .filter(ProcessItem.vencimento < hoje)
            .scalar()
            or 0
        )

        return {
            "total": total,
            "concluidos": concluidos,
            "vence_hoje": vence_hoje,
            "vence_semana": vence_semana,
            "vence_proxima_semana": vence_proxima_semana,
            "atrasados": atrasados,
        }

    # ✅ PROCEDENTE / EXECUCAO (sem "concluidos")
    vence_hoje = (
        db.query(func.count(ProcessItem.id))
        .filter(ProcessItem.aba.in_(aba_values))
        .filter(ProcessItem.vencimento.isnot(None))
        .filter(ProcessItem.vencimento == hoje)
        .scalar()
        or 0
    )

    vence_semana = (
        db.query(func.count(ProcessItem.id))
        .filter(ProcessItem.aba.in_(aba_values))
        .filter(ProcessItem.vencimento.isnot(None))
        .filter(ProcessItem.vencimento >= hoje)
        .filter(ProcessItem.vencimento <= fim_semana)
        .scalar()
        or 0
    )

    vence_proxima_semana = (
        db.query(func.count(ProcessItem.id))
        .filter(ProcessItem.aba.in_(aba_values))
        .filter(ProcessItem.vencimento.isnot(None))
        .filter(ProcessItem.vencimento >= inicio_proxima)
        .filter(ProcessItem.vencimento <= fim_proxima)
        .scalar()
        or 0
    )

    atrasados = (
        db.query(func.count(ProcessItem.id))
        .filter(ProcessItem.aba.in_(aba_values))
        .filter(ProcessItem.vencimento.isnot(None))
        .filter(ProcessItem.vencimento < hoje)
        .scalar()
        or 0
    )

    return {
        "total": total,
        "vence_hoje": vence_hoje,
        "vence_semana": vence_semana,
        "vence_proxima_semana": vence_proxima_semana,
        "atrasados": atrasados,
    }


# -----------------------------
# LISTAS (3 abas)
# -----------------------------
@router.get("/processos", response_class=HTMLResponse)
def processos_list(
    request: Request,
    status: str = "PROCEDENTE",
    filtro: str = "PENDENTES",
    db: Session = Depends(get_db),
):
    aba_norm = _normalize_aba(status)  # sempre código
    aba_values = _aba_values_for_filter(aba_norm)

    filtro_prazos = _normalize_filtro_prazos(filtro) if aba_norm == "PRAZOS" else None

    q = db.query(ProcessItem).filter(ProcessItem.aba.in_(aba_values))

    if aba_norm == "PRAZOS":
        if filtro_prazos == "PENDENTES":
            q = q.filter(ProcessItem.cumprimento != "CUMPRIDO")
        elif filtro_prazos == "CUMPRIDOS":
            q = q.filter(ProcessItem.cumprimento == "CUMPRIDO")

    rows = (
        q.order_by(
            ProcessItem.vencimento.asc().nulls_last(),
            ProcessItem.parte_autora.asc(),
        )
        .all()
    )

    itens = []
    for p in rows:
        itens.append(
            {
                "p": p,
                "cor": cor_por_item(aba_norm, p),
                "dias_restantes": dias_restantes(p.vencimento),
            }
        )

    # ✅ contadores agora existem para as 3 abas
    counters = _contadores_por_aba(db, aba_norm)

    return templates.TemplateResponse(
        "processes/list.html",
        {
            "request": request,
            "title": _titulo_por_aba_norm(aba_norm),
            "status": aba_norm,          # "PROCEDENTE|EXECUCAO|PRAZOS"
            "filtro": filtro_prazos,
            "counters": counters,
            "itens": itens,
            "msg": None,
        },
    )


@router.get("/prazos", response_class=HTMLResponse)
def prazos_list(request: Request, filtro: str = "PENDENTES", db: Session = Depends(get_db)):
    return processos_list(request=request, status="PRAZOS", filtro=filtro, db=db)


# -----------------------------
# NOVO
# -----------------------------
@router.get("/processos/novo", response_class=HTMLResponse)
def processos_novo_form(request: Request, status: str = "PROCEDENTE"):
    aba_norm = _normalize_aba(status)
    return templates.TemplateResponse(
        "processes/form.html",
        {"request": request, "title": "Novo Processo", "p": None, "status": aba_norm, "erro": None},
    )


@router.post("/processos/novo")
def processos_novo(
    request: Request,
    db: Session = Depends(get_db),
    status: str = Form("PROCEDENTE"),
    numero_processo: str = Form(...),
    parte_autora: str = Form(...),
    vara: str = Form(...),
    data_intimacao: str = Form(""),
    prazo_dias: str = Form(""),
    obs: str = Form(""),
):
    aba_norm = _normalize_aba(status)
    aba_label = ABA_LABEL_BY_STATUS.get(aba_norm, aba_norm)
    numero = numero_processo.strip()

    existe = (
        db.query(ProcessItem)
        .filter(ProcessItem.aba.in_([aba_norm, aba_label]))
        .filter(ProcessItem.numero_processo == numero)
        .first()
    )
    if existe:
        return templates.TemplateResponse(
            "processes/form.html",
            {
                "request": request,
                "title": "Novo Processo",
                "p": None,
                "status": aba_norm,
                "erro": "Este processo já está cadastrado nesta aba.",
            },
            status_code=400,
        )

    djen = None
    if data_intimacao.strip():
        y, m, d = data_intimacao.split("-")
        djen = date(int(y), int(m), int(d))

    dias_int = None
    if prazo_dias.strip():
        dias_int = int(prazo_dias)

    venc = None
    if djen and dias_int:
        venc = add_business_days(djen, dias_int)

    # ✅ grava aba como rótulo (padrão novo), mas a listagem pega rótulo OU código
    p = ProcessItem(
        aba=aba_label,
        numero_processo=numero,
        parte_autora=parte_autora.strip(),
        vara=vara.strip(),
        data_intimacao=djen,
        prazo_dias=dias_int,
        vencimento=venc,
        obs=(obs.strip() or None),
        cumprimento="PENDENTE",
    )
    db.add(p)
    db.commit()

    return RedirectResponse(url=f"/processos?status={aba_norm}", status_code=303)


# -----------------------------
# EDITAR
# -----------------------------
@router.get("/processos/{pid}/editar", response_class=HTMLResponse)
def processos_editar_form(pid: int, request: Request, db: Session = Depends(get_db)):
    p = db.query(ProcessItem).filter(ProcessItem.id == pid).first()
    if not p:
        return RedirectResponse(url="/processos?status=PROCEDENTE", status_code=303)

    aba_norm = _normalize_aba(getattr(p, "aba", None))
    return templates.TemplateResponse(
        "processes/form.html",
        {"request": request, "title": "Editar Processo", "p": p, "status": aba_norm, "erro": None},
    )


@router.post("/processos/{pid}/editar")
def processos_editar(
    pid: int,
    request: Request,
    db: Session = Depends(get_db),
    numero_processo: str = Form(...),
    parte_autora: str = Form(...),
    vara: str = Form(...),
    data_intimacao: str = Form(""),
    prazo_dias: str = Form(""),
    obs: str = Form(""),
):
    p = db.query(ProcessItem).filter(ProcessItem.id == pid).first()
    if not p:
        return RedirectResponse(url="/processos?status=PROCEDENTE", status_code=303)

    numero = numero_processo.strip()

    aba_norm = _normalize_aba(getattr(p, "aba", None))
    aba_label = ABA_LABEL_BY_STATUS.get(aba_norm, aba_norm)
    aba_values = [aba_norm, aba_label]

    existe = (
        db.query(ProcessItem)
        .filter(ProcessItem.aba.in_(aba_values))
        .filter(ProcessItem.numero_processo == numero)
        .filter(ProcessItem.id != p.id)
        .first()
    )
    if existe:
        return templates.TemplateResponse(
            "processes/form.html",
            {
                "request": request,
                "title": "Editar Processo",
                "p": p,
                "status": aba_norm,
                "erro": "Já existe este número de processo nesta aba.",
            },
            status_code=400,
        )

    djen = None
    if data_intimacao.strip():
        y, m, d = data_intimacao.split("-")
        djen = date(int(y), int(m), int(d))

    dias_int = None
    if prazo_dias.strip():
        dias_int = int(prazo_dias)

    venc = None
    if djen and dias_int:
        venc = add_business_days(djen, dias_int)

    p.numero_processo = numero
    p.parte_autora = parte_autora.strip()
    p.vara = vara.strip()
    p.data_intimacao = djen
    p.prazo_dias = dias_int
    p.vencimento = venc
    p.obs = (obs.strip() or None)

    db.add(p)
    db.commit()

    return RedirectResponse(url=f"/processos?status={aba_norm}", status_code=303)


# -----------------------------
# EXCLUIR
# -----------------------------
@router.post("/processos/{pid}/excluir")
def processos_excluir(pid: int, db: Session = Depends(get_db), status: str = Form("PROCEDENTE")):
    p = db.query(ProcessItem).filter(ProcessItem.id == pid).first()
    if p:
        aba_norm = _normalize_aba(getattr(p, "aba", None))
        db.delete(p)
        db.commit()
        return RedirectResponse(url=f"/processos?status={aba_norm}", status_code=303)

    aba_norm = _normalize_aba(status)
    return RedirectResponse(url=f"/processos?status={aba_norm}", status_code=303)


@router.post("/processos/excluir-lote")
def processos_excluir_lote(db: Session = Depends(get_db), status: str = Form(...), ids: str = Form("")):
    aba_norm = _normalize_aba(status)
    aba_label = ABA_LABEL_BY_STATUS.get(aba_norm, aba_norm)
    aba_values = [aba_norm, aba_label]

    if ids.strip():
        lista_ids = [int(x) for x in ids.split(",") if x.strip().isdigit()]
        if lista_ids:
            rows = (
                db.query(ProcessItem)
                .filter(ProcessItem.aba.in_(aba_values))
                .filter(ProcessItem.id.in_(lista_ids))
                .all()
            )
            for r in rows:
                db.delete(r)
            db.commit()

    return RedirectResponse(url=f"/processos?status={aba_norm}", status_code=303)


# -----------------------------
# ATUALIZAR STATUS
# -----------------------------
@router.post("/processos/{pid}/atualizar-status")
def processos_atualizar_status(
    pid: int,
    db: Session = Depends(get_db),
    status: str = Form(...),
    cumprimento: str = Form(...),
    filtro: str = Form(""),
):
    p = db.query(ProcessItem).filter(ProcessItem.id == pid).first()
    if not p:
        return RedirectResponse(url="/processos?status=PROCEDENTE", status_code=303)

    aba_redirect = _normalize_aba(status)
    novo = (cumprimento or "PENDENTE").upper().strip()

    if novo not in ("PENDENTE", "CUMPRIDO", "TRANSITADO", "RECURSO"):
        novo = "PENDENTE"

    if novo == "TRANSITADO":
        p.aba = ABA_LABEL_BY_STATUS["EXECUCAO"]
        p.cumprimento = "TRANSITADO"
    elif novo == "RECURSO":
        p.aba = ABA_LABEL_BY_STATUS["PRAZOS"]
        p.cumprimento = "RECURSO"
    elif novo == "CUMPRIDO":
        p.cumprimento = "CUMPRIDO"
    else:
        p.cumprimento = "PENDENTE"
        p.aba = ABA_LABEL_BY_STATUS.get(aba_redirect, aba_redirect)

    db.add(p)
    db.commit()

    if aba_redirect == "PRAZOS":
        f = _normalize_filtro_prazos(filtro) if filtro else "PENDENTES"
        return RedirectResponse(url=f"/processos?status=PRAZOS&filtro={f}", status_code=303)

    return RedirectResponse(url=f"/processos?status={aba_redirect}", status_code=303)
