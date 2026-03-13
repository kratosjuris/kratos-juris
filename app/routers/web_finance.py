# app/routers/web_finance.py

import os
import urllib.parse
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_

from app.core.database import get_db
from app.models.finance_models import FinanceMonth, ExpenseTemplate, Payable, Receivable

router = APIRouter()

# ✅ Caminho ABSOLUTO dos templates (resolve TemplateNotFound mesmo rodando uvicorn em outra pasta)
APP_DIR = Path(__file__).resolve().parents[1]   # .../app
TEMPLATES_DIR = APP_DIR / "templates"          # .../app/templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ----------------------------
# Formatadores BR (data e moeda)
# ----------------------------
def _fmt_br(dt: date | None) -> str:
    if not dt:
        return "—"
    return dt.strftime("%d/%m/%Y")


def _money_br(value) -> str:
    try:
        v = float(value or 0.0)
    except Exception:
        v = 0.0

    s = f"{v:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _number_br(value) -> str:
    try:
        v = float(value or 0.0)
    except Exception:
        v = 0.0
    s = f"{v:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def _parse_brl_number(s: str) -> float:
    if s is None:
        return 0.0
    txt = str(s).strip()
    if not txt:
        return 0.0

    txt = txt.replace("R$", "").replace(" ", "").replace("\xa0", "")

    if "," in txt:
        txt = txt.replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except Exception:
        return 0.0


templates.env.filters["money_br"] = _money_br
templates.env.filters["date_br"] = _fmt_br
templates.env.filters["number_br"] = _number_br


# ----------------------------
# Auth (senha)
# ----------------------------
def _finance_password() -> str:
    return os.getenv("FINANCE_PASSWORD", "").strip()


def _is_authed(request: Request) -> bool:
    return bool(request.session.get("finance_auth"))


def _require_auth(request: Request):
    if _is_authed(request):
        return None

    nxt = request.url.path
    if request.url.query:
        nxt += "?" + request.url.query

    nxt_q = urllib.parse.quote(nxt, safe="/?=&")
    return RedirectResponse(url=f"/financeiro/login?next={nxt_q}", status_code=303)


def _ym_default() -> str:
    hoje = date.today()
    return f"{hoje.year:04d}-{hoje.month:02d}"


def _normalize_ym(ym: str | None) -> str:
    ym = (ym or "").strip()
    if len(ym) == 7 and ym[4] == "-":
        return ym
    return _ym_default()


def _ym_from_date(dt: date | None) -> str | None:
    if not dt:
        return None
    return f"{dt.year:04d}-{dt.month:02d}"


def _parse_date_any(value: str | None, fallback: date | None = None) -> date | None:
    txt = (value or "").strip()
    if not txt:
        return fallback

    # YYYY-MM-DD
    if "-" in txt:
        try:
            y, m, d = txt.split("-")
            return date(int(y), int(m), int(d))
        except Exception:
            return fallback

    # DD/MM/YYYY
    if "/" in txt:
        try:
            d, m, y = txt.split("/")
            return date(int(y), int(m), int(d))
        except Exception:
            return fallback

    return fallback


def _conta_label(code: str) -> str:
    return {
        "CONTA_CSL": "Conta CSL",
        "CONTA_TARCISIO": "Conta Tarcisio",
        "CONTA_ANA": "Conta Ana Luisa",
        "CONTA_TIAGO": "Conta Tiago",
    }.get(code, code)


# =========================================================
# ✅ COMPETÊNCIA (DESPESAS)
# Regra: pago_em em mês X => competência mês X-1
# Ex.: pago em Jan/2026 => competência Dez/2025
# =========================================================
def _ym_prev(ym: str) -> str:
    """
    Retorna o mês anterior de um ym 'YYYY-MM'.
    """
    try:
        y = int(ym[:4])
        m = int(ym[5:7])
    except Exception:
        return ym

    if m <= 1:
        return f"{y - 1:04d}-12"
    return f"{y:04d}-{m - 1:02d}"


def _competencia_ym_from_payment_date(paid_dt: date | None) -> str | None:
    """
    Converte uma data de pagamento em ym de competência (mês anterior).
    """
    if not paid_dt:
        return None
    ym_pay = f"{paid_dt.year:04d}-{paid_dt.month:02d}"
    return _ym_prev(ym_pay)


def _competencia_ym_for_payable(p: Payable) -> str:
    """
    Define a competência de um Payable:
    - se pago e tem pago_em: competência = mês anterior do pago_em
    - fallback: usa p.ym (como está no seu banco hoje)
    """
    if getattr(p, "pago", False) and getattr(p, "pago_em", None):
        comp = _competencia_ym_from_payment_date(p.pago_em)
        if comp:
            return comp
    return (getattr(p, "ym", None) or "").strip() or _ym_default()


# ----------------------------
# Login / Logout
# ----------------------------
@router.get("/financeiro/login", response_class=HTMLResponse)
def financeiro_login_form(request: Request, next: str = "/financeiro"):
    return templates.TemplateResponse(
        "finance/login.html",
        {"request": request, "title": "Acesso Financeiro", "erro": None, "next": next},
    )


@router.post("/financeiro/login")
def financeiro_login(
    request: Request,
    senha: str = Form(""),
    next: str = Form("/financeiro"),
):
    pw = _finance_password()
    if not pw:
        return templates.TemplateResponse(
            "finance/login.html",
            {
                "request": request,
                "title": "Acesso Financeiro",
                "erro": "FINANCE_PASSWORD não está definido no ambiente. Defina no PowerShell e reinicie o servidor.",
                "next": next,
            },
            status_code=400,
        )

    if senha.strip() != pw:
        return templates.TemplateResponse(
            "finance/login.html",
            {"request": request, "title": "Acesso Financeiro", "erro": "Senha incorreta.", "next": next},
            status_code=401,
        )

    request.session["finance_auth"] = True
    return RedirectResponse(url=(next or "/financeiro"), status_code=303)


@router.get("/financeiro/sair")
def financeiro_logout_redirect(request: Request):
    request.session.pop("finance_auth", None)
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/financeiro/logout")
def financeiro_logout_silent(request: Request):
    request.session.pop("finance_auth", None)
    return Response(status_code=204)


@router.get("/financeiro/ping")
def financeiro_ping(request: Request):
    if not _is_authed(request):
        return Response(status_code=401)
    return Response(status_code=204)


# ----------------------------
# Home do Financeiro
# ----------------------------
@router.get("/financeiro", response_class=HTMLResponse)
def financeiro_home(request: Request):
    redir = _require_auth(request)
    if redir:
        return redir

    return templates.TemplateResponse(
        "finance/index.html",
        {"request": request, "title": "Financeiro"},
    )


# ----------------------------
# Contas a Pagar
# ----------------------------
def _get_or_create_month(db: Session, ym: str) -> FinanceMonth:
    m = db.query(FinanceMonth).filter(FinanceMonth.ym == ym).first()
    if not m:
        m = FinanceMonth(ym=ym, saldo_inicial=0.0)
        db.add(m)
        db.commit()
        db.refresh(m)
    return m


@router.get("/financeiro/pagar", response_class=HTMLResponse)
def pagar_list(request: Request, ym: str | None = None, db: Session = Depends(get_db)):
    redir = _require_auth(request)
    if redir:
        return redir

    ym = _normalize_ym(ym)
    month = _get_or_create_month(db, ym)

    payables = (
        db.query(Payable)
        .filter(Payable.ym == ym)
        .order_by(Payable.pago.asc(), Payable.vencimento.asc().nulls_last(), Payable.descricao.asc())
        .all()
    )

    total_despesas = sum((p.valor or 0.0) for p in payables)
    total_pago = sum((p.valor or 0.0) for p in payables if p.pago)
    total_pendente = total_despesas - total_pago

    saldo_inicial = float(month.saldo_inicial or 0.0)
    saldo_restante = saldo_inicial - total_pago

    templates_list = (
        db.query(ExpenseTemplate)
        .order_by(ExpenseTemplate.tipo.asc(), ExpenseTemplate.nome.asc())
        .all()
    )

    return templates.TemplateResponse(
        "finance/pagar.html",
        {
            "request": request,
            "title": "Contas a Pagar",
            "ym": ym,
            "month": month,
            "payables": payables,
            "templates_list": templates_list,
            "total_despesas": float(total_despesas),
            "total_pago": float(total_pago),
            "total_pendente": float(total_pendente),
            "saldo_inicial": float(saldo_inicial),
            "saldo_restante": float(saldo_restante),
        },
    )


@router.post("/financeiro/pagar/saldo")
def pagar_set_saldo(request: Request, db: Session = Depends(get_db), ym: str = Form(...), saldo_inicial: str = Form("0")):
    redir = _require_auth(request)
    if redir:
        return redir

    ym = _normalize_ym(ym)
    m = _get_or_create_month(db, ym)

    val = _parse_brl_number(saldo_inicial or "0")
    m.saldo_inicial = float(val)
    db.add(m)
    db.commit()

    return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)


@router.post("/financeiro/pagar/novo")
def pagar_novo(
    request: Request,
    db: Session = Depends(get_db),
    ym: str = Form(...),
    template_id: str = Form(""),
    descricao: str = Form(""),
    tipo: str = Form("FIXA"),
    valor: str = Form("0"),
    vencimento: str = Form(""),
    obs: str = Form(""),
    salvar_modelo: str = Form("0"),
):
    redir = _require_auth(request)
    if redir:
        return redir

    ym = _normalize_ym(ym)

    if template_id.strip().isdigit():
        t = db.query(ExpenseTemplate).filter(ExpenseTemplate.id == int(template_id)).first()
        if t:
            if not descricao.strip():
                descricao = t.nome
            if not valor.strip() or valor.strip() == "0":
                valor = str(t.valor_padrao or 0.0)
            if not obs.strip() and (t.observacao or "").strip():
                obs = t.observacao or ""
            tipo = (t.tipo or tipo).upper().strip()

    v = _parse_brl_number(valor or "0")

    dt = None
    if (vencimento or "").strip():
        y, m, d = vencimento.split("-")
        dt = date(int(y), int(m), int(d))

    p = Payable(
        ym=ym,
        descricao=descricao.strip() or "Despesa",
        tipo=(tipo or "FIXA").upper().strip(),
        valor=float(v),
        vencimento=dt,
        pago=False,
        pago_em=None,
        obs=(obs or "").strip() or None,
    )
    db.add(p)

    if salvar_modelo == "1":
        nome_modelo = (descricao or "").strip()
        if nome_modelo:
            existe = db.query(ExpenseTemplate).filter(func.lower(ExpenseTemplate.nome) == nome_modelo.lower()).first()
            if not existe:
                db.add(
                    ExpenseTemplate(
                        nome=nome_modelo,
                        tipo=(tipo or "FIXA").upper().strip(),
                        valor_padrao=float(v),
                        observacao=(obs or "").strip() or None,
                    )
                )

    db.commit()
    return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)


@router.post("/financeiro/pagar/{pid}/toggle")
def pagar_toggle(request: Request, pid: int, db: Session = Depends(get_db), ym: str = Form(...)):
    redir = _require_auth(request)
    if redir:
        return redir

    ym = _normalize_ym(ym)
    p = db.query(Payable).filter(Payable.id == pid).first()
    if p:
        p.pago = not bool(p.pago)
        p.pago_em = date.today() if p.pago else None
        db.add(p)
        db.commit()
    return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)


@router.post("/financeiro/pagar/{pid}/editar")
def pagar_editar(
    request: Request,
    pid: int,
    db: Session = Depends(get_db),
    ym: str = Form(...),
    descricao: str = Form(...),
    tipo: str = Form("FIXA"),
    valor: str = Form("0"),
    vencimento: str = Form(""),
    obs: str = Form(""),
):
    redir = _require_auth(request)
    if redir:
        return redir

    ym = _normalize_ym(ym)
    p = db.query(Payable).filter(Payable.id == pid).first()
    if not p:
        return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)

    v = _parse_brl_number(valor or str(p.valor or 0.0))

    dt = None
    if (vencimento or "").strip():
        y, m, d = vencimento.split("-")
        dt = date(int(y), int(m), int(d))

    p.descricao = descricao.strip()
    p.tipo = (tipo or "FIXA").upper().strip()
    p.valor = float(v)
    p.vencimento = dt
    p.obs = (obs or "").strip() or None

    db.add(p)
    db.commit()
    return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)


@router.post("/financeiro/pagar/{pid}/excluir")
def pagar_excluir(request: Request, pid: int, db: Session = Depends(get_db), ym: str = Form(...)):
    redir = _require_auth(request)
    if redir:
        return redir

    ym = _normalize_ym(ym)
    p = db.query(Payable).filter(Payable.id == pid).first()
    if p:
        db.delete(p)
        db.commit()
    return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)


@router.post("/financeiro/pagar/modelo/{tid}/excluir")
def pagar_modelo_excluir(request: Request, tid: int, db: Session = Depends(get_db), ym: str = Form(_ym_default())):
    # ✅ Mantida apenas UMA rota (removida a duplicada no final do arquivo)
    redir = _require_auth(request)
    if redir:
        return redir

    t = db.query(ExpenseTemplate).filter(ExpenseTemplate.id == tid).first()
    if t:
        db.delete(t)
        db.commit()

    ym = _normalize_ym(ym)
    return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)


@router.get("/financeiro/pagar/relatorio", response_class=HTMLResponse)
def pagar_relatorio(request: Request, ym: str | None = None, db: Session = Depends(get_db)):
    redir = _require_auth(request)
    if redir:
        return redir

    ym = _normalize_ym(ym)
    month = _get_or_create_month(db, ym)

    payables = (
        db.query(Payable)
        .filter(Payable.ym == ym)
        .order_by(Payable.pago.asc(), Payable.vencimento.asc().nulls_last(), Payable.descricao.asc())
        .all()
    )

    total_despesas = sum((p.valor or 0.0) for p in payables)
    total_pago = sum((p.valor or 0.0) for p in payables if p.pago)

    saldo_inicial = float(month.saldo_inicial or 0.0)
    saldo_final = saldo_inicial - total_pago

    return templates.TemplateResponse(
        "finance/relatorio_pagar.html",
        {
            "request": request,
            "title": "Relatório Contas a Pagar",
            "ym": ym,
            "payables": payables,
            "saldo_inicial": float(saldo_inicial),
            "saldo_final": float(saldo_final),
            "total_despesas": float(total_despesas),
            "total_pago": float(total_pago),
        },
    )


# ----------------------------
# Contas a Receber
# ----------------------------
@router.get("/financeiro/receber", response_class=HTMLResponse)
def receber_list(
    request: Request,
    ym: str | None = None,
    status: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    redir = _require_auth(request)
    if redir:
        return redir

    ym = _normalize_ym(ym)
    status = (status or "").strip()
    q = (q or "").strip()

    query = db.query(Receivable).filter(Receivable.ym == ym)

    if status == "Recebido":
        query = query.filter(Receivable.recebido.is_(True))
    elif status == "Pendente":
        query = query.filter(Receivable.recebido.is_(False))

    if q:
        like = f"%{q}%"
        query = query.filter(
            (Receivable.parte_autora.ilike(like))
            | (Receivable.numero_processo.ilike(like))
            | (Receivable.vara.ilike(like))
        )

    rows_db = (
        query.order_by(
            Receivable.recebido.asc(),
            Receivable.data_prevista.asc().nulls_last(),
            Receivable.parte_autora.asc(),
        ).all()
    )

    hoje = date.today()
    rows = []
    for r in rows_db:
        valor = float(r.valor or 0.0)
        em_atraso = (not r.recebido) and bool(r.data_prevista) and (r.data_prevista < hoje)

        rows.append(
            {
                "id": r.id,
                "ym": r.ym,
                "numero_processo": r.numero_processo,
                "parte_autora": r.parte_autora,
                "vara": r.vara,
                "data_prevista": r.data_prevista,
                "data_prevista_iso": r.data_prevista.isoformat() if r.data_prevista else "",
                "conta": r.conta,
                "conta_label": _conta_label(r.conta),
                "valor": valor,
                "valor_raw": f"{valor:.2f}",
                "recebido": bool(r.recebido),
                "recebido_em": r.recebido_em,
                "obs": r.obs,
                "em_atraso": em_atraso,
            }
        )

    total = sum((r["valor"] or 0.0) for r in rows)
    total_recebido = sum((r["valor"] or 0.0) for r in rows if r["recebido"])
    total_pendente = total - total_recebido

    y, m = ym.split("-")
    y = int(y)
    m = int(m)
    ym_prev = f"{y-1:04d}-12" if m == 1 else f"{y:04d}-{m-1:02d}"

    prev_total = (
        db.query(func.coalesce(func.sum(Receivable.valor), 0.0))
        .filter(Receivable.ym == ym_prev)
        .scalar()
        or 0.0
    )

    contas = ["CONTA_CSL", "CONTA_TARCISIO", "CONTA_ANA", "CONTA_TIAGO"]
    por_conta = []
    for c in contas:
        s = sum((r["valor"] or 0.0) for r in rows if r["conta"] == c)
        por_conta.append({"conta": c, "label": _conta_label(c), "total": float(s)})

    return templates.TemplateResponse(
        "finance/receber.html",
        {
            "request": request,
            "title": "Contas a Receber",
            "ym": ym,
            "rows": rows,
            "total": float(total),
            "total_recebido": float(total_recebido),
            "total_pendente": float(total_pendente),
            "ym_prev": ym_prev,
            "prev_total": float(prev_total),
            "por_conta": por_conta,
            "status": status or None,
            "q": q or None,
        },
    )


@router.post("/financeiro/receber/novo")
def receber_novo(
    request: Request,
    db: Session = Depends(get_db),
    ym: str = Form(...),
    numero_processo: str = Form(...),
    parte_autora: str = Form(...),
    vara: str = Form(...),
    data_prevista: str = Form(""),
    conta: str = Form("CONTA_CSL"),
    valor: str = Form("0"),
    obs: str = Form(""),
):
    redir = _require_auth(request)
    if redir:
        return redir

    ym = _normalize_ym(ym)
    v = _parse_brl_number(valor or "0")

    dt = _parse_date_any(data_prevista, fallback=None)

    # ✅ se existe data_prevista, competência acompanha
    ym_by_date = _ym_from_date(dt)
    if ym_by_date:
        ym = ym_by_date

    conta = (conta or "CONTA_CSL").upper().strip()
    if conta not in ("CONTA_CSL", "CONTA_TARCISIO", "CONTA_ANA", "CONTA_TIAGO"):
        conta = "CONTA_CSL"

    r = Receivable(
        ym=ym,
        numero_processo=numero_processo.strip(),
        parte_autora=parte_autora.strip(),
        vara=vara.strip(),
        data_prevista=dt,
        conta=conta,
        valor=float(v),
        recebido=False,
        recebido_em=None,
        obs=(obs or "").strip() or None,
    )
    db.add(r)
    db.commit()

    return RedirectResponse(url=f"/financeiro/receber?ym={ym}", status_code=303)


@router.post("/financeiro/receber/{rid}/toggle")
def receber_toggle(request: Request, rid: int, db: Session = Depends(get_db), ym: str = Form(...)):
    redir = _require_auth(request)
    if redir:
        return redir

    ym = _normalize_ym(ym)
    r = db.query(Receivable).filter(Receivable.id == rid).first()
    if r:
        r.recebido = not bool(r.recebido)
        r.recebido_em = date.today() if r.recebido else None
        db.add(r)
        db.commit()
    return RedirectResponse(url=f"/financeiro/receber?ym={ym}", status_code=303)


@router.post("/financeiro/receber/{rid}/editar")
def receber_editar(
    request: Request,
    rid: int,
    db: Session = Depends(get_db),
    ym: str = Form(...),               # mês da tela (fallback)
    ym_novo: str = Form(""),           # ✅ competência escolhida no modal
    numero_processo: str = Form(...),
    parte_autora: str = Form(...),
    vara: str = Form(...),
    data_prevista: str = Form(""),
    conta: str = Form("CONTA_CSL"),
    valor: str = Form("0"),
    obs: str = Form(""),
):
    redir = _require_auth(request)
    if redir:
        return redir

    ym = _normalize_ym(ym)
    ym_novo = _normalize_ym(ym_novo) if (ym_novo or "").strip() else ""

    r = db.query(Receivable).filter(Receivable.id == rid).first()
    if not r:
        return RedirectResponse(url=f"/financeiro/receber?ym={ym}", status_code=303)

    v = _parse_brl_number(valor or str(r.valor or 0.0))

    # ✅ não apaga a data se usuário não mexeu
    dt = _parse_date_any(data_prevista, fallback=r.data_prevista)

    conta = (conta or "CONTA_CSL").upper().strip()
    if conta not in ("CONTA_CSL", "CONTA_TARCISIO", "CONTA_ANA", "CONTA_TIAGO"):
        conta = "CONTA_CSL"

    r.numero_processo = (numero_processo or "").strip()
    r.parte_autora = (parte_autora or "").strip()
    r.vara = (vara or "").strip()
    r.data_prevista = dt
    r.conta = conta
    r.valor = float(v)
    r.obs = (obs or "").strip() or None

    # ✅ REGRA FINAL
    ym_by_date = _ym_from_date(dt)
    if ym_by_date:
        r.ym = ym_by_date
        ym_redirect = ym_by_date
    else:
        if ym_novo:
            r.ym = ym_novo
            ym_redirect = ym_novo
        else:
            r.ym = ym
            ym_redirect = ym

    db.add(r)
    db.commit()

    return RedirectResponse(url=f"/financeiro/receber?ym={ym_redirect}", status_code=303)


@router.post("/financeiro/receber/{rid}/baixar")
def receber_baixar(
    request: Request,
    rid: int,
    db: Session = Depends(get_db),
    ym: str = Form(...),
    recebido_em: str = Form(""),
    obs: str = Form(""),
):
    redir = _require_auth(request)
    if redir:
        return redir

    ym = _normalize_ym(ym)

    r = db.query(Receivable).filter(Receivable.id == rid).first()
    if not r:
        return RedirectResponse(url=f"/financeiro/receber?ym={ym}", status_code=303)

    dt = _parse_date_any(recebido_em, fallback=None)

    r.recebido = True
    r.recebido_em = dt or date.today()

    obs_new = (obs or "").strip()
    if obs_new:
        r.obs = (r.obs + "\n" if r.obs else "") + obs_new

    db.add(r)
    db.commit()

    return RedirectResponse(url=f"/financeiro/receber?ym={ym}", status_code=303)


@router.post("/financeiro/receber/{rid}/excluir")
def receber_excluir(request: Request, rid: int, db: Session = Depends(get_db), ym: str = Form(...)):
    redir = _require_auth(request)
    if redir:
        return redir

    ym = _normalize_ym(ym)
    r = db.query(Receivable).filter(Receivable.id == rid).first()
    if r:
        db.delete(r)
        db.commit()
    return RedirectResponse(url=f"/financeiro/receber?ym={ym}", status_code=303)


@router.get("/financeiro/receber/relatorio-mes", response_class=HTMLResponse)
def receber_relatorio_mes(request: Request, ym: str | None = None, db: Session = Depends(get_db)):
    redir = _require_auth(request)
    if redir:
        return redir

    ym = _normalize_ym(ym)

    rows = (
        db.query(Receivable)
        .filter(Receivable.ym == ym)
        .order_by(Receivable.data_prevista.asc().nulls_last(), Receivable.parte_autora.asc())
        .all()
    )

    total = sum((r.valor or 0.0) for r in rows)

    contas = ["CONTA_CSL", "CONTA_TARCISIO", "CONTA_ANA", "CONTA_TIAGO"]
    por_conta = []
    for c in contas:
        s = (
            db.query(func.coalesce(func.sum(Receivable.valor), 0.0))
            .filter(Receivable.ym == ym)
            .filter(Receivable.conta == c)
            .scalar()
            or 0.0
        )
        por_conta.append({"conta": c, "label": _conta_label(c), "total": float(s)})

    return templates.TemplateResponse(
        "finance/relatorio_receber_mes.html",
        {
            "request": request,
            "title": "Relatório Contas a Receber (Mês)",
            "ym": ym,
            "rows": rows,
            "total": float(total),
            "por_conta": por_conta,
        },
    )


# ============================
# ✅ RELATÓRIO ANUAL (COM COMPETÊNCIA DE DESPESAS)
# Recebido por COMPETÊNCIA (Receivable.ym)
# Despesas por COMPETÊNCIA (mês anterior ao pagamento: Payable.pago_em - 1 mês)
# ============================
@router.get("/financeiro/receber/relatorio-anual", response_class=HTMLResponse)
def receber_relatorio_anual(request: Request, ano: int | None = None, db: Session = Depends(get_db)):
    redir = _require_auth(request)
    if redir:
        return redir

    hoje = date.today()
    ano = int(ano or hoje.year)

    recebido_por_mes = {m: 0.0 for m in range(1, 13)}
    despesas_por_mes = {m: 0.0 for m in range(1, 13)}

    # 1) RECEBIDOS (fiel ao mensal): recebido=True por competência (ym)
    recebidos_db = (
        db.query(Receivable)
        .filter(Receivable.recebido.is_(True))
        .filter(Receivable.ym.like(f"{ano:04d}-%"))
        .all()
    )
    for r in recebidos_db:
        try:
            mes = int((r.ym or "0000-00")[5:7])
        except Exception:
            continue
        if 1 <= mes <= 12:
            recebido_por_mes[mes] += float(r.valor or 0.0)

    # 2) DESPESAS por competência:
    #    Para competência do ANO:
    #    - pagamentos de FEv/ANO até JAN/(ANO+1) entram no ANO (pois JAN/(ANO+1) => competência DEZ/ANO)
    #    - pagamentos de JAN/ANO pertencem a DEZ/(ANO-1), então NÃO entram no ANO
    dt_ini = date(ano, 2, 1)          # 01/02/ano
    dt_fim = date(ano + 1, 2, 1)      # 01/02/(ano+1)

    payables_db = (
        db.query(Payable)
        .filter(Payable.pago.is_(True))
        .filter(
            or_(
                # ✅ preferencial: por data de pagamento
                and_(Payable.pago_em.isnot(None), Payable.pago_em >= dt_ini, Payable.pago_em < dt_fim),
                # ✅ fallback: registros antigos sem pago_em (usa p.ym como antes)
                and_(Payable.pago_em.is_(None), Payable.ym.like(f"{ano:04d}-%")),
            )
        )
        .all()
    )

    for p in payables_db:
        comp_ym = _competencia_ym_for_payable(p)
        try:
            y_comp = int(comp_ym[:4])
            m_comp = int(comp_ym[5:7])
        except Exception:
            continue

        if y_comp != ano:
            continue
        if 1 <= m_comp <= 12:
            despesas_por_mes[m_comp] += float(p.valor or 0.0)

    meses = []
    chart_labels = []
    chart_recebido = []
    chart_despesas = []
    chart_resultado = []

    for m in range(1, 13):
        ym = f"{ano:04d}-{m:02d}"
        recebido = float(recebido_por_mes.get(m, 0.0))
        despesas = float(despesas_por_mes.get(m, 0.0))
        resultado = float(recebido - despesas)

        meses.append({"ym": ym, "mes": m, "recebido": recebido, "despesas": despesas, "resultado": resultado})

        chart_labels.append(ym)
        chart_recebido.append(recebido)
        chart_despesas.append(despesas)
        chart_resultado.append(resultado)

    total_recebido = sum(x["recebido"] for x in meses)
    total_despesas = sum(x["despesas"] for x in meses)
    total_resultado = sum(x["resultado"] for x in meses)

    return templates.TemplateResponse(
        "finance/relatorio_receber_anual.html",
        {
            "request": request,
            "title": "Comparativo Anual Financeiro",
            "ano": ano,
            "meses": meses,
            "total_recebido": float(total_recebido),
            "total_despesas": float(total_despesas),
            "total_resultado": float(total_resultado),
            "total_recebido_ano": float(total_recebido),
            "total_despesas_ano": float(total_despesas),
            "total_resultado_ano": float(total_resultado),
            "chart_labels": chart_labels,
            "chart_recebido": chart_recebido,
            "chart_despesas": chart_despesas,
            "chart_resultado": chart_resultado,
        },
    )


# ============================
# ✅ RELATÓRIO ANUAL CSL (COM COMPETÊNCIA DE DESPESAS)
# Recebido CSL por COMPETÊNCIA (Receivable.ym)
# Despesas por COMPETÊNCIA (mês anterior ao pagamento)
# ============================
@router.get("/financeiro/receber/relatorio-anual-csl", response_class=HTMLResponse)
def receber_relatorio_anual_csl(request: Request, ano: int | None = None, db: Session = Depends(get_db)):
    redir = _require_auth(request)
    if redir:
        return redir

    hoje = date.today()
    ano = int(ano or hoje.year)

    recebido_csl_por_mes = {m: 0.0 for m in range(1, 13)}
    despesas_por_mes = {m: 0.0 for m in range(1, 13)}

    # 1) RECEBIDOS CSL: recebido=True + conta CSL por competência (ym)
    recebidos_csl_db = (
        db.query(Receivable)
        .filter(Receivable.recebido.is_(True))
        .filter(Receivable.conta == "CONTA_CSL")
        .filter(Receivable.ym.like(f"{ano:04d}-%"))
        .all()
    )
    for r in recebidos_csl_db:
        try:
            mes = int((r.ym or "0000-00")[5:7])
        except Exception:
            continue
        if 1 <= mes <= 12:
            recebido_csl_por_mes[mes] += float(r.valor or 0.0)

    # 2) DESPESAS por competência (mesma regra do anual)
    dt_ini = date(ano, 2, 1)
    dt_fim = date(ano + 1, 2, 1)

    payables_db = (
        db.query(Payable)
        .filter(Payable.pago.is_(True))
        .filter(
            or_(
                and_(Payable.pago_em.isnot(None), Payable.pago_em >= dt_ini, Payable.pago_em < dt_fim),
                and_(Payable.pago_em.is_(None), Payable.ym.like(f"{ano:04d}-%")),
            )
        )
        .all()
    )

    for p in payables_db:
        comp_ym = _competencia_ym_for_payable(p)
        try:
            y_comp = int(comp_ym[:4])
            m_comp = int(comp_ym[5:7])
        except Exception:
            continue

        if y_comp != ano:
            continue
        if 1 <= m_comp <= 12:
            despesas_por_mes[m_comp] += float(p.valor or 0.0)

    meses = []
    chart_labels = []
    chart_recebido_csl = []
    chart_despesas = []
    chart_resultado = []

    for m in range(1, 13):
        ym = f"{ano:04d}-{m:02d}"
        recebido_csl = float(recebido_csl_por_mes.get(m, 0.0))
        despesas = float(despesas_por_mes.get(m, 0.0))
        resultado = float(recebido_csl - despesas)

        meses.append({"ym": ym, "mes": m, "recebido_csl": recebido_csl, "despesas": despesas, "resultado": resultado})

        chart_labels.append(ym)
        chart_recebido_csl.append(recebido_csl)
        chart_despesas.append(despesas)
        chart_resultado.append(resultado)

    total_recebido_csl = sum(x["recebido_csl"] for x in meses)
    total_despesas = sum(x["despesas"] for x in meses)
    total_resultado = sum(x["resultado"] for x in meses)

    return templates.TemplateResponse(
        "finance/receber_anual_csl.html",
        {
            "request": request,
            "title": "Anual CSL x Despesas",
            "ano": ano,
            "meses": meses,
            "total_recebido_csl": float(total_recebido_csl),
            "total_despesas": float(total_despesas),
            "total_resultado": float(total_resultado),
            "chart_labels": chart_labels,
            "chart_recebido_csl": chart_recebido_csl,
            "chart_despesas": chart_despesas,
            "chart_resultado": chart_resultado,
        },
    )