# app/routers/web_users.py
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.database import get_db
from app.core.permissions import require_permission
from app.core.security import hash_password
from app.core.session_manager import get_session_office_id
from app.models.audit_log import AuditLog
from app.models.user import User

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


# =========================================================
# LISTAGEM
# =========================================================
@router.get("", response_class=HTMLResponse)
def users_list(request: Request, db: Session = Depends(get_db)):
    try:
        require_permission(request, "usuarios.view")
    except HTTPException:
        return _redirect_denied()

    office_id = get_session_office_id(request)

    users = (
        db.query(User)
        .filter(User.office_id == office_id)
        .order_by(User.nome.asc())
        .all()
    )

    return templates.TemplateResponse(
        "users/list.html",
        {
            "request": request,
            "users": users,
            "current_user": request.state.current_user,
            "title": "Usuários",
        },
    )


# =========================================================
# NOVO
# =========================================================
@router.get("/novo", response_class=HTMLResponse)
def users_new_page(request: Request, db: Session = Depends(get_db)):
    try:
        require_permission(request, "usuarios.create")
    except HTTPException:
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
    except HTTPException:
        return _redirect_denied()

    office_id = get_session_office_id(request)

    if password != confirm_password:
        return templates.TemplateResponse(
            "users/form.html",
            {"request": request, "mode": "create", "error": "As senhas não conferem."},
            status_code=400,
        )

    user = User(
        nome=nome.strip(),
        email=email.strip().lower(),
        username=username.strip().lower(),
        password_hash=hash_password(password),
        is_active=bool(is_active),
        is_superuser=bool(is_superuser),
        must_change_password=bool(must_change_password),
        office_id=office_id,
    )

    db.add(user)
    db.commit()

    _log_action(db, actor, "create_user", "users", f"Usuário criado: {user.username}", request.client.host)

    return RedirectResponse(url="/usuarios", status_code=303)


# =========================================================
# EDITAR
# =========================================================
@router.get("/{user_id}/editar", response_class=HTMLResponse)
def users_edit_page(user_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        require_permission(request, "usuarios.edit")
    except HTTPException:
        return _redirect_denied()

    office_id = get_session_office_id(request)

    user_obj = db.query(User).filter(
        User.id == user_id,
        User.office_id == office_id
    ).first()

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
    except HTTPException:
        return _redirect_denied()

    office_id = get_session_office_id(request)

    user = db.query(User).filter(User.id == user_id, User.office_id == office_id).first()

    if not user:
        return RedirectResponse(url="/usuarios", status_code=303)

    user.nome = nome.strip()
    user.email = email.strip().lower()
    user.username = username.strip().lower()
    user.is_active = bool(is_active)
    user.is_superuser = bool(is_superuser)
    user.must_change_password = bool(must_change_password)

    db.commit()

    _log_action(db, actor, "edit_user", "users", f"Usuário editado: {user.username}", request.client.host)

    return RedirectResponse(url="/usuarios", status_code=303)


# =========================================================
# 🔥 SUSPENDER
# =========================================================
@router.post("/{user_id}/suspender")
def users_suspend(user_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        actor = require_permission(request, "usuarios.edit")
    except HTTPException:
        return _redirect_denied()

    office_id = get_session_office_id(request)

    user = db.query(User).filter(User.id == user_id, User.office_id == office_id).first()

    if not user:
        return RedirectResponse(url="/usuarios", status_code=303)

    user.suspend("Suspenso manualmente")

    db.commit()

    _log_action(db, actor, "suspend_user", "users", f"Usuário suspenso: {user.username}", request.client.host)

    return RedirectResponse(url="/usuarios", status_code=303)


# =========================================================
# 🔥 REATIVAR
# =========================================================
@router.post("/{user_id}/reativar")
def users_reactivate(user_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        actor = require_permission(request, "usuarios.edit")
    except HTTPException:
        return _redirect_denied()

    office_id = get_session_office_id(request)

    user = db.query(User).filter(User.id == user_id, User.office_id == office_id).first()

    if not user:
        return RedirectResponse(url="/usuarios", status_code=303)

    user.reactivate()

    db.commit()

    _log_action(db, actor, "reactivate_user", "users", f"Usuário reativado: {user.username}", request.client.host)

    return RedirectResponse(url="/usuarios", status_code=303)


# =========================================================
# 🔥 EXCLUIR
# =========================================================
@router.post("/{user_id}/excluir")
def users_delete(user_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        actor = require_permission(request, "usuarios.delete")
    except HTTPException:
        return _redirect_denied()

    office_id = get_session_office_id(request)
    current_user = request.state.current_user

    user = db.query(User).filter(User.id == user_id, User.office_id == office_id).first()

    if not user:
        return RedirectResponse(url="/usuarios", status_code=303)

    # 🚫 proteção: não excluir a si mesmo
    if current_user and user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Você não pode excluir seu próprio usuário.")

    username = user.username

    db.delete(user)
    db.commit()

    _log_action(db, actor, "delete_user", "users", f"Usuário excluído: {username}", request.client.host)

    return RedirectResponse(url="/usuarios", status_code=303)