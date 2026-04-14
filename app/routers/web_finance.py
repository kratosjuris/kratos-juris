# app/routers/web_finance.py

import os
import re
import urllib.parse
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.datetime_utils import now_br
from app.core.database import get_db
from app.models.finance_models import (
    FinanceMonth,
    ExpenseTemplate,
    Payable,
    Receivable,
    FinancialAccount,
)

router = APIRouter()

# ✅ Caminho ABSOLUTO dos templates
APP_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = APP_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ----------------------------
# Helpers gerais
# ----------------------------
def _get_office_id(request: Request) -> int:
    office_id = request.session.get("office_id")
    if not office_id:
        raise HTTPException(status_code=403, detail="Usuário sem escritório vinculado.")
    return int(office_id)


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
    hoje = now_br().date()
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

    if "-" in txt:
        try:
            y, m, d = txt.split("-")
            return date(int(y), int(m), int(d))
        except Exception:
            return fallback

    if "/" in txt:
        try:
            d, m, y = txt.split("/")
            return date(int(y), int(m), int(d))
        except Exception:
            return fallback

    return fallback


# =========================================================
# CONTAS FINANCEIRAS DINÂMICAS
# =========================================================
LEGACY_DEFAULT_ACCOUNTS = [
    ("CONTA_CSL", "Conta CSL"),
    ("CONTA_TARCISIO", "Conta Tarcisio"),
    ("CONTA_ANA", "Conta Ana Luisa"),
    ("CONTA_TIAGO", "Conta Tiago"),
]


def _slugify_account_code(nome: str) -> str:
    txt = (nome or "").strip().upper()
    txt = re.sub(r"[^A-Z0-9]+", "_", txt)
    txt = re.sub(r"_+", "_", txt).strip("_")
    if not txt:
        txt = "CONTA"
    if not txt.startswith("CONTA_"):
        txt = f"CONTA_{txt}"
    return txt[:60]


def _ensure_default_accounts(db: Session, office_id: int):
    """
    Cria as contas antigas no banco apenas se não existir nenhuma para o escritório.
    """
    total = (
        db.query(func.count(FinancialAccount.id))
        .filter(FinancialAccount.office_id == office_id)
        .scalar()
        or 0
    )
    if total > 0:
        return

    for code, nome in LEGACY_DEFAULT_ACCOUNTS:
        db.add(FinancialAccount(office_id=office_id, code=code, nome=nome, ativo=True))
    db.commit()


def _get_accounts(db: Session, office_id: int, only_active: bool = True):
    _ensure_default_accounts(db, office_id)

    query = db.query(FinancialAccount).filter(FinancialAccount.office_id == office_id)
    if only_active:
        query = query.filter(FinancialAccount.ativo.is_(True))

    return query.order_by(FinancialAccount.nome.asc()).all()


def _get_account_map(db: Session, office_id: int, include_inactive: bool = True) -> dict[str, FinancialAccount]:
    _ensure_default_accounts(db, office_id)

    query = db.query(FinancialAccount).filter(FinancialAccount.office_id == office_id)
    if not include_inactive:
        query = query.filter(FinancialAccount.ativo.is_(True))

    rows = query.all()
    return {str(a.code): a for a in rows}


def _conta_label(db: Session, office_id: int, code: str) -> str:
    if not code:
        return "Sem conta"

    account_map = _get_account_map(db, office_id, include_inactive=True)
    acc = account_map.get(code)
    if acc:
        return acc.nome

    legacy = dict(LEGACY_DEFAULT_ACCOUNTS)
    return legacy.get(code, code)


def _default_account_code(db: Session, office_id: int) -> str:
    active = _get_accounts(db, office_id, only_active=True)
    if active:
        return active[0].code
    return "CONTA_CSL"


def _is_valid_account_code(db: Session, office_id: int, code: str) -> bool:
    if not code:
        return False
    active_codes = {a.code for a in _get_accounts(db, office_id, only_active=True)}
    return code in active_codes


def _resolve_report_account(
    db: Session,
    office_id: int,
    conta_id: int | None = None,
    conta_code: str | None = None,
) -> FinancialAccount | None:
    _ensure_default_accounts(db, office_id)

    if conta_id:
        acc = (
            db.query(FinancialAccount)
            .filter(
                FinancialAccount.office_id == office_id,
                FinancialAccount.id == conta_id,
            )
            .first()
        )
        if acc:
            return acc

    conta_code = (conta_code or "").strip().upper()
    if conta_code:
        acc = (
            db.query(FinancialAccount)
            .filter(
                FinancialAccount.office_id == office_id,
                func.upper(FinancialAccount.code) == conta_code,
            )
            .first()
        )
        if acc:
            return acc

    acc = (
        db.query(FinancialAccount)
        .filter(
            FinancialAccount.office_id == office_id,
            func.upper(FinancialAccount.code) == "CONTA_CSL",
        )
        .first()
    )
    if acc:
        return acc

    acc = (
        db.query(FinancialAccount)
        .filter(
            FinancialAccount.office_id == office_id,
            FinancialAccount.ativo.is_(True),
        )
        .order_by(FinancialAccount.nome.asc())
        .first()
    )
    if acc:
        return acc

    return (
        db.query(FinancialAccount)
        .filter(FinancialAccount.office_id == office_id)
        .order_by(FinancialAccount.nome.asc())
        .first()
    )


# =========================================================
# ✅ COMPETÊNCIA (DESPESAS)
# Regra oficial:
# pago em janeiro/2026  -> competência dezembro/2025
# pago em fevereiro/2026 -> competência janeiro/2026
# pago em março/2026 -> competência fevereiro/2026
# =========================================================
def _ym_prev(ym: str) -> str:
    try:
        y = int(ym[:4])
        m = int(ym[5:7])
    except Exception:
        return ym

    if m <= 1:
        return f"{y - 1:04d}-12"
    return f"{y:04d}-{m - 1:02d}"


def _competencia_ym_from_payment_date(paid_dt: date | None) -> str | None:
    if not paid_dt:
        return None
    ym_pay = f"{paid_dt.year:04d}-{paid_dt.month:02d}"
    return _ym_prev(ym_pay)


def _competencia_ym_for_payable(p: Payable) -> str | None:
    """
    Só considera competência real via pago_em.
    Sem pago_em, a despesa não entra no breakdown/anual por competência.
    """
    if getattr(p, "pago", False) and getattr(p, "pago_em", None):
        comp = _competencia_ym_from_payment_date(p.pago_em)
        if comp:
            return comp
    return None


def _build_despesas_breakdown(payables_db: list[Payable], ano: int):
    despesas_por_mes = {m: 0.0 for m in range(1, 13)}
    breakdown_map = {m: [] for m in range(1, 13)}

    for p in payables_db:
        comp_ym = _competencia_ym_for_payable(p)
        if not comp_ym:
            continue

        try:
            y_comp = int(comp_ym[:4])
            m_comp = int(comp_ym[5:7])
        except Exception:
            continue

        if y_comp != ano or not (1 <= m_comp <= 12):
            continue

        valor = float(p.valor or 0.0)
        despesas_por_mes[m_comp] += valor

        breakdown_map[m_comp].append(
            {
                "id": p.id,
                "descricao": p.descricao,
                "tipo": p.tipo,
                "valor": valor,
                "vencimento": p.vencimento,
                "pago_em": p.pago_em,
                "competencia_ym": comp_ym,
                "obs": p.obs,
            }
        )

    for m in range(1, 13):
        breakdown_map[m].sort(
            key=lambda item: (
                item["pago_em"] or date.min,
                item["descricao"] or "",
                item["id"],
            )
        )

    breakdown_rows = []
    for m in range(1, 13):
        ym = f"{ano:04d}-{m:02d}"
        items = breakdown_map[m]
        breakdown_rows.append(
            {
                "ym": ym,
                "mes": m,
                "total": float(despesas_por_mes[m]),
                "items": items,
            }
        )

    return despesas_por_mes, breakdown_rows


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
# CRUD DE CONTAS FINANCEIRAS
# ----------------------------
@router.get("/financeiro/contas", response_class=HTMLResponse)
def financeiro_contas(request: Request, db: Session = Depends(get_db)):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)
    contas = _get_accounts(db, office_id, only_active=False)

    return templates.TemplateResponse(
        "finance/contas.html",
        {
            "request": request,
            "title": "Contas Financeiras",
            "contas": contas,
        },
    )


@router.post("/financeiro/contas/nova")
def financeiro_conta_nova(
    request: Request,
    db: Session = Depends(get_db),
    nome: str = Form(...),
    code: str = Form(""),
):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)

    nome = (nome or "").strip()
    if not nome:
        return RedirectResponse(url="/financeiro/contas", status_code=303)

    code = (code or "").strip().upper() or _slugify_account_code(nome)

    existe_code = (
        db.query(FinancialAccount)
        .filter(
            FinancialAccount.office_id == office_id,
            func.upper(FinancialAccount.code) == code.upper(),
        )
        .first()
    )
    if existe_code:
        return RedirectResponse(url="/financeiro/contas", status_code=303)

    existe_nome = (
        db.query(FinancialAccount)
        .filter(
            FinancialAccount.office_id == office_id,
            func.lower(FinancialAccount.nome) == nome.lower(),
        )
        .first()
    )
    if existe_nome:
        if not bool(existe_nome.ativo):
            existe_nome.ativo = True
            db.add(existe_nome)
            db.commit()
        return RedirectResponse(url="/financeiro/contas", status_code=303)

    db.add(FinancialAccount(office_id=office_id, code=code, nome=nome, ativo=True))
    db.commit()
    return RedirectResponse(url="/financeiro/contas", status_code=303)


@router.post("/financeiro/contas/{cid}/editar")
def financeiro_conta_editar(
    request: Request,
    cid: int,
    db: Session = Depends(get_db),
    nome: str = Form(...),
    ativo: str = Form("1"),
):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)

    conta = (
        db.query(FinancialAccount)
        .filter(
            FinancialAccount.office_id == office_id,
            FinancialAccount.id == cid,
        )
        .first()
    )
    if not conta:
        return RedirectResponse(url="/financeiro/contas", status_code=303)

    nome = (nome or "").strip()
    if nome:
        conta.nome = nome
    conta.ativo = ativo == "1"

    db.add(conta)
    db.commit()
    return RedirectResponse(url="/financeiro/contas", status_code=303)


@router.post("/financeiro/contas/{cid}/excluir")
def financeiro_conta_excluir(request: Request, cid: int, db: Session = Depends(get_db)):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)

    conta = (
        db.query(FinancialAccount)
        .filter(
            FinancialAccount.office_id == office_id,
            FinancialAccount.id == cid,
        )
        .first()
    )
    if not conta:
        return RedirectResponse(url="/financeiro/contas", status_code=303)

    uso = (
        db.query(func.count(Receivable.id))
        .filter(
            Receivable.office_id == office_id,
            Receivable.conta == conta.code,
        )
        .scalar()
        or 0
    )

    if uso > 0:
        conta.ativo = False
        db.add(conta)
        db.commit()
    else:
        db.delete(conta)
        db.commit()

    return RedirectResponse(url="/financeiro/contas", status_code=303)


# ----------------------------
# Contas a Pagar
# ----------------------------
def _get_or_create_month(db: Session, office_id: int, ym: str) -> FinanceMonth:
    m = (
        db.query(FinanceMonth)
        .filter(
            FinanceMonth.office_id == office_id,
            FinanceMonth.ym == ym,
        )
        .first()
    )
    if not m:
        m = FinanceMonth(office_id=office_id, ym=ym, saldo_inicial=0.0)
        db.add(m)
        db.commit()
        db.refresh(m)
    return m


def _parse_ids_csv(raw: str | None) -> list[int]:
    if not raw:
        return []
    ids: list[int] = []
    seen = set()

    for part in str(raw).split(","):
        txt = part.strip()
        if not txt or not txt.isdigit():
            continue
        pid = int(txt)
        if pid not in seen:
            seen.add(pid)
            ids.append(pid)
    return ids


@router.get("/financeiro/pagar", response_class=HTMLResponse)
def pagar_list(request: Request, ym: str | None = None, db: Session = Depends(get_db)):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)
    month = _get_or_create_month(db, office_id, ym)

    payables = (
        db.query(Payable)
        .filter(
            Payable.office_id == office_id,
            Payable.ym == ym,
        )
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
        .filter(ExpenseTemplate.office_id == office_id)
        .order_by(ExpenseTemplate.tipo.asc(), ExpenseTemplate.nome.asc())
        .all()
    )

    contas_ativas = _get_accounts(db, office_id, only_active=True)

    return templates.TemplateResponse(
        "finance/pagar.html",
        {
            "request": request,
            "title": "Contas a Pagar",
            "ym": ym,
            "month": month,
            "payables": payables,
            "templates_list": templates_list,
            "contas_ativas": contas_ativas,
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

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)
    m = _get_or_create_month(db, office_id, ym)

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

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)

    if template_id.strip().isdigit():
        t = (
            db.query(ExpenseTemplate)
            .filter(
                ExpenseTemplate.office_id == office_id,
                ExpenseTemplate.id == int(template_id),
            )
            .first()
        )
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
        office_id=office_id,
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
            existe = (
                db.query(ExpenseTemplate)
                .filter(
                    ExpenseTemplate.office_id == office_id,
                    func.lower(ExpenseTemplate.nome) == nome_modelo.lower(),
                )
                .first()
            )
            if not existe:
                db.add(
                    ExpenseTemplate(
                        office_id=office_id,
                        nome=nome_modelo,
                        tipo=(tipo or "FIXA").upper().strip(),
                        valor_padrao=float(v),
                        observacao=(obs or "").strip() or None,
                    )
                )

    db.commit()
    return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)


@router.post("/financeiro/pagar/lote/baixar")
def pagar_baixar_lote(
    request: Request,
    db: Session = Depends(get_db),
    ym: str = Form(...),
    selected_ids: str = Form(""),
    pago_em: str = Form(""),
):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)
    ids = _parse_ids_csv(selected_ids)

    if not ids:
        return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)

    dt_pagamento = _parse_date_any(pago_em, fallback=None) or now_br().date()

    rows = (
        db.query(Payable)
        .filter(
            Payable.office_id == office_id,
            Payable.id.in_(ids),
        )
        .all()
    )

    for p in rows:
        p.pago = True
        p.pago_em = dt_pagamento
        db.add(p)

    db.commit()
    return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)


@router.post("/financeiro/pagar/lote/desfazer")
def pagar_desfazer_lote(
    request: Request,
    db: Session = Depends(get_db),
    ym: str = Form(...),
    selected_ids: str = Form(""),
):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)
    ids = _parse_ids_csv(selected_ids)

    if not ids:
        return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)

    rows = (
        db.query(Payable)
        .filter(
            Payable.office_id == office_id,
            Payable.id.in_(ids),
        )
        .all()
    )

    for p in rows:
        p.pago = False
        p.pago_em = None
        db.add(p)

    db.commit()
    return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)


@router.post("/financeiro/pagar/{pid}/toggle")
def pagar_toggle(request: Request, pid: int, db: Session = Depends(get_db), ym: str = Form(...)):
    """
    Compatibilidade antiga.
    O fluxo recomendado é usar /baixar, /desfazer e /editar-pagamento.
    """
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)
    p = (
        db.query(Payable)
        .filter(
            Payable.office_id == office_id,
            Payable.id == pid,
        )
        .first()
    )
    if p:
        if p.pago:
            p.pago = False
            p.pago_em = None
        else:
            p.pago = True
            p.pago_em = now_br().date()
        db.add(p)
        db.commit()
    return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)


@router.post("/financeiro/pagar/{pid}/baixar")
def pagar_baixar(
    request: Request,
    pid: int,
    db: Session = Depends(get_db),
    ym: str = Form(...),
    pago_em: str = Form(""),
):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)

    p = (
        db.query(Payable)
        .filter(
            Payable.office_id == office_id,
            Payable.id == pid,
        )
        .first()
    )
    if not p:
        return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)

    dt_pagamento = _parse_date_any(pago_em, fallback=None) or now_br().date()

    p.pago = True
    p.pago_em = dt_pagamento

    db.add(p)
    db.commit()
    return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)


@router.post("/financeiro/pagar/{pid}/desfazer")
def pagar_desfazer(
    request: Request,
    pid: int,
    db: Session = Depends(get_db),
    ym: str = Form(...),
):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)

    p = (
        db.query(Payable)
        .filter(
            Payable.office_id == office_id,
            Payable.id == pid,
        )
        .first()
    )
    if p:
        p.pago = False
        p.pago_em = None
        db.add(p)
        db.commit()

    return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)


@router.post("/financeiro/pagar/{pid}/editar-pagamento")
def pagar_editar_pagamento(
    request: Request,
    pid: int,
    db: Session = Depends(get_db),
    ym: str = Form(...),
    pago_em: str = Form(""),
):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)

    p = (
        db.query(Payable)
        .filter(
            Payable.office_id == office_id,
            Payable.id == pid,
        )
        .first()
    )
    if not p:
        return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)

    dt_pagamento = _parse_date_any(pago_em, fallback=p.pago_em) or now_br().date()

    p.pago = True
    p.pago_em = dt_pagamento

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

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)
    p = (
        db.query(Payable)
        .filter(
            Payable.office_id == office_id,
            Payable.id == pid,
        )
        .first()
    )
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

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)
    p = (
        db.query(Payable)
        .filter(
            Payable.office_id == office_id,
            Payable.id == pid,
        )
        .first()
    )
    if p:
        db.delete(p)
        db.commit()
    return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)


@router.post("/financeiro/pagar/modelo/{tid}/editar")
def pagar_modelo_editar(
    request: Request,
    tid: int,
    db: Session = Depends(get_db),
    ym: str = Form(_ym_default()),
    nome: str = Form(...),
    tipo: str = Form("FIXA"),
    valor_padrao: str = Form("0"),
    observacao: str = Form(""),
):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)

    t = (
        db.query(ExpenseTemplate)
        .filter(
            ExpenseTemplate.office_id == office_id,
            ExpenseTemplate.id == tid,
        )
        .first()
    )
    if not t:
        ym = _normalize_ym(ym)
        return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)

    nome_limpo = (nome or "").strip()
    if not nome_limpo:
        ym = _normalize_ym(ym)
        return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)

    valor_num = _parse_brl_number(valor_padrao or "0")

    t.nome = nome_limpo
    t.tipo = (tipo or "FIXA").upper().strip()
    t.valor_padrao = float(valor_num)
    t.observacao = (observacao or "").strip() or None

    db.add(t)
    db.commit()

    ym = _normalize_ym(ym)
    return RedirectResponse(url=f"/financeiro/pagar?ym={ym}", status_code=303)


@router.post("/financeiro/pagar/modelo/{tid}/excluir")
def pagar_modelo_excluir(request: Request, tid: int, db: Session = Depends(get_db), ym: str = Form(_ym_default())):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)
    t = (
        db.query(ExpenseTemplate)
        .filter(
            ExpenseTemplate.office_id == office_id,
            ExpenseTemplate.id == tid,
        )
        .first()
    )
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

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)
    month = _get_or_create_month(db, office_id, ym)

    payables = (
        db.query(Payable)
        .filter(
            Payable.office_id == office_id,
            Payable.ym == ym,
        )
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

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)
    status = (status or "").strip()
    q = (q or "").strip()

    account_map = _get_account_map(db, office_id, include_inactive=True)
    active_accounts = _get_accounts(db, office_id, only_active=True)

    query = db.query(Receivable).filter(
        Receivable.office_id == office_id,
        Receivable.ym == ym,
    )

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

    hoje = now_br().date()
    rows = []
    used_codes = set()

    for r in rows_db:
        valor = float(r.valor or 0.0)
        em_atraso = (not r.recebido) and bool(r.data_prevista) and (r.data_prevista < hoje)
        used_codes.add(r.conta)

        acc = account_map.get(r.conta)
        conta_label = acc.nome if acc else r.conta

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
                "conta_label": conta_label,
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
        .filter(
            Receivable.office_id == office_id,
            Receivable.ym == ym_prev,
        )
        .scalar()
        or 0.0
    )

    por_conta_codes = {a.code for a in active_accounts} | used_codes
    por_conta = []

    for code in sorted(por_conta_codes, key=lambda c: _conta_label(db, office_id, c).lower()):
        s = sum((r["valor"] or 0.0) for r in rows if r["conta"] == code)
        por_conta.append({"conta": code, "label": _conta_label(db, office_id, code), "total": float(s)})

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
            "contas_ativas": active_accounts,
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
    conta: str = Form(""),
    valor: str = Form("0"),
    obs: str = Form(""),
):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)
    v = _parse_brl_number(valor or "0")
    dt = _parse_date_any(data_prevista, fallback=None)

    ym_by_date = _ym_from_date(dt)
    if ym_by_date:
        ym = ym_by_date

    conta = (conta or "").upper().strip()
    if not _is_valid_account_code(db, office_id, conta):
        conta = _default_account_code(db, office_id)

    r = Receivable(
        office_id=office_id,
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

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)
    r = (
        db.query(Receivable)
        .filter(
            Receivable.office_id == office_id,
            Receivable.id == rid,
        )
        .first()
    )
    if r:
        r.recebido = not bool(r.recebido)
        r.recebido_em = now_br().date() if r.recebido else None
        db.add(r)
        db.commit()
    return RedirectResponse(url=f"/financeiro/receber?ym={ym}", status_code=303)


@router.post("/financeiro/receber/{rid}/editar")
def receber_editar(
    request: Request,
    rid: int,
    db: Session = Depends(get_db),
    ym: str = Form(...),
    ym_novo: str = Form(""),
    numero_processo: str = Form(...),
    parte_autora: str = Form(...),
    vara: str = Form(...),
    data_prevista: str = Form(""),
    conta: str = Form(""),
    valor: str = Form("0"),
    obs: str = Form(""),
):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)
    ym_novo = _normalize_ym(ym_novo) if (ym_novo or "").strip() else ""

    r = (
        db.query(Receivable)
        .filter(
            Receivable.office_id == office_id,
            Receivable.id == rid,
        )
        .first()
    )
    if not r:
        return RedirectResponse(url=f"/financeiro/receber?ym={ym}", status_code=303)

    v = _parse_brl_number(valor or str(r.valor or 0.0))
    dt = _parse_date_any(data_prevista, fallback=r.data_prevista)

    conta = (conta or "").upper().strip()
    if not _is_valid_account_code(db, office_id, conta):
        conta = r.conta or _default_account_code(db, office_id)

    r.numero_processo = (numero_processo or "").strip()
    r.parte_autora = (parte_autora or "").strip()
    r.vara = (vara or "").strip()
    r.data_prevista = dt
    r.conta = conta
    r.valor = float(v)
    r.obs = (obs or "").strip() or None

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

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)

    r = (
        db.query(Receivable)
        .filter(
            Receivable.office_id == office_id,
            Receivable.id == rid,
        )
        .first()
    )
    if not r:
        return RedirectResponse(url=f"/financeiro/receber?ym={ym}", status_code=303)

    dt = _parse_date_any(recebido_em, fallback=None)

    r.recebido = True
    r.recebido_em = dt or now_br().date()

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

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)
    r = (
        db.query(Receivable)
        .filter(
            Receivable.office_id == office_id,
            Receivable.id == rid,
        )
        .first()
    )
    if r:
        db.delete(r)
        db.commit()
    return RedirectResponse(url=f"/financeiro/receber?ym={ym}", status_code=303)


@router.get("/financeiro/receber/relatorio-mes", response_class=HTMLResponse)
def receber_relatorio_mes(request: Request, ym: str | None = None, db: Session = Depends(get_db)):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)
    ym = _normalize_ym(ym)

    rows = (
        db.query(Receivable)
        .filter(
            Receivable.office_id == office_id,
            Receivable.ym == ym,
        )
        .order_by(Receivable.data_prevista.asc().nulls_last(), Receivable.parte_autora.asc())
        .all()
    )

    total = sum((r.valor or 0.0) for r in rows)

    used_codes = {r.conta for r in rows if r.conta}
    active_codes = {a.code for a in _get_accounts(db, office_id, only_active=True)}
    all_codes = used_codes | active_codes

    por_conta = []
    for c in sorted(all_codes, key=lambda code: _conta_label(db, office_id, code).lower()):
        s = (
            db.query(func.coalesce(func.sum(Receivable.valor), 0.0))
            .filter(
                Receivable.office_id == office_id,
                Receivable.ym == ym,
                Receivable.conta == c,
            )
            .scalar()
            or 0.0
        )
        por_conta.append({"conta": c, "label": _conta_label(db, office_id, c), "total": float(s)})

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
# ✅ RELATÓRIO ANUAL
# ============================
@router.get("/financeiro/receber/relatorio-anual", response_class=HTMLResponse)
def receber_relatorio_anual(request: Request, ano: int | None = None, db: Session = Depends(get_db)):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)
    hoje = now_br().date()
    ano = int(ano or hoje.year)

    recebido_por_mes = {m: 0.0 for m in range(1, 13)}

    recebidos_db = (
        db.query(Receivable)
        .filter(
            Receivable.office_id == office_id,
            Receivable.recebido.is_(True),
            Receivable.ym.like(f"{ano:04d}-%"),
        )
        .all()
    )
    for r in recebidos_db:
        try:
            mes = int((r.ym or "0000-00")[5:7])
        except Exception:
            continue
        if 1 <= mes <= 12:
            recebido_por_mes[mes] += float(r.valor or 0.0)

    # Para o ano de competência:
    # entram pagamentos de 01/02/ANO até 31/01/(ANO+1)
    dt_ini = date(ano, 2, 1)
    dt_fim = date(ano + 1, 2, 1)

    payables_db = (
        db.query(Payable)
        .filter(
            Payable.office_id == office_id,
            Payable.pago.is_(True),
            Payable.pago_em.isnot(None),
            Payable.pago_em >= dt_ini,
            Payable.pago_em < dt_fim,
        )
        .order_by(Payable.pago_em.asc(), Payable.descricao.asc())
        .all()
    )

    despesas_por_mes, despesas_breakdown = _build_despesas_breakdown(payables_db, ano)

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
            "despesas_breakdown": despesas_breakdown,
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
# ✅ RELATÓRIO ANUAL CONTA PRINCIPAL x DESPESAS
# ============================
@router.get("/financeiro/receber/relatorio-anual-csl", response_class=HTMLResponse)
@router.get("/financeiro/receber/relatorio-anual-conta-principal", response_class=HTMLResponse)
def receber_relatorio_anual_conta_principal(
    request: Request,
    ano: int | None = None,
    conta_id: int | None = None,
    conta: str | None = None,
    db: Session = Depends(get_db),
):
    redir = _require_auth(request)
    if redir:
        return redir

    office_id = _get_office_id(request)
    hoje = now_br().date()
    ano = int(ano or hoje.year)

    contas = _get_accounts(db, office_id, only_active=True)
    conta_escolhida = _resolve_report_account(db, office_id, conta_id=conta_id, conta_code=conta)

    conta_code = conta_escolhida.code if conta_escolhida else _default_account_code(db, office_id)
    conta_nome = conta_escolhida.nome if conta_escolhida else _conta_label(db, office_id, conta_code)
    conta_escolhida_id = conta_escolhida.id if conta_escolhida else None

    recebido_principal_por_mes = {m: 0.0 for m in range(1, 13)}

    recebidos_principal_db = (
        db.query(Receivable)
        .filter(
            Receivable.office_id == office_id,
            Receivable.recebido.is_(True),
            Receivable.conta == conta_code,
            Receivable.ym.like(f"{ano:04d}-%"),
        )
        .all()
    )

    for r in recebidos_principal_db:
        try:
            mes = int((r.ym or "0000-00")[5:7])
        except Exception:
            continue
        if 1 <= mes <= 12:
            recebido_principal_por_mes[mes] += float(r.valor or 0.0)

    dt_ini = date(ano, 2, 1)
    dt_fim = date(ano + 1, 2, 1)

    payables_db = (
        db.query(Payable)
        .filter(
            Payable.office_id == office_id,
            Payable.pago.is_(True),
            Payable.pago_em.isnot(None),
            Payable.pago_em >= dt_ini,
            Payable.pago_em < dt_fim,
        )
        .order_by(Payable.pago_em.asc(), Payable.descricao.asc())
        .all()
    )

    despesas_por_mes, despesas_breakdown = _build_despesas_breakdown(payables_db, ano)

    meses = []
    chart_labels = []
    chart_recebido_principal = []
    chart_despesas = []
    chart_resultado = []

    for m in range(1, 13):
        ym = f"{ano:04d}-{m:02d}"
        recebido_principal = float(recebido_principal_por_mes.get(m, 0.0))
        despesas = float(despesas_por_mes.get(m, 0.0))
        resultado = float(recebido_principal - despesas)

        meses.append(
            {
                "ym": ym,
                "mes": m,
                "recebido_principal": recebido_principal,
                "despesas": despesas,
                "resultado": resultado,
            }
        )

        chart_labels.append(ym)
        chart_recebido_principal.append(recebido_principal)
        chart_despesas.append(despesas)
        chart_resultado.append(resultado)

    total_recebido_principal = sum(x["recebido_principal"] for x in meses)
    total_despesas = sum(x["despesas"] for x in meses)
    total_resultado = sum(x["resultado"] for x in meses)

    return templates.TemplateResponse(
        "finance/relatorio_anual_conta_principal.html",
        {
            "request": request,
            "title": f"Anual {conta_nome} x Despesas",
            "ano": ano,
            "contas": contas,
            "conta_principal_id": conta_escolhida_id,
            "conta_principal_nome": conta_nome,
            "conta_principal_code": conta_code,
            "meses": meses,
            "despesas_breakdown": despesas_breakdown,
            "total_recebido_principal": float(total_recebido_principal),
            "total_despesas": float(total_despesas),
            "total_resultado": float(total_resultado),
            "chart_labels": chart_labels,
            "chart_recebido_principal": chart_recebido_principal,
            "chart_despesas": chart_despesas,
            "chart_resultado": chart_resultado,
        },
    )