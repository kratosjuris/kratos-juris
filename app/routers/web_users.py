# app/routers/web_users.py
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.core.config import TEMPLATES_DIR
from app.core.database import get_db
from app.core.permissions import require_permission
from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.permission import Permission
from app.models.user import User
from app.models.user_permission import UserPermission

router = APIRouter(prefix="/usuarios", tags=["Usuários"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _redirect_denied():
    return RedirectResponse(url="/acesso-negado", status_code=303)


def _log_action(db: Session, actor: User | None, action: str, module: str, description: str, ip: str | None):
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
def users_list(request: Request, db: Session = Depends(get_db)):
    try:
        require_permission(request, "usuarios.view")
    except PermissionError:
        return _redirect_denied()

    users = db.query(User).order_by(User.nome.asc()).all()
    return templates.TemplateResponse(
        "users/list.html",
        {
            "request": request,
            "users": users,
            "current_user": request.state.current_user,
            "title": "Usuários",
        },
    )


@router.get("/novo", response_class=HTMLResponse)
def users_new_page(request: Request, db: Session = Depends(get_db)):
    try:
        require_permission(request, "usuarios.create")
    except PermissionError:
        return _redirect_denied()

    return templates.TemplateResponse(
        "users/form.html",
        {
            "request": request,
            "mode": "create",
            "user_obj": None,
            "error": None,
            "title": "Novo usuário",
        },
    )


@router.post("/novo")
def users_new_submit(
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    is_active: str | None = Form(None),
    is_superuser: str | None = Form(None),
    must_change_password: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        actor = require_permission(request, "usuarios.create")
    except PermissionError:
        return _redirect_denied()

    nome = nome.strip()
    email = email.strip().lower()
    username = username.strip().lower()

    if password != confirm_password:
        return templates.TemplateResponse(
            "users/form.html",
            {
                "request": request,
                "mode": "create",
                "user_obj": None,
                "error": "As senhas não conferem.",
                "title": "Novo usuário",
            },
            status_code=400,
        )

    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse(
            "users/form.html",
            {
                "request": request,
                "mode": "create",
                "user_obj": None,
                "error": "Já existe usuário com este e-mail.",
                "title": "Novo usuário",
            },
            status_code=400,
        )

    if db.query(User).filter(User.username == username).first():
        return templates.TemplateResponse(
            "users/form.html",
            {
                "request": request,
                "mode": "create",
                "user_obj": None,
                "error": "Já existe usuário com este username.",
                "title": "Novo usuário",
            },
            status_code=400,
        )

    user = User(
        nome=nome,
        email=email,
        username=username,
        password_hash=hash_password(password),
        is_active=bool(is_active),
        is_superuser=bool(is_superuser),
        must_change_password=bool(must_change_password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    ip = request.client.host if request.client else None
    _log_action(db, actor, "create_user", "users", f"Usuário criado: {user.username}", ip)

    return RedirectResponse(url="/usuarios", status_code=303)


@router.get("/{user_id}/editar", response_class=HTMLResponse)
def users_edit_page(user_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        require_permission(request, "usuarios.edit")
    except PermissionError:
        return _redirect_denied()

    user_obj = db.query(User).filter(User.id == user_id).first()
    if not user_obj:
        return RedirectResponse(url="/usuarios", status_code=303)

    return templates.TemplateResponse(
        "users/form.html",
        {
            "request": request,
            "mode": "edit",
            "user_obj": user_obj,
            "error": None,
            "title": "Editar usuário",
        },
    )


@router.post("/{user_id}/editar")
def users_edit_submit(
    user_id: int,
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    username: str = Form(...),
    is_active: str | None = Form(None),
    is_superuser: str | None = Form(None),
    must_change_password: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        actor = require_permission(request, "usuarios.edit")
    except PermissionError:
        return _redirect_denied()

    user_obj = db.query(User).filter(User.id == user_id).first()
    if not user_obj:
        return RedirectResponse(url="/usuarios", status_code=303)

    email = email.strip().lower()
    username = username.strip().lower()

    if db.query(User).filter(User.email == email, User.id != user_id).first():
        return templates.TemplateResponse(
            "users/form.html",
            {
                "request": request,
                "mode": "edit",
                "user_obj": user_obj,
                "error": "Já existe outro usuário com este e-mail.",
                "title": "Editar usuário",
            },
            status_code=400,
        )

    if db.query(User).filter(User.username == username, User.id != user_id).first():
        return templates.TemplateResponse(
            "users/form.html",
            {
                "request": request,
                "mode": "edit",
                "user_obj": user_obj,
                "error": "Já existe outro usuário com este username.",
                "title": "Editar usuário",
            },
            status_code=400,
        )

    user_obj.nome = nome.strip()
    user_obj.email = email
    user_obj.username = username
    user_obj.is_active = bool(is_active)
    user_obj.is_superuser = bool(is_superuser)
    user_obj.must_change_password = bool(must_change_password)

    db.commit()

    ip = request.client.host if request.client else None
    _log_action(db, actor, "edit_user", "users", f"Usuário editado: {user_obj.username}", ip)

    return RedirectResponse(url="/usuarios", status_code=303)


@router.post("/{user_id}/inativar")
def users_inactivate(user_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        actor = require_permission(request, "usuarios.delete")
    except PermissionError:
        return _redirect_denied()

    user_obj = db.query(User).filter(User.id == user_id).first()
    if not user_obj:
        return RedirectResponse(url="/usuarios", status_code=303)

    if actor.id == user_obj.id:
        return RedirectResponse(url="/usuarios", status_code=303)

    user_obj.is_active = False
    db.commit()

    ip = request.client.host if request.client else None
    _log_action(db, actor, "inactivate_user", "users", f"Usuário inativado: {user_obj.username}", ip)

    return RedirectResponse(url="/usuarios", status_code=303)


@router.get("/{user_id}/reset-senha", response_class=HTMLResponse)
def users_reset_password_page(user_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        require_permission(request, "usuarios.reset_password")
    except PermissionError:
        return _redirect_denied()

    user_obj = db.query(User).filter(User.id == user_id).first()
    if not user_obj:
        return RedirectResponse(url="/usuarios", status_code=303)

    return templates.TemplateResponse(
        "users/reset_password.html",
        {
            "request": request,
            "user_obj": user_obj,
            "error": None,
            "title": "Redefinir senha",
        },
    )


@router.post("/{user_id}/reset-senha")
def users_reset_password_submit(
    user_id: int,
    request: Request,
    password: str = Form(...),
    confirm_password: str = Form(...),
    must_change_password: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        actor = require_permission(request, "usuarios.reset_password")
    except PermissionError:
        return _redirect_denied()

    user_obj = db.query(User).filter(User.id == user_id).first()
    if not user_obj:
        return RedirectResponse(url="/usuarios", status_code=303)

    if password != confirm_password:
        return templates.TemplateResponse(
            "users/reset_password.html",
            {
                "request": request,
                "user_obj": user_obj,
                "error": "As senhas não conferem.",
                "title": "Redefinir senha",
            },
            status_code=400,
        )

    user_obj.password_hash = hash_password(password)
    user_obj.must_change_password = bool(must_change_password)
    db.commit()

    ip = request.client.host if request.client else None
    _log_action(db, actor, "reset_password", "users", f"Senha redefinida para: {user_obj.username}", ip)

    return RedirectResponse(url="/usuarios", status_code=303)


@router.get("/{user_id}/permissoes", response_class=HTMLResponse)
def users_permissions_page(user_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        require_permission(request, "usuarios.permissions")
    except PermissionError:
        return _redirect_denied()

    user_obj = (
        db.query(User)
        .options(joinedload(User.permission_links).joinedload(UserPermission.permission))
        .filter(User.id == user_id)
        .first()
    )
    if not user_obj:
        return RedirectResponse(url="/usuarios", status_code=303)

    permissions = db.query(Permission).order_by(Permission.module.asc(), Permission.name.asc()).all()

    grouped = defaultdict(list)
    selected_ids = set()

    for perm in permissions:
        grouped[perm.module].append(perm)

    for link in user_obj.permission_links:
        selected_ids.add(link.permission_id)

    return templates.TemplateResponse(
        "users/permissions.html",
        {
            "request": request,
            "user_obj": user_obj,
            "grouped_permissions": dict(grouped),
            "selected_ids": selected_ids,
            "title": "Permissões",
        },
    )


@router.post("/{user_id}/permissoes")
async def users_permissions_submit(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        actor = require_permission(request, "usuarios.permissions")
    except PermissionError:
        return _redirect_denied()

    user_obj = db.query(User).filter(User.id == user_id).first()
    if not user_obj:
        return RedirectResponse(url="/usuarios", status_code=303)

    form_data = await request.form()
    ids = form_data.getlist("permission_ids")

    valid_ids = []
    for item in ids:
        try:
            valid_ids.append(int(item))
        except Exception:
            continue

    db.query(UserPermission).filter(UserPermission.user_id == user_obj.id).delete()

    if not user_obj.is_superuser:
        for perm_id in valid_ids:
            db.add(UserPermission(user_id=user_obj.id, permission_id=perm_id))

    db.commit()

    ip = request.client.host if request.client else None
    _log_action(db, actor, "update_permissions", "users", f"Permissões atualizadas para: {user_obj.username}", ip)

    return RedirectResponse(url="/usuarios", status_code=303)