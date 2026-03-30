# app/routers/web_offices.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.database import get_db
from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.office import Office
from app.models.user import User

router = APIRouter(prefix="/offices", tags=["Escritórios"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _redirect_denied():
    return RedirectResponse(url="/acesso-negado", status_code=303)


def require_superuser(request: Request) -> User:
    user = getattr(request.state, "current_user", None)
    if not user or not user.is_active or not user.is_superuser:
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador")
    return user


def _log_action(
    db: Session,
    actor: User | None,
    action: str,
    module: str,
    description: str,
    ip: str | None,
):
    db.add(
        AuditLog(
            user_id=actor.id if actor else None,
            action=action,
            module=module,
            description=description,
            ip_address=ip,
        )
    )
    db.commit()


@router.get("", response_class=HTMLResponse)
def offices_list(request: Request, db: Session = Depends(get_db)):
    try:
        current_user = require_superuser(request)
    except HTTPException:
        return _redirect_denied()

    offices = db.query(Office).order_by(Office.nome.asc()).all()

    return templates.TemplateResponse(
        "offices/list.html",
        {
            "request": request,
            "title": "Escritórios",
            "offices": offices,
            "current_user": current_user,
        },
    )


@router.get("/novo", response_class=HTMLResponse)
def offices_new_page(request: Request):
    try:
        require_superuser(request)
    except HTTPException:
        return _redirect_denied()

    return templates.TemplateResponse(
        "offices/form.html",
        {
            "request": request,
            "title": "Novo Escritório",
            "error": None,
            "form_data": {},
        },
    )


@router.post("/novo")
def offices_new_submit(
    request: Request,
    office_nome: str = Form(...),
    admin_nome: str = Form(...),
    admin_email: str = Form(...),
    admin_username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        actor = require_superuser(request)
    except HTTPException:
        return _redirect_denied()

    office_nome = (office_nome or "").strip()
    admin_nome = (admin_nome or "").strip()
    admin_email = (admin_email or "").strip().lower()
    admin_username = (admin_username or "").strip().lower()

    form_data = {
        "office_nome": office_nome,
        "admin_nome": admin_nome,
        "admin_email": admin_email,
        "admin_username": admin_username,
    }

    if not office_nome:
        return templates.TemplateResponse(
            "offices/form.html",
            {
                "request": request,
                "title": "Novo Escritório",
                "error": "Informe o nome do escritório.",
                "form_data": form_data,
            },
            status_code=400,
        )

    if not admin_nome:
        return templates.TemplateResponse(
            "offices/form.html",
            {
                "request": request,
                "title": "Novo Escritório",
                "error": "Informe o nome do administrador.",
                "form_data": form_data,
            },
            status_code=400,
        )

    if not admin_email:
        return templates.TemplateResponse(
            "offices/form.html",
            {
                "request": request,
                "title": "Novo Escritório",
                "error": "Informe o e-mail do administrador.",
                "form_data": form_data,
            },
            status_code=400,
        )

    if not admin_username:
        return templates.TemplateResponse(
            "offices/form.html",
            {
                "request": request,
                "title": "Novo Escritório",
                "error": "Informe o username do administrador.",
                "form_data": form_data,
            },
            status_code=400,
        )

    if password != confirm_password:
        return templates.TemplateResponse(
            "offices/form.html",
            {
                "request": request,
                "title": "Novo Escritório",
                "error": "As senhas não conferem.",
                "form_data": form_data,
            },
            status_code=400,
        )

    existing_office = (
        db.query(Office)
        .filter(Office.nome.ilike(office_nome))
        .first()
    )
    if existing_office:
        return templates.TemplateResponse(
            "offices/form.html",
            {
                "request": request,
                "title": "Novo Escritório",
                "error": "Já existe um escritório com esse nome.",
                "form_data": form_data,
            },
            status_code=400,
        )

    if db.query(User).filter(User.email == admin_email).first():
        return templates.TemplateResponse(
            "offices/form.html",
            {
                "request": request,
                "title": "Novo Escritório",
                "error": "Já existe usuário com esse e-mail.",
                "form_data": form_data,
            },
            status_code=400,
        )

    if db.query(User).filter(User.username == admin_username).first():
        return templates.TemplateResponse(
            "offices/form.html",
            {
                "request": request,
                "title": "Novo Escritório",
                "error": "Já existe usuário com esse username.",
                "form_data": form_data,
            },
            status_code=400,
        )

    ip = request.client.host if request.client else None

    try:
        office = Office(nome=office_nome)
        db.add(office)
        db.flush()

        admin_user = User(
            nome=admin_nome,
            email=admin_email,
            username=admin_username,
            office_id=office.id,
            password_hash=hash_password(password),
            is_active=True,
            is_superuser=False,
            must_change_password=False,
        )
        db.add(admin_user)
        db.commit()
        db.refresh(office)
        db.refresh(admin_user)

    except Exception:
        db.rollback()
        return templates.TemplateResponse(
            "offices/form.html",
            {
                "request": request,
                "title": "Novo Escritório",
                "error": "Não foi possível criar o escritório.",
                "form_data": form_data,
            },
            status_code=500,
        )

    _log_action(
        db=db,
        actor=actor,
        action="create_office",
        module="offices",
        description=(
            f"Escritório criado: {office.nome} | "
            f"admin: {admin_user.username} | office_id={office.id}"
        ),
        ip=ip,
    )

    return RedirectResponse(url="/offices", status_code=303)