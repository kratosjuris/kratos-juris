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
from app.models.permission import Permission
from app.models.office_permission import OfficePermission

router = APIRouter(prefix="/offices", tags=["Escritórios"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _redirect_denied():
    return RedirectResponse(url="/acesso-negado", status_code=303)


def require_superuser(request: Request) -> User:
    user = getattr(request.state, "current_user", None)
    if not user or not user.is_active or not user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="Acesso restrito ao superadministrador.",
        )
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


def _build_form_data(
    office_nome: str = "",
    admin_nome: str = "",
    admin_email: str = "",
    admin_username: str = "",
):
    return {
        "office_nome": office_nome,
        "admin_nome": admin_nome,
        "admin_email": admin_email,
        "admin_username": admin_username,
    }


# =========================================================
# LISTAGEM
# =========================================================
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
            "offices": offices,
            "current_user": current_user,
        },
    )


# =========================================================
# PERMISSÕES DO ESCRITÓRIO
# =========================================================
@router.get("/{office_id}/permissoes", response_class=HTMLResponse)
def office_permissions_page(
    office_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        require_superuser(request)
    except HTTPException:
        return _redirect_denied()

    office = db.query(Office).filter(Office.id == office_id).first()
    if not office:
        return RedirectResponse(url="/offices", status_code=303)

    all_permissions = db.query(Permission).order_by(Permission.code.asc()).all()
    office_permission_ids = {
        op.permission_id for op in (office.permission_links or [])
    }

    return templates.TemplateResponse(
        "offices/permissions.html",
        {
            "request": request,
            "office": office,
            "all_permissions": all_permissions,
            "office_permission_ids": office_permission_ids,
        },
    )


@router.post("/{office_id}/permissoes")
def office_permissions_save(
    office_id: int,
    request: Request,
    permissions: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    actor = require_superuser(request)

    office = db.query(Office).filter(Office.id == office_id).first()
    if not office:
        return RedirectResponse(url="/offices", status_code=303)

    ip = request.client.host if request.client else None

    try:
        db.query(OfficePermission).filter(
            OfficePermission.office_id == office_id
        ).delete()

        selected_codes = [p for p in (permissions or []) if (p or "").strip()]
        if selected_codes:
            perms = (
                db.query(Permission)
                .filter(Permission.code.in_(selected_codes))
                .all()
            )

            for perm in perms:
                db.add(
                    OfficePermission(
                        office_id=office.id,
                        permission_id=perm.id,
                    )
                )

        db.commit()

    except Exception:
        db.rollback()
        return templates.TemplateResponse(
            "offices/permissions.html",
            {
                "request": request,
                "office": office,
                "all_permissions": db.query(Permission).order_by(Permission.code.asc()).all(),
                "office_permission_ids": {
                    op.permission_id for op in (office.permission_links or [])
                },
                "error": "Não foi possível salvar as permissões do escritório.",
            },
            status_code=500,
        )

    _log_action(
        db=db,
        actor=actor,
        action="update_office_permissions",
        module="offices",
        description=f"Permissões atualizadas para o escritório: {office.nome} | office_id={office.id}",
        ip=ip,
    )

    return RedirectResponse(url="/offices", status_code=303)


# =========================================================
# NOVO
# =========================================================
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

    form_data = _build_form_data(
        office_nome=office_nome,
        admin_nome=admin_nome,
        admin_email=admin_email,
        admin_username=admin_username,
    )

    if not office_nome:
        return templates.TemplateResponse(
            "offices/form.html",
            {
                "request": request,
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
                "error": "As senhas não conferem.",
                "form_data": form_data,
            },
            status_code=400,
        )

    existing_office = db.query(Office).filter(Office.nome.ilike(office_nome)).first()
    if existing_office:
        return templates.TemplateResponse(
            "offices/form.html",
            {
                "request": request,
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

        admin = User(
            nome=admin_nome,
            email=admin_email,
            username=admin_username,
            password_hash=hash_password(password),
            office_id=office.id,
            is_active=True,
            is_superuser=False,
            must_change_password=False,
        )
        db.add(admin)
        db.commit()
        db.refresh(office)
        db.refresh(admin)

    except Exception:
        db.rollback()
        return templates.TemplateResponse(
            "offices/form.html",
            {
                "request": request,
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
        description=f"Escritório criado: {office.nome} | admin: {admin.username} | office_id={office.id}",
        ip=ip,
    )

    return RedirectResponse(url="/offices", status_code=303)


# =========================================================
# EDITAR
# =========================================================
@router.get("/{office_id}/editar", response_class=HTMLResponse)
def office_edit_page(
    office_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        require_superuser(request)
    except HTTPException:
        return _redirect_denied()

    office = db.query(Office).filter(Office.id == office_id).first()

    if not office:
        return RedirectResponse(url="/offices", status_code=303)

    admin_user = (
        db.query(User)
        .filter(User.office_id == office.id)
        .order_by(User.id.asc())
        .first()
    )

    return templates.TemplateResponse(
        "offices/form_edit.html",
        {
            "request": request,
            "office": office,
            "admin_user": admin_user,
            "error": None,
        },
    )


@router.post("/{office_id}/editar")
def office_edit_submit(
    office_id: int,
    request: Request,
    office_nome: str = Form(...),
    admin_nome: str = Form(...),
    admin_email: str = Form(...),
    admin_username: str = Form(...),
    password: str | None = Form(None),
    confirm_password: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        actor = require_superuser(request)
    except HTTPException:
        return _redirect_denied()

    office = db.query(Office).filter(Office.id == office_id).first()

    if not office:
        return RedirectResponse(url="/offices", status_code=303)

    admin_user = (
        db.query(User)
        .filter(User.office_id == office.id)
        .order_by(User.id.asc())
        .first()
    )

    if not admin_user:
        return templates.TemplateResponse(
            "offices/form_edit.html",
            {
                "request": request,
                "office": office,
                "admin_user": None,
                "error": "Administrador não encontrado para este escritório.",
            },
            status_code=400,
        )

    office_nome = (office_nome or "").strip()
    admin_nome = (admin_nome or "").strip()
    admin_email = (admin_email or "").strip().lower()
    admin_username = (admin_username or "").strip().lower()
    password = (password or "").strip()
    confirm_password = (confirm_password or "").strip()

    if not office_nome:
        return templates.TemplateResponse(
            "offices/form_edit.html",
            {
                "request": request,
                "office": office,
                "admin_user": admin_user,
                "error": "Informe o nome do escritório.",
            },
            status_code=400,
        )

    if not admin_nome:
        return templates.TemplateResponse(
            "offices/form_edit.html",
            {
                "request": request,
                "office": office,
                "admin_user": admin_user,
                "error": "Informe o nome do administrador.",
            },
            status_code=400,
        )

    if not admin_email:
        return templates.TemplateResponse(
            "offices/form_edit.html",
            {
                "request": request,
                "office": office,
                "admin_user": admin_user,
                "error": "Informe o e-mail do administrador.",
            },
            status_code=400,
        )

    if not admin_username:
        return templates.TemplateResponse(
            "offices/form_edit.html",
            {
                "request": request,
                "office": office,
                "admin_user": admin_user,
                "error": "Informe o username do administrador.",
            },
            status_code=400,
        )

    existing_office = (
        db.query(Office)
        .filter(Office.nome.ilike(office_nome), Office.id != office.id)
        .first()
    )
    if existing_office:
        return templates.TemplateResponse(
            "offices/form_edit.html",
            {
                "request": request,
                "office": office,
                "admin_user": admin_user,
                "error": "Já existe outro escritório com esse nome.",
            },
            status_code=400,
        )

    if db.query(User).filter(User.email == admin_email, User.id != admin_user.id).first():
        return templates.TemplateResponse(
            "offices/form_edit.html",
            {
                "request": request,
                "office": office,
                "admin_user": admin_user,
                "error": "Já existe usuário com esse e-mail.",
            },
            status_code=400,
        )

    if db.query(User).filter(User.username == admin_username, User.id != admin_user.id).first():
        return templates.TemplateResponse(
            "offices/form_edit.html",
            {
                "request": request,
                "office": office,
                "admin_user": admin_user,
                "error": "Já existe usuário com esse username.",
            },
            status_code=400,
        )

    if password or confirm_password:
        if password != confirm_password:
            return templates.TemplateResponse(
                "offices/form_edit.html",
                {
                    "request": request,
                    "office": office,
                    "admin_user": admin_user,
                    "error": "As senhas não conferem.",
                },
                status_code=400,
            )
        if not password:
            return templates.TemplateResponse(
                "offices/form_edit.html",
                {
                    "request": request,
                    "office": office,
                    "admin_user": admin_user,
                    "error": "Informe a nova senha.",
                },
                status_code=400,
            )

    ip = request.client.host if request.client else None

    try:
        office.nome = office_nome
        admin_user.nome = admin_nome
        admin_user.email = admin_email
        admin_user.username = admin_username

        if password:
            admin_user.password_hash = hash_password(password)

        db.commit()
        db.refresh(office)
        db.refresh(admin_user)

    except Exception:
        db.rollback()
        return templates.TemplateResponse(
            "offices/form_edit.html",
            {
                "request": request,
                "office": office,
                "admin_user": admin_user,
                "error": "Não foi possível salvar as alterações.",
            },
            status_code=500,
        )

    _log_action(
        db=db,
        actor=actor,
        action="edit_office_full",
        module="offices",
        description=f"Editado escritório {office.nome} + admin {admin_user.username}",
        ip=ip,
    )

    return RedirectResponse(url="/offices", status_code=303)


# =========================================================
# SUSPENDER
# =========================================================
@router.post("/{office_id}/suspender")
def office_suspend(office_id: int, request: Request, db: Session = Depends(get_db)):
    actor = require_superuser(request)

    office = db.query(Office).filter(Office.id == office_id).first()

    if not office:
        return RedirectResponse(url="/offices", status_code=303)

    office.suspend("Inadimplência")

    users = db.query(User).filter(User.office_id == office.id).all()
    for u in users:
        u.suspend("Office suspenso")

    db.commit()

    _log_action(
        db,
        actor,
        "suspend_office",
        "offices",
        f"Suspenso: {office.nome}",
        request.client.host if request.client else None,
    )

    return RedirectResponse(url="/offices", status_code=303)


# =========================================================
# REATIVAR
# =========================================================
@router.post("/{office_id}/reativar")
def office_reactivate(office_id: int, request: Request, db: Session = Depends(get_db)):
    actor = require_superuser(request)

    office = db.query(Office).filter(Office.id == office_id).first()

    if not office:
        return RedirectResponse(url="/offices", status_code=303)

    office.reactivate()

    users = db.query(User).filter(User.office_id == office.id).all()
    for u in users:
        u.reactivate()

    db.commit()

    _log_action(
        db,
        actor,
        "reactivate_office",
        "offices",
        f"Reativado: {office.nome}",
        request.client.host if request.client else None,
    )

    return RedirectResponse(url="/offices", status_code=303)


# =========================================================
# EXCLUIR (SEGURO)
# =========================================================
@router.post("/{office_id}/excluir")
def office_delete(office_id: int, request: Request, db: Session = Depends(get_db)):
    actor = require_superuser(request)

    if actor.office_id == office_id:
        raise HTTPException(
            status_code=400,
            detail="Você não pode excluir seu próprio escritório.",
        )

    office = db.query(Office).filter(Office.id == office_id).first()

    if not office:
        return RedirectResponse(url="/offices", status_code=303)

    office_nome = office.nome
    ip = request.client.host if request.client else None

    try:
        db.query(OfficePermission).filter(
            OfficePermission.office_id == office.id
        ).delete()

        users = db.query(User).filter(User.office_id == office.id).all()
        for u in users:
            db.delete(u)

        db.delete(office)
        db.commit()

    except Exception:
        db.rollback()
        raise

    _log_action(
        db,
        actor,
        "delete_office",
        "offices",
        f"Excluído: {office_nome}",
        ip,
    )

    return RedirectResponse(url="/offices", status_code=303)