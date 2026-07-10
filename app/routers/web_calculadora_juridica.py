from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.services.calculos_atualizacao import calcular_atualizacao
from app.services.calculos_astreintes import calcular_astreintes
from app.services.calculadora_documentos import gerar_docx_calculadora
from app.services.indices_monetarios import atualizar_cache_indices, status_cache
from app.services.gerar_pdf_calculo import gerar_pdf_calculo
from app.services.gerar_pdf_astreintes import gerar_pdf_astreintes


router = APIRouter(tags=["Calculadora Jurídica"])
templates = Jinja2Templates(directory="app/templates")


def _get_logged_user(request: Request, db: Session) -> User:
    user_id = request.session.get("user_id")
    office_id = request.session.get("office_id")

    if not user_id:
        raise HTTPException(status_code=401, detail="Usuário não autenticado")

    user = db.query(User).filter(
        User.id == user_id,
        User.is_active == True,
    ).first()

    if not user:
        raise HTTPException(status_code=401, detail="Usuário inválido")

    if not office_id:
        office_id = getattr(user, "office_id", None)

    if not office_id:
        raise HTTPException(status_code=403, detail="Escritório não identificado")

    return user


@router.get("/calculadora-juridica", response_class=HTMLResponse)
def calculadora_index(request: Request, db: Session = Depends(get_db)):
    _get_logged_user(request, db)
    return templates.TemplateResponse(
        "calculadora_juridica/index.html",
        {"request": request},
    )


@router.get("/calculadora-juridica/atualizacao", response_class=HTMLResponse)
def atualizacao_form(request: Request, db: Session = Depends(get_db)):
    _get_logged_user(request, db)
    return templates.TemplateResponse(
        "calculadora_juridica/atualizacao_monetaria.html",
        {"request": request},
    )


@router.post("/calculadora-juridica/atualizacao/gerar", response_class=HTMLResponse)
async def gerar_atualizacao(
    request: Request,
    processo: str = Form(""),
    vara: str = Form(""),
    exequente: str = Form(""),
    executado: str = Form(""),
    data_final_calculo: str = Form(""),
    custas_valor: str = Form(""),
    lancamentos_json: str = Form("[]"),
    periodos_correcao_json: str = Form("[]"),
    periodos_juros_json: str = Form("[]"),
    deducoes_json: str = Form("[]"),
    multas_json: str = Form("[]"),
    honorarios_json: str = Form("[]"),
    db: Session = Depends(get_db),
):
    _get_logged_user(request, db)

    def _parse(s):
        try:
            return json.loads(s or "[]")
        except Exception:
            return []

    payload = {
        "processo":           processo,
        "vara":               vara,
        "exequente":          exequente,
        "executado":          executado,
        "data_final_calculo": data_final_calculo,
        "custas_valor":       custas_valor,
        "lancamentos":        _parse(lancamentos_json),
        "periodos_correcao":  _parse(periodos_correcao_json),
        "periodos_juros":     _parse(periodos_juros_json),
        "deducoes":           _parse(deducoes_json),
        "multas":             _parse(multas_json),
        "honorarios_lista":   _parse(honorarios_json),
    }

    resultado = calcular_atualizacao(payload)

    return templates.TemplateResponse(
        "calculadora_juridica/relatorio_atualizacao.html",
        {
            "request": request,
            "resultado": resultado,
            "resultado_json": json.dumps(resultado, ensure_ascii=False),
        },
    )


@router.post("/calculadora-juridica/atualizacao/pdf")
async def baixar_pdf_calculo(
    request: Request,
    resultado_json: str = Form(...),
    db: Session = Depends(get_db),
):
    _get_logged_user(request, db)

    try:
        resultado = json.loads(resultado_json or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Dados do cálculo inválidos")

    pdf_bytes = gerar_pdf_calculo(resultado)

    from app.services.calculos_utils import sanitize_filename
    processo = resultado.get("processo") or "calculo"
    filename = sanitize_filename(f"Calculo_{processo}.pdf")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/calculadora-juridica/atualizacao/documento")
async def gerar_documento_calculo(
    request: Request,
    doc_key: str = Form(...),
    resultado_json: str = Form(...),
    db: Session = Depends(get_db),
):
    user = _get_logged_user(request, db)
    office_id = request.session.get("office_id") or getattr(user, "office_id", None)

    allowed = {
        "memorial-calculo",
        "cumprimento-voluntario",
        "execucao-sentenca",
    }

    if doc_key not in allowed:
        raise HTTPException(status_code=400, detail="Documento inválido")

    try:
        resultado = json.loads(resultado_json or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Dados do cálculo inválidos")

    return gerar_docx_calculadora(
        db=db,
        office_id=office_id,
        doc_key=doc_key,
        resultado=resultado,
    )


@router.get("/calculadora-juridica/astreintes", response_class=HTMLResponse)
def astreintes_form(request: Request, db: Session = Depends(get_db)):
    _get_logged_user(request, db)
    return templates.TemplateResponse(
        "calculadora_juridica/astreintes.html",
        {"request": request},
    )


@router.post("/calculadora-juridica/astreintes/gerar", response_class=HTMLResponse)
async def gerar_astreintes(
    request: Request,
    processo: str = Form(""),
    vara: str = Form(""),
    exequente: str = Form(""),
    executado: str = Form(""),
    tipo_contagem: str = Form("corridos"),
    periodos_json: str = Form("[]"),
    db: Session = Depends(get_db),
):
    _get_logged_user(request, db)

    try:
        periodos = json.loads(periodos_json or "[]")
    except Exception:
        periodos = []

    resultado = calcular_astreintes(
        {
            "processo": processo,
            "vara": vara,
            "exequente": exequente,
            "executado": executado,
            "tipo_contagem": tipo_contagem,
            "periodos": periodos,
        }
    )

    return templates.TemplateResponse(
        "calculadora_juridica/relatorio_astreintes.html",
        {
            "request": request,
            "resultado": resultado,
            "resultado_json": json.dumps(resultado, ensure_ascii=False),
        },
    )


# ---------------------------------------------------------------------------
# Endpoint PDF — astreintes
# ---------------------------------------------------------------------------

@router.post("/calculadora-juridica/astreintes/pdf")
async def baixar_pdf_astreintes(
    request: Request,
    resultado_json: str = Form(...),
    db: Session = Depends(get_db),
):
    _get_logged_user(request, db)

    try:
        resultado = json.loads(resultado_json or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Dados do cálculo inválidos")

    pdf_bytes = gerar_pdf_astreintes(resultado)

    from app.services.calculos_utils import sanitize_filename
    processo  = resultado.get("processo") or "astreintes"
    filename  = sanitize_filename(f"Astreintes_{processo}.pdf")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Endpoints de administração — cache de índices monetários
# ---------------------------------------------------------------------------

@router.get("/calculadora-juridica/indices/status")
def indices_status(request: Request, db: Session = Depends(get_db)):
    _get_logged_user(request, db)
    return JSONResponse(content=status_cache())


@router.post("/calculadora-juridica/indices/atualizar")
async def indices_atualizar(request: Request, db: Session = Depends(get_db)):
    _get_logged_user(request, db)
    resultado = await atualizar_cache_indices()
    return JSONResponse(content=resultado)