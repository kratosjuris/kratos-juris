from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.services.mercadopago import sdk, get_app_base_url


router = APIRouter(tags=["Assinatura Pública"])

templates = Jinja2Templates(directory="app/templates")


# =========================================================
# PÁGINA DE ASSINATURA
# =========================================================
@router.get("/assinar")
def assinar_page(request: Request):

    return templates.TemplateResponse(
        "public/assinar.html",
        {
            "request": request,
        },
    )


# =========================================================
# TERMOS DE USO
# =========================================================
@router.get("/termos")
def termos_page(request: Request):

    return templates.TemplateResponse(
        "public/termos.html",
        {
            "request": request,
        },
    )


# =========================================================
# PROCESSAMENTO DA ASSINATURA RECORRENTE
# =========================================================
@router.post("/assinar")
def assinar_submit(
    request: Request,
    responsavel: str = Form(...),
    escritorio: str = Form(...),
    email: str = Form(...),
    telefone: str = Form(...),
):

    base_url = get_app_base_url()

    is_local = (
        "127.0.0.1" in base_url
        or "localhost" in base_url
        or base_url.startswith("http://")
    )

    if is_local:
        return JSONResponse(
            status_code=400,
            content={
                "erro": "Assinatura recorrente exige URL pública HTTPS.",
                "detalhe": "Use o sistema publicado no Render para criar assinaturas recorrentes.",
                "base_url_atual": base_url,
            },
        )

    external_reference = f"{escritorio}|{email}"

    start_date = datetime.utcnow() + timedelta(minutes=10)
    start_date_mp = start_date.strftime("%Y-%m-%dT%H:%M:%S.000+00:00")

    preapproval_data = {
        "reason": "Assinatura Kratos Juris",
        "external_reference": external_reference,
        "payer_email": email.strip().lower(),

        "back_url": f"{base_url}/mp/success",
        "notification_url": f"{base_url}/mp/webhook",

        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": 59.90,
            "currency_id": "BRL",
            "start_date": start_date_mp,
        },

        "metadata": {
            "responsavel": responsavel,
            "escritorio": escritorio,
            "email": email,
            "telefone": telefone,
        },
    }

    response = sdk.preapproval().create(preapproval_data)

    print("========== MERCADO PAGO PREAPPROVAL RESPONSE ==========")
    print(response)
    print("=======================================================")

    response_data = response.get("response", {})

    checkout_url = (
        response_data.get("init_point")
        or response_data.get("sandbox_init_point")
    )

    if not checkout_url:
        return JSONResponse(
            status_code=500,
            content={
                "erro": "Mercado Pago não retornou URL de assinatura recorrente.",
                "mercado_pago_response": response_data,
            },
        )

    return RedirectResponse(
        url=checkout_url,
        status_code=303,
    )