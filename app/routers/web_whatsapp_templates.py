from __future__ import annotations

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.whatsapp_template import WhatsAppTemplate
from app.services.whatsapp_templates import (
    AVAILABLE_PLACEHOLDERS,
    TIPO_LABELS,
    activate_template,
    ensure_default_whatsapp_templates,
    get_template_by_id,
    get_tipo_label,
    list_tipo_choices,
    restore_template_to_default,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _get_office_id(request: Request) -> int:
    office_id = request.session.get("office_id")
    if not office_id:
        raise HTTPException(status_code=403, detail="Usuário sem escritório vinculado.")
    return int(office_id)


def _get_user_id(request: Request) -> int | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return int(user_id)


@router.get("/configuracoes/whatsapp", response_class=HTMLResponse)
def whatsapp_templates_list(request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)
    user_id = _get_user_id(request)

    ensure_default_whatsapp_templates(db, office_id=office_id, user_id=user_id)

    templates_rows = (
        db.query(WhatsAppTemplate)
        .filter(WhatsAppTemplate.office_id == office_id)
        .order_by(
            WhatsAppTemplate.tipo.asc(),
            WhatsAppTemplate.is_active.desc(),
            WhatsAppTemplate.is_default.desc(),
            WhatsAppTemplate.titulo.asc(),
        )
        .all()
    )

    return templates.TemplateResponse(
        "whatsapp_templates/list.html",
        {
            "request": request,
            "title": "Modelos de WhatsApp",
            "rows": templates_rows,
            "tipo_labels": TIPO_LABELS,
            "get_tipo_label": get_tipo_label,
        },
    )


@router.get("/configuracoes/whatsapp/novo", response_class=HTMLResponse)
def whatsapp_templates_new_form(request: Request):
    _get_office_id(request)

    return templates.TemplateResponse(
        "whatsapp_templates/form.html",
        {
            "request": request,
            "title": "Novo Modelo de WhatsApp",
            "item": None,
            "erro": None,
            "tipo_choices": list_tipo_choices(),
            "available_placeholders": AVAILABLE_PLACEHOLDERS,
        },
    )


@router.post("/configuracoes/whatsapp/novo")
def whatsapp_templates_new(
    request: Request,
    db: Session = Depends(get_db),
    tipo: str = Form(...),
    titulo: str = Form(...),
    conteudo: str = Form(...),
    is_active: str | None = Form(None),
):
    office_id = _get_office_id(request)
    user_id = _get_user_id(request)

    tipo = (tipo or "").strip()
    titulo = (titulo or "").strip()
    conteudo = (conteudo or "").strip()

    if not tipo or tipo not in dict(list_tipo_choices()):
        return templates.TemplateResponse(
            "whatsapp_templates/form.html",
            {
                "request": request,
                "title": "Novo Modelo de WhatsApp",
                "item": None,
                "erro": "Selecione um tipo válido.",
                "tipo_choices": list_tipo_choices(),
                "available_placeholders": AVAILABLE_PLACEHOLDERS,
            },
            status_code=400,
        )

    if not titulo:
        return templates.TemplateResponse(
            "whatsapp_templates/form.html",
            {
                "request": request,
                "title": "Novo Modelo de WhatsApp",
                "item": None,
                "erro": "Informe o título do modelo.",
                "tipo_choices": list_tipo_choices(),
                "available_placeholders": AVAILABLE_PLACEHOLDERS,
            },
            status_code=400,
        )

    if not conteudo:
        return templates.TemplateResponse(
            "whatsapp_templates/form.html",
            {
                "request": request,
                "title": "Novo Modelo de WhatsApp",
                "item": None,
                "erro": "Informe o conteúdo do modelo.",
                "tipo_choices": list_tipo_choices(),
                "available_placeholders": AVAILABLE_PLACEHOLDERS,
            },
            status_code=400,
        )

    exists = (
        db.query(WhatsAppTemplate)
        .filter(
            WhatsAppTemplate.office_id == office_id,
            WhatsAppTemplate.tipo == tipo,
            WhatsAppTemplate.titulo == titulo,
        )
        .first()
    )
    if exists:
        return templates.TemplateResponse(
            "whatsapp_templates/form.html",
            {
                "request": request,
                "title": "Novo Modelo de WhatsApp",
                "item": None,
                "erro": "Já existe um modelo com este título para este tipo.",
                "tipo_choices": list_tipo_choices(),
                "available_placeholders": AVAILABLE_PLACEHOLDERS,
            },
            status_code=400,
        )

    tpl = WhatsAppTemplate(
        office_id=office_id,
        tipo=tipo,
        titulo=titulo,
        conteudo=conteudo,
        is_active=bool(is_active),
        is_default=False,
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)

    if tpl.is_active:
        activate_template(db, office_id=office_id, template_id=tpl.id, user_id=user_id)

    return RedirectResponse(url="/configuracoes/whatsapp", status_code=303)


@router.get("/configuracoes/whatsapp/{template_id}/editar", response_class=HTMLResponse)
def whatsapp_templates_edit_form(template_id: int, request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)

    item = get_template_by_id(db, office_id=office_id, template_id=template_id)
    if not item:
        return RedirectResponse(url="/configuracoes/whatsapp", status_code=303)

    return templates.TemplateResponse(
        "whatsapp_templates/form.html",
        {
            "request": request,
            "title": "Editar Modelo de WhatsApp",
            "item": item,
            "erro": None,
            "tipo_choices": list_tipo_choices(),
            "available_placeholders": AVAILABLE_PLACEHOLDERS,
        },
    )


@router.post("/configuracoes/whatsapp/{template_id}/editar")
def whatsapp_templates_edit(
    template_id: int,
    request: Request,
    db: Session = Depends(get_db),
    tipo: str = Form(...),
    titulo: str = Form(...),
    conteudo: str = Form(...),
    is_active: str | None = Form(None),
):
    office_id = _get_office_id(request)
    user_id = _get_user_id(request)

    item = get_template_by_id(db, office_id=office_id, template_id=template_id)
    if not item:
        return RedirectResponse(url="/configuracoes/whatsapp", status_code=303)

    tipo = (tipo or "").strip()
    titulo = (titulo or "").strip()
    conteudo = (conteudo or "").strip()

    if not tipo or tipo not in dict(list_tipo_choices()):
        return templates.TemplateResponse(
            "whatsapp_templates/form.html",
            {
                "request": request,
                "title": "Editar Modelo de WhatsApp",
                "item": item,
                "erro": "Selecione um tipo válido.",
                "tipo_choices": list_tipo_choices(),
                "available_placeholders": AVAILABLE_PLACEHOLDERS,
            },
            status_code=400,
        )

    if not titulo:
        return templates.TemplateResponse(
            "whatsapp_templates/form.html",
            {
                "request": request,
                "title": "Editar Modelo de WhatsApp",
                "item": item,
                "erro": "Informe o título do modelo.",
                "tipo_choices": list_tipo_choices(),
                "available_placeholders": AVAILABLE_PLACEHOLDERS,
            },
            status_code=400,
        )

    if not conteudo:
        return templates.TemplateResponse(
            "whatsapp_templates/form.html",
            {
                "request": request,
                "title": "Editar Modelo de WhatsApp",
                "item": item,
                "erro": "Informe o conteúdo do modelo.",
                "tipo_choices": list_tipo_choices(),
                "available_placeholders": AVAILABLE_PLACEHOLDERS,
            },
            status_code=400,
        )

    exists = (
        db.query(WhatsAppTemplate)
        .filter(
            WhatsAppTemplate.office_id == office_id,
            WhatsAppTemplate.tipo == tipo,
            WhatsAppTemplate.titulo == titulo,
            WhatsAppTemplate.id != item.id,
        )
        .first()
    )
    if exists:
        return templates.TemplateResponse(
            "whatsapp_templates/form.html",
            {
                "request": request,
                "title": "Editar Modelo de WhatsApp",
                "item": item,
                "erro": "Já existe um modelo com este título para este tipo.",
                "tipo_choices": list_tipo_choices(),
                "available_placeholders": AVAILABLE_PLACEHOLDERS,
            },
            status_code=400,
        )

    item.tipo = tipo
    item.titulo = titulo
    item.conteudo = conteudo
    item.is_active = bool(is_active)
    item.updated_by_user_id = user_id
    db.add(item)
    db.commit()

    if item.is_active:
        activate_template(db, office_id=office_id, template_id=item.id, user_id=user_id)

    return RedirectResponse(url="/configuracoes/whatsapp", status_code=303)


@router.post("/configuracoes/whatsapp/{template_id}/ativar")
def whatsapp_templates_activate(template_id: int, request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)
    user_id = _get_user_id(request)

    activate_template(db, office_id=office_id, template_id=template_id, user_id=user_id)
    return RedirectResponse(url="/configuracoes/whatsapp", status_code=303)


@router.post("/configuracoes/whatsapp/{template_id}/restaurar-padrao")
def whatsapp_templates_restore_default(template_id: int, request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)
    user_id = _get_user_id(request)

    restore_template_to_default(db, office_id=office_id, template_id=template_id, user_id=user_id)
    return RedirectResponse(url=f"/configuracoes/whatsapp/{template_id}/editar", status_code=303)


@router.post("/configuracoes/whatsapp/{template_id}/excluir")
def whatsapp_templates_delete(template_id: int, request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)

    item = get_template_by_id(db, office_id=office_id, template_id=template_id)
    if not item:
        return RedirectResponse(url="/configuracoes/whatsapp", status_code=303)

    if item.is_default:
        return RedirectResponse(url="/configuracoes/whatsapp", status_code=303)

    was_active = bool(item.is_active)
    item_tipo = item.tipo

    db.delete(item)
    db.commit()

    if was_active:
        replacement = (
            db.query(WhatsAppTemplate)
            .filter(
                WhatsAppTemplate.office_id == office_id,
                WhatsAppTemplate.tipo == item_tipo,
            )
            .order_by(
                WhatsAppTemplate.is_default.desc(),
                WhatsAppTemplate.updated_at.desc(),
                WhatsAppTemplate.id.desc(),
            )
            .first()
        )
        if replacement:
            replacement.is_active = True
            db.add(replacement)
            db.commit()

    return RedirectResponse(url="/configuracoes/whatsapp", status_code=303)