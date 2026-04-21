from datetime import date, datetime
from zoneinfo import ZoneInfo
import re
import secrets

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.client import Client
from app.models.client_invite import ClientInvite

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

TZ_BR = ZoneInfo("America/Sao_Paulo")


def now_br():
    return datetime.now(TZ_BR).replace(tzinfo=None)


# =========================
# HELPERS
# =========================
def _redirect_denied():
    return RedirectResponse(url="/acesso-negado", status_code=303)


def _get_office_id(request: Request) -> int:
    office_id = request.session.get("office_id")
    if not office_id:
        raise HTTPException(status_code=403, detail="Usuário sem escritório vinculado.")
    return int(office_id)


def _parse_birth_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None

    try:
        y, m, d = value.split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        raise ValueError("Data de nascimento inválida.")


# =========================
# CPF HELPERS
# =========================
_CPF_ONLY_DIGITS_RE = re.compile(r"\D+")


def _only_digits(s: str | None) -> str:
    return _CPF_ONLY_DIGITS_RE.sub("", (s or "").strip())


def _norm_cpf_if_valid(cpf_cnpj: str | None) -> str | None:
    d = _only_digits(cpf_cnpj)
    if len(d) == 11:
        return d
    return None


def _store_doc_normalized(cpf_cnpj: str | None) -> str | None:
    d = _only_digits(cpf_cnpj)
    return d or None


def _cpf_exists(
    db: Session,
    cpf_norm: str,
    office_id: int,
    ignore_client_id: int | None = None,
) -> bool:
    if not cpf_norm:
        return False

    q = db.query(Client).filter(
        Client.cpf_cnpj.isnot(None),
        Client.office_id == office_id,
    )

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


def _build_public_register_link(request: Request, token: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/clientes/cadastro/{token}"


def _get_invite_by_token(db: Session, token: str) -> ClientInvite | None:
    return db.query(ClientInvite).filter(ClientInvite.token == token).first()


# =========================
# LISTAR CLIENTES
# =========================
@router.get("/clientes", response_class=HTMLResponse)
def clientes_list(request: Request, q: str = "", db: Session = Depends(get_db)):
    try:
        require_permission(request, "clientes.view")
    except HTTPException:
        return _redirect_denied()

    office_id = _get_office_id(request)

    query = db.query(Client).filter(Client.office_id == office_id)

    if q.strip():
        query = query.filter(Client.nome.ilike(f"%{q.strip()}%"))

    clientes = query.order_by(Client.nome.asc()).all()

    msg = _pop_flash(request, "clientes_msg")
    invite_link = _pop_flash(request, "clientes_invite_link")

    return templates.TemplateResponse(
        "clients/list.html",
        {
            "request": request,
            "title": "Clientes",
            "clientes": clientes,
            "q": q,
            "msg": msg,
            "invite_link": invite_link,
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

    office_id = _get_office_id(request)

    try:
        nasc = _parse_birth_date(nascimento)
    except ValueError:
        _set_flash(request, "clientes_msg", "Data de nascimento inválida.")
        return RedirectResponse(url="/clientes/novo", status_code=303)

    cpf_norm = _norm_cpf_if_valid(cpf_cnpj)
    cpf_store = _store_doc_normalized(cpf_cnpj)

    if cpf_norm and _cpf_exists(db, cpf_norm, office_id):
        _set_flash(request, "clientes_msg", "Já existe um cliente cadastrado com este CPF.")
        return RedirectResponse(url="/clientes/novo", status_code=303)

    cliente = Client(
        office_id=office_id,
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

    office_id = _get_office_id(request)

    cliente = db.query(Client).filter(
        Client.id == client_id,
        Client.office_id == office_id,
    ).first()

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

    office_id = _get_office_id(request)

    cliente = db.query(Client).filter(
        Client.id == client_id,
        Client.office_id == office_id,
    ).first()

    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    try:
        nasc = _parse_birth_date(nascimento)
    except ValueError:
        _set_flash(request, "clientes_msg", "Data de nascimento inválida.")
        return RedirectResponse(url=f"/clientes/{client_id}/editar", status_code=303)

    cpf_norm = _norm_cpf_if_valid(cpf_cnpj)
    cpf_store = _store_doc_normalized(cpf_cnpj)

    if cpf_norm and _cpf_exists(db, cpf_norm, office_id, ignore_client_id=client_id):
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

    office_id = _get_office_id(request)

    cliente = db.query(Client).filter(
        Client.id == client_id,
        Client.office_id == office_id,
    ).first()

    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    db.delete(cliente)
    db.commit()

    return RedirectResponse(url="/clientes", status_code=303)


# =========================
# GERAR LINK ÚNICO DE CADASTRO
# =========================
@router.post("/clientes/gerar-link-cadastro")
def clientes_gerar_link_cadastro(request: Request, db: Session = Depends(get_db)):
    try:
        require_permission(request, "clientes.create")
    except HTTPException:
        return _redirect_denied()

    office_id = _get_office_id(request)

    token = secrets.token_urlsafe(32)

    invite = ClientInvite(
        token=token,
        office_id=office_id,
        used=False,
        created_at=now_br(),
        used_at=None,
    )

    db.add(invite)
    db.commit()
    db.refresh(invite)

    link = _build_public_register_link(request, invite.token)

    _set_flash(request, "clientes_msg", "Link de cadastro gerado com sucesso.")
    _set_flash(request, "clientes_invite_link", link)

    return RedirectResponse(url="/clientes", status_code=303)


# =========================
# FORMULÁRIO PÚBLICO DO CLIENTE
# =========================
@router.get("/clientes/cadastro/{token}", response_class=HTMLResponse)
def cliente_cadastro_publico_form(token: str, request: Request, db: Session = Depends(get_db)):
    invite = _get_invite_by_token(db, token)

    if not invite:
        return templates.TemplateResponse(
            "clients/public_form_result.html",
            {
                "request": request,
                "title": "Cadastro de Cliente",
                "success": False,
                "message": "Link inválido.",
            },
            status_code=404,
        )

    if invite.used:
        return templates.TemplateResponse(
            "clients/public_form_result.html",
            {
                "request": request,
                "title": "Cadastro de Cliente",
                "success": False,
                "message": "Este link já foi utilizado e não está mais disponível.",
            },
            status_code=400,
        )

    return templates.TemplateResponse(
        "clients/public_form.html",
        {
            "request": request,
            "title": "Cadastro de Cliente",
            "token": token,
            "msg": None,
        },
    )


# =========================
# SALVAR CADASTRO PÚBLICO DO CLIENTE
# =========================
@router.post("/clientes/cadastro/{token}", response_class=HTMLResponse)
def cliente_cadastro_publico_salvar(
    token: str,
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
    invite = _get_invite_by_token(db, token)

    if not invite:
        return templates.TemplateResponse(
            "clients/public_form_result.html",
            {
                "request": request,
                "title": "Cadastro de Cliente",
                "success": False,
                "message": "Link inválido.",
            },
            status_code=404,
        )

    if invite.used:
        return templates.TemplateResponse(
            "clients/public_form_result.html",
            {
                "request": request,
                "title": "Cadastro de Cliente",
                "success": False,
                "message": "Este link já foi utilizado e não está mais disponível.",
            },
            status_code=400,
        )

    office_id = int(invite.office_id)

    try:
        nasc = _parse_birth_date(nascimento)
    except ValueError:
        return templates.TemplateResponse(
            "clients/public_form.html",
            {
                "request": request,
                "title": "Cadastro de Cliente",
                "token": token,
                "msg": "Data de nascimento inválida.",
            },
            status_code=400,
        )

    cpf_norm = _norm_cpf_if_valid(cpf_cnpj)
    cpf_store = _store_doc_normalized(cpf_cnpj)

    if cpf_norm and _cpf_exists(db, cpf_norm, office_id):
        return templates.TemplateResponse(
            "clients/public_form.html",
            {
                "request": request,
                "title": "Cadastro de Cliente",
                "token": token,
                "msg": "Já existe um cliente cadastrado com este CPF.",
            },
            status_code=400,
        )

    cliente = Client(
        office_id=office_id,
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

    invite.used = True
    invite.used_at = now_br()

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            "clients/public_form.html",
            {
                "request": request,
                "title": "Cadastro de Cliente",
                "token": token,
                "msg": "Não foi possível concluir o cadastro. Verifique se o CPF já está cadastrado.",
            },
            status_code=400,
        )

    return templates.TemplateResponse(
        "clients/public_form_result.html",
        {
            "request": request,
            "title": "Cadastro de Cliente",
            "success": True,
            "message": "Cadastro realizado com sucesso.",
        },
        status_code=200,
    )