from datetime import date
import re

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.client import Client

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# =========================
# HELPERS
# =========================
def _redirect_denied():
    return RedirectResponse(url="/acesso-negado", status_code=303)


# =========================
# ✅ CPF: normalização + checagem duplicidade
# =========================
_CPF_ONLY_DIGITS_RE = re.compile(r"\D+")


def _only_digits(s: str | None) -> str:
    return _CPF_ONLY_DIGITS_RE.sub("", (s or "").strip())


def _norm_cpf_if_valid(cpf_cnpj: str | None) -> str | None:
    """
    Regra do escritório: evitar duplicidade por CPF.
    - Normaliza para só dígitos
    - Considera CPF para regra de duplicidade se tiver 11 dígitos
    """
    d = _only_digits(cpf_cnpj)
    if len(d) == 11:
        return d
    return None


def _store_doc_normalized(cpf_cnpj: str | None) -> str | None:
    """
    Guarda o documento de forma padronizada:
    - se vier vazio -> None
    - se vier com máscara -> guarda só dígitos
    """
    d = _only_digits(cpf_cnpj)
    return d or None


def _cpf_exists(db: Session, cpf_norm: str, ignore_client_id: int | None = None) -> bool:
    """
    ✅ CORREÇÃO DEFINITIVA:
    Alguns CPFs antigos podem estar salvos com máscara no banco.
    Aqui nós comparamos SEMPRE em forma normalizada (só dígitos),
    do lado do Python, garantindo que:
      "123.456.789-09" == "12345678909"
    """
    if not cpf_norm:
        return False

    q = db.query(Client).filter(Client.cpf_cnpj.isnot(None))
    if ignore_client_id is not None:
        q = q.filter(Client.id != ignore_client_id)

    for c in q.all():
        stored = _only_digits(getattr(c, "cpf_cnpj", None))
        if stored == cpf_norm:
            return True

    return False


def _set_flash(request: Request, key: str, message: str) -> None:
    try:
        request.session[key] = message
    except Exception:
        pass


def _pop_flash(request: Request, key: str) -> str | None:
    try:
        return request.session.pop(key, None)
    except Exception:
        return None


# =========================
# LISTAR CLIENTES
# =========================
@router.get("/clientes", response_class=HTMLResponse)
def clientes_list(request: Request, q: str = "", db: Session = Depends(get_db)):
    try:
        require_permission(request, "clientes.view")
    except HTTPException:
        return _redirect_denied()

    query = db.query(Client)
    if q.strip():
        query = query.filter(Client.nome.ilike(f"%{q.strip()}%"))
    clientes = query.order_by(Client.nome.asc()).all()

    msg = _pop_flash(request, "clientes_msg")

    return templates.TemplateResponse(
        "clients/list.html",
        {
            "request": request,
            "title": "Clientes",
            "clientes": clientes,
            "q": q,
            "msg": msg,
        },
    )


# =========================
# FORM NOVO CLIENTE
# =========================
@router.get("/clientes/novo", response_class=HTMLResponse)
def clientes_novo_form(request: Request):
    try:
        require_permission(request, "clientes.create")
    except HTTPException:
        return _redirect_denied()

    msg = _pop_flash(request, "clientes_msg")
    return templates.TemplateResponse(
        "clients/form.html",
        {
            "request": request,
            "title": "Novo Cliente",
            "cliente": None,
            "msg": msg,
        },
    )


# =========================
# CRIAR CLIENTE
# =========================
@router.post("/clientes/novo")
def clientes_novo(
    request: Request,
    nome: str = Form(...),
    cpf_cnpj: str = Form(""),
    rg: str = Form(""),
    ssp_uf: str = Form(""),
    estado_civil: str = Form(""),
    profissao: str = Form(""),
    telefone: str = Form(""),
    email: str = Form(""),
    endereco: str = Form(""),
    nascimento: str = Form(""),
    obs: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        require_permission(request, "clientes.create")
    except HTTPException:
        return _redirect_denied()

    nasc = None
    if nascimento.strip():
        y, m, d = nascimento.split("-")
        nasc = date(int(y), int(m), int(d))

    cpf_norm = _norm_cpf_if_valid(cpf_cnpj)
    cpf_store = _store_doc_normalized(cpf_cnpj)

    if cpf_norm and _cpf_exists(db, cpf_norm):
        _set_flash(request, "clientes_msg", "Já existe um cliente cadastrado com este CPF.")
        return RedirectResponse(url="/clientes/novo", status_code=303)

    cliente = Client(
        nome=nome.strip(),
        cpf_cnpj=cpf_store,
        rg=rg.strip() or None,
        ssp_uf=ssp_uf.strip() or None,
        estado_civil=estado_civil.strip() or None,
        profissao=profissao.strip() or None,
        telefone=telefone.strip() or None,
        email=email.strip() or None,
        endereco=endereco.strip() or None,
        nascimento=nasc,
        obs=obs.strip() or None,
    )

    db.add(cliente)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        _set_flash(request, "clientes_msg", "Já existe um cliente cadastrado com este CPF.")
        return RedirectResponse(url="/clientes/novo", status_code=303)

    return RedirectResponse(url="/clientes", status_code=303)


# =========================
# FORM EDITAR CLIENTE
# =========================
@router.get("/clientes/{client_id}/editar", response_class=HTMLResponse)
def clientes_editar_form(request: Request, client_id: int, db: Session = Depends(get_db)):
    try:
        require_permission(request, "clientes.edit")
    except HTTPException:
        return _redirect_denied()

    cliente = db.query(Client).filter(Client.id == client_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    msg = _pop_flash(request, "clientes_msg")

    return templates.TemplateResponse(
        "clients/form.html",
        {
            "request": request,
            "title": "Editar Cliente",
            "cliente": cliente,
            "msg": msg,
        },
    )


# =========================
# SALVAR EDIÇÃO CLIENTE
# =========================
@router.post("/clientes/{client_id}/editar")
def clientes_editar(
    request: Request,
    client_id: int,
    nome: str = Form(...),
    cpf_cnpj: str = Form(""),
    rg: str = Form(""),
    ssp_uf: str = Form(""),
    estado_civil: str = Form(""),
    profissao: str = Form(""),
    telefone: str = Form(""),
    email: str = Form(""),
    endereco: str = Form(""),
    nascimento: str = Form(""),
    obs: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        require_permission(request, "clientes.edit")
    except HTTPException:
        return _redirect_denied()

    cliente = db.query(Client).filter(Client.id == client_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    nasc = None
    if nascimento.strip():
        y, m, d = nascimento.split("-")
        nasc = date(int(y), int(m), int(d))

    cpf_norm = _norm_cpf_if_valid(cpf_cnpj)
    cpf_store = _store_doc_normalized(cpf_cnpj)

    if cpf_norm and _cpf_exists(db, cpf_norm, ignore_client_id=client_id):
        _set_flash(
            request,
            "clientes_msg",
            "Não foi possível salvar: este CPF já está cadastrado em outro cliente.",
        )
        return RedirectResponse(url=f"/clientes/{client_id}/editar", status_code=303)

    cliente.nome = nome.strip()
    cliente.cpf_cnpj = cpf_store

    cliente.rg = rg.strip() or None
    cliente.ssp_uf = ssp_uf.strip() or None
    cliente.estado_civil = estado_civil.strip() or None
    cliente.profissao = profissao.strip() or None

    cliente.telefone = telefone.strip() or None
    cliente.email = email.strip() or None
    cliente.endereco = endereco.strip() or None
    cliente.nascimento = nasc
    cliente.obs = obs.strip() or None

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        _set_flash(
            request,
            "clientes_msg",
            "Não foi possível salvar: este CPF já está cadastrado em outro cliente.",
        )
        return RedirectResponse(url=f"/clientes/{client_id}/editar", status_code=303)

    return RedirectResponse(url="/clientes", status_code=303)


# =========================
# EXCLUIR CLIENTE
# =========================
@router.post("/clientes/{client_id}/excluir")
def clientes_excluir(request: Request, client_id: int, db: Session = Depends(get_db)):
    try:
        require_permission(request, "clientes.delete")
    except HTTPException:
        return _redirect_denied()

    cliente = db.query(Client).filter(Client.id == client_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    db.delete(cliente)
    db.commit()
    return RedirectResponse(url="/clientes", status_code=303)