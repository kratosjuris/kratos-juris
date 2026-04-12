import json
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.document_template import OfficeDocumentTemplate
from app.models.user import User
from app.services.document_templates import (
    DOC_TEMPLATES_MAX_BYTES,
    DOC_TEMPLATES_MAX_MB,
    build_storage_path,
    detected_placeholders_to_json,
    get_all_doc_specs,
    get_allowed_placeholders,
    get_doc_spec,
    get_doc_title,
    remove_file_silently,
    sanitize_filename,
    validate_docx_placeholders,
    write_template_bytes,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _get_logged_user(request: Request, db: Session) -> User:
    user_id = request.session.get("user_id")
    office_id = request.session.get("office_id")

    if not user_id:
        raise HTTPException(status_code=401, detail="Usuário não autenticado")

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="Usuário inválido")

    if not office_id:
        office_id = getattr(user, "office_id", None)

    if not office_id:
        raise HTTPException(status_code=403, detail="Escritório não identificado na sessão")

    return user


@router.get("/doc-templates", response_class=HTMLResponse)
def listar_modelos(request: Request, db: Session = Depends(get_db)):
    user = _get_logged_user(request, db)
    office_id = request.session.get("office_id") or getattr(user, "office_id", None)

    rows = (
        db.query(OfficeDocumentTemplate)
        .filter(OfficeDocumentTemplate.office_id == office_id)
        .order_by(
            OfficeDocumentTemplate.doc_key.asc(),
            OfficeDocumentTemplate.version.desc(),
            OfficeDocumentTemplate.id.desc(),
        )
        .all()
    )

    active_by_key = {}
    history_by_key = {}

    for row in rows:
        history_by_key.setdefault(row.doc_key, []).append(row)
        if row.is_active and row.doc_key not in active_by_key:
            active_by_key[row.doc_key] = row

    return templates.TemplateResponse(
        "doc_templates/index.html",
        {
            "request": request,
            "specs": get_all_doc_specs(),
            "active_by_key": active_by_key,
            "history_by_key": history_by_key,
            "max_mb": DOC_TEMPLATES_MAX_MB,
        },
    )


@router.get("/doc-templates/novo/{doc_key}", response_class=HTMLResponse)
def form_novo_modelo(doc_key: str, request: Request, db: Session = Depends(get_db)):
    _get_logged_user(request, db)

    spec = get_doc_spec(doc_key)
    if not spec:
        raise HTTPException(status_code=404, detail="Tipo de documento inválido")

    return templates.TemplateResponse(
        "doc_templates/form.html",
        {
            "request": request,
            "doc_key": doc_key,
            "title": get_doc_title(doc_key),
            "allowed_placeholders": get_allowed_placeholders(doc_key),
            "max_mb": DOC_TEMPLATES_MAX_MB,
            "msg": None,
            "validation": None,
        },
    )


@router.post("/doc-templates/novo/{doc_key}", response_class=HTMLResponse)
async def salvar_modelo(
    doc_key: str,
    request: Request,
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = _get_logged_user(request, db)
    office_id = request.session.get("office_id") or getattr(user, "office_id", None)

    spec = get_doc_spec(doc_key)
    if not spec:
        raise HTTPException(status_code=404, detail="Tipo de documento inválido")

    allowed_placeholders = get_allowed_placeholders(doc_key)

    if not arquivo or not arquivo.filename:
        return templates.TemplateResponse(
            "doc_templates/form.html",
            {
                "request": request,
                "doc_key": doc_key,
                "title": get_doc_title(doc_key),
                "allowed_placeholders": allowed_placeholders,
                "max_mb": DOC_TEMPLATES_MAX_MB,
                "msg": "Selecione um arquivo .docx.",
                "validation": None,
            },
            status_code=400,
        )

    original_filename = sanitize_filename(arquivo.filename)

    if not original_filename.lower().endswith(".docx"):
        return templates.TemplateResponse(
            "doc_templates/form.html",
            {
                "request": request,
                "doc_key": doc_key,
                "title": get_doc_title(doc_key),
                "allowed_placeholders": allowed_placeholders,
                "max_mb": DOC_TEMPLATES_MAX_MB,
                "msg": "Apenas arquivos .docx são permitidos.",
                "validation": None,
            },
            status_code=400,
        )

    file_bytes = await arquivo.read()

    if not file_bytes:
        return templates.TemplateResponse(
            "doc_templates/form.html",
            {
                "request": request,
                "doc_key": doc_key,
                "title": get_doc_title(doc_key),
                "allowed_placeholders": allowed_placeholders,
                "max_mb": DOC_TEMPLATES_MAX_MB,
                "msg": "O arquivo enviado está vazio.",
                "validation": None,
            },
            status_code=400,
        )

    if len(file_bytes) > DOC_TEMPLATES_MAX_BYTES:
        return templates.TemplateResponse(
            "doc_templates/form.html",
            {
                "request": request,
                "doc_key": doc_key,
                "title": get_doc_title(doc_key),
                "allowed_placeholders": allowed_placeholders,
                "max_mb": DOC_TEMPLATES_MAX_MB,
                "msg": f"O arquivo excede o limite de {DOC_TEMPLATES_MAX_MB} MB.",
                "validation": None,
            },
            status_code=400,
        )

    try:
        validation = validate_docx_placeholders(doc_key, file_bytes)
    except Exception as e:
        return templates.TemplateResponse(
            "doc_templates/form.html",
            {
                "request": request,
                "doc_key": doc_key,
                "title": get_doc_title(doc_key),
                "allowed_placeholders": allowed_placeholders,
                "max_mb": DOC_TEMPLATES_MAX_MB,
                "msg": f"Não foi possível ler o arquivo .docx: {e}",
                "validation": None,
            },
            status_code=400,
        )

    if not validation["is_valid"]:
        return templates.TemplateResponse(
            "doc_templates/form.html",
            {
                "request": request,
                "doc_key": doc_key,
                "title": get_doc_title(doc_key),
                "allowed_placeholders": allowed_placeholders,
                "max_mb": DOC_TEMPLATES_MAX_MB,
                "msg": "O modelo possui placeholders inválidos. Corrija e envie novamente.",
                "validation": validation,
            },
            status_code=400,
        )

    last_version = (
        db.query(OfficeDocumentTemplate)
        .filter(
            OfficeDocumentTemplate.office_id == office_id,
            OfficeDocumentTemplate.doc_key == doc_key,
        )
        .order_by(OfficeDocumentTemplate.version.desc(), OfficeDocumentTemplate.id.desc())
        .first()
    )

    next_version = (last_version.version + 1) if last_version else 1
    storage_path = build_storage_path(
        office_id=office_id,
        doc_key=doc_key,
        version=next_version,
        original_filename=original_filename,
    )

    try:
        write_template_bytes(file_bytes, storage_path)

        (
            db.query(OfficeDocumentTemplate)
            .filter(
                OfficeDocumentTemplate.office_id == office_id,
                OfficeDocumentTemplate.doc_key == doc_key,
                OfficeDocumentTemplate.is_active == True,
            )
            .update({"is_active": False}, synchronize_session=False)
        )

        row = OfficeDocumentTemplate(
            office_id=office_id,
            created_by_user_id=user.id,
            doc_key=doc_key,
            display_name=get_doc_title(doc_key),
            original_filename=original_filename,
            storage_path=storage_path,
            file_size=len(file_bytes),
            version=next_version,
            is_active=True,
            detected_placeholders=detected_placeholders_to_json(
                validation["detected_placeholders"]
            ),
        )

        db.add(row)
        db.commit()

    except Exception:
        db.rollback()
        remove_file_silently(storage_path)
        raise

    return RedirectResponse(url="/doc-templates", status_code=303)


@router.get("/doc-templates/{template_id}/download")
def baixar_modelo(template_id: int, request: Request, db: Session = Depends(get_db)):
    user = _get_logged_user(request, db)
    office_id = request.session.get("office_id") or getattr(user, "office_id", None)

    row = (
        db.query(OfficeDocumentTemplate)
        .filter(
            OfficeDocumentTemplate.id == template_id,
            OfficeDocumentTemplate.office_id == office_id,
        )
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="Modelo não encontrado")

    if not row.storage_path or not os.path.exists(row.storage_path):
        raise HTTPException(status_code=404, detail="Arquivo do modelo não encontrado")

    return FileResponse(
        row.storage_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=row.original_filename,
    )


@router.post("/doc-templates/{template_id}/ativar")
def ativar_modelo(template_id: int, request: Request, db: Session = Depends(get_db)):
    user = _get_logged_user(request, db)
    office_id = request.session.get("office_id") or getattr(user, "office_id", None)

    row = (
        db.query(OfficeDocumentTemplate)
        .filter(
            OfficeDocumentTemplate.id == template_id,
            OfficeDocumentTemplate.office_id == office_id,
        )
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="Modelo não encontrado")

    (
        db.query(OfficeDocumentTemplate)
        .filter(
            OfficeDocumentTemplate.office_id == office_id,
            OfficeDocumentTemplate.doc_key == row.doc_key,
            OfficeDocumentTemplate.is_active == True,
        )
        .update({"is_active": False}, synchronize_session=False)
    )

    row.is_active = True
    db.commit()

    return RedirectResponse(url="/doc-templates", status_code=303)


@router.post("/doc-templates/{template_id}/excluir")
def excluir_modelo(template_id: int, request: Request, db: Session = Depends(get_db)):
    user = _get_logged_user(request, db)
    office_id = request.session.get("office_id") or getattr(user, "office_id", None)

    row = (
        db.query(OfficeDocumentTemplate)
        .filter(
            OfficeDocumentTemplate.id == template_id,
            OfficeDocumentTemplate.office_id == office_id,
        )
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="Modelo não encontrado")

    file_path = row.storage_path
    db.delete(row)
    db.commit()
    remove_file_silently(file_path)

    return RedirectResponse(url="/doc-templates", status_code=303)