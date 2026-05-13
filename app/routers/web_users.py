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
from app.core.datetime_utils import TZ_BR
from app.models.audit_log import AuditLog
from app.models.permission import Permission
from app.models.user import User
from app.models.user_permission import UserPermission

router = APIRouter(prefix="/usuarios", tags=["Usuários"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _redirect_denied():
    return RedirectResponse(url="/acesso-negado", status_code=303)


def _is_superuser(user: User | None) -> bool:
    return bool(getattr(user, "is_superuser", False))


def _is_ceo(user: User | None) -> bool:
    return bool(getattr(user, "is_ceo", False))


def _can_manage_roles(actor: User | None) -> bool:
    """
    Apenas superadministrador pode alterar cargos sensíveis:
    - is_superuser
    - is_ceo
    """
    return _is_superuser(actor)


def _can_manage_permissions(actor: User | None) -> bool:
    """
    Superadministrador e CEO podem acessar a tela de permissões,
    desde que tenham a permissão usuarios.permissions.
    """
    return _is_superuser(actor) or _is_ceo(actor)


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


def _get_office_user_or_none(
    db: Session,
    office_id: int | None,
    user_id: int,
) -> User | None:
    if office_id is None:
        return None

    return (
        db.query(User)
        .filter(User.id == user_id, User.office_id == office_id)
        .first()
    )


def _fmt_dt_br(dt):
    if not dt:
        return "-"

    try:
        if dt.tzinfo is None:
            from zoneinfo import ZoneInfo
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))

        return dt.astimezone(TZ_BR).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(dt)


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

    for u in users:
        u.last_login_at_fmt = _fmt_dt_br(u.last_login_at)

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
        actor = require_permission(request, "usuarios.create")
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
            "current_user": actor,
            "can_manage_roles": _can_manage_roles(actor),
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
    is_ceo: str | None = Form(None),
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
            {
                "request": request,
                "mode": "create",
                "user_obj": None,
                "error": "As senhas não conferem.",
                "title": "Novo usuário",
                "current_user": actor,
                "can_manage_roles": _can_manage_roles(actor),
            },
            status_code=400,
        )

    # REGRA DE SEGURANÇA:
    # Somente superadministrador pode criar outro superadministrador ou CEO.
    if _can_manage_roles(actor):
        new_is_superuser = bool(is_superuser)
        new_is_ceo = bool(is_ceo)
    else:
        new_is_superuser = False
        new_is_ceo = False

    user = User(
        nome=nome.strip(),
        email=email.strip().lower(),
        username=username.strip().lower(),
        password_hash=hash_password(password),
        is_active=bool(is_active),
        is_superuser=new_is_superuser,
        is_ceo=new_is_ceo,
        must_change_password=bool(must_change_password),
        office_id=office_id,
    )

    db.add(user)
    db.commit()

    _log_action(
        db=db,
        actor=actor,
        action="create_user",
        module="users",
        description=f"Usuário criado: {user.username}",
        ip=request.client.host if request.client else None,
    )

    return RedirectResponse(url="/usuarios", status_code=303)


# =========================================================
# EDITAR
# =========================================================
@router.get("/{user_id}/editar", response_class=HTMLResponse)
def users_edit_page(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        actor = require_permission(request, "usuarios.edit")
    except HTTPException:
        return _redirect_denied()

    office_id = get_session_office_id(request)

    user_obj = _get_office_user_or_none(db, office_id, user_id)

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
            "current_user": actor,
            "can_manage_roles": _can_manage_roles(actor),
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
    is_ceo: str | None = Form(None),
    must_change_password: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        actor = require_permission(request, "usuarios.edit")
    except HTTPException:
        return _redirect_denied()

    office_id = get_session_office_id(request)

    user = _get_office_user_or_none(db, office_id, user_id)

    if not user:
        return RedirectResponse(url="/usuarios", status_code=303)

    is_self_edit = bool(actor and actor.id == user.id)

    user.nome = nome.strip()
    user.email = email.strip().lower()
    user.username = username.strip().lower()

    # Usuário não superadmin não pode alterar sua própria ativação.
    if is_self_edit and not _is_superuser(actor):
        user.is_active = bool(user.is_active)
    else:
        user.is_active = bool(is_active)

    user.must_change_password = bool(must_change_password)

    # REGRA DE SEGURANÇA:
    # Apenas superadministrador altera is_superuser e is_ceo.
    # CEO pode editar usuários, mas não pode se transformar em superadmin,
    # nem transformar terceiros em superadmin/CEO.
    if _can_manage_roles(actor):
        user.is_superuser = bool(is_superuser)
        user.is_ceo = bool(is_ceo)
    else:
        user.is_superuser = bool(user.is_superuser)
        user.is_ceo = bool(user.is_ceo)

    db.commit()

    _log_action(
        db=db,
        actor=actor,
        action="edit_user",
        module="users",
        description=f"Usuário editado: {user.username}",
        ip=request.client.host if request.client else None,
    )

    return RedirectResponse(url="/usuarios", status_code=303)


# =========================================================
# PERMISSÕES DO USUÁRIO
# =========================================================
@router.get("/{user_id}/permissoes", response_class=HTMLResponse)
def user_permissions_page(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        actor = require_permission(request, "usuarios.permissions")
    except HTTPException:
        return _redirect_denied()

    if not _can_manage_permissions(actor):
        return _redirect_denied()

    office_id = get_session_office_id(request)
    user_obj = _get_office_user_or_none(db, office_id, user_id)

    if not user_obj:
        return RedirectResponse(url="/usuarios", status_code=303)

    all_permissions = db.query(Permission).order_by(Permission.code.asc()).all()

    user_permission_ids = {
        link.permission_id
        for link in (user_obj.permission_links or [])
        if link.permission_id
    }

    grouped_permissions = defaultdict(list)

    for perm in all_permissions:
        group = (perm.code or "").split(".")[0] or "geral"
        grouped_permissions[group].append(perm)

    return templates.TemplateResponse(
        "users/permissions.html",
        {
            "request": request,
            "user_obj": user_obj,
            "all_permissions": all_permissions,
            "grouped_permissions": grouped_permissions,
            "user_permission_ids": user_permission_ids,
            "title": "Permissões do usuário",
            "current_user": actor,
            "can_manage_roles": _can_manage_roles(actor),
        },
    )


@router.post("/{user_id}/permissoes")
def user_permissions_save(
    user_id: int,
    request: Request,
    permissions: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    try:
        actor = require_permission(request, "usuarios.permissions")
    except HTTPException:
        return _redirect_denied()

    if not _can_manage_permissions(actor):
        return _redirect_denied()

    office_id = get_session_office_id(request)
    user_obj = _get_office_user_or_none(db, office_id, user_id)

    if not user_obj:
        return RedirectResponse(url="/usuarios", status_code=303)

    try:
        db.query(UserPermission).filter(
            UserPermission.user_id == user_obj.id
        ).delete(synchronize_session=False)

        selected_codes = [
            p.strip()
            for p in (permissions or [])
            if (p or "").strip()
        ]

        if selected_codes:
            perms = (
                db.query(Permission)
                .filter(Permission.code.in_(selected_codes))
                .all()
            )

            for perm in perms:
                db.add(
                    UserPermission(
                        user_id=user_obj.id,
                        permission_id=perm.id,
                    )
                )

        db.commit()

    except Exception:
        db.rollback()
        raise

    _log_action(
        db=db,
        actor=actor,
        action="update_user_permissions",
        module="users",
        description=f"Permissões atualizadas para o usuário: {user_obj.username}",
        ip=request.client.host if request.client else None,
    )

    return RedirectResponse(url="/usuarios", status_code=303)