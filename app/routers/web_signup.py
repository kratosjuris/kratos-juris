from __future__ import annotations

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
# PROCESSAMENTO DA ASSINATURA
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

    preference_data = {
        "items": [
            {
                "title": "Assinatura Kratos Juris",
                "description": "Assinatura mensal do sistema Kratos Juris",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": 59.90,
            }
        ],

        "payer": {
            "name": responsavel,
            "email": email,
        },

        "back_urls": {
            "success": f"{base_url}/mp/success",
            "failure": f"{base_url}/mp/failure",
            "pending": f"{base_url}/mp/pending",
        },

        "external_reference": f"{escritorio}|{email}",
    }

    # Em produção, com HTTPS real no Render/domínio próprio,
    # o Mercado Pago aceita retorno automático e webhook.
    if not is_local:
        preference_data["auto_return"] = "approved"
        preference_data["notification_url"] = f"{base_url}/mp/webhook"

    response = sdk.preference().create(preference_data)

    print("========== MERCADO PAGO RESPONSE ==========")
    print(response)
    print("===========================================")

    response_data = response.get("response", {})

    checkout_url = (
        response_data.get("init_point")
        or response_data.get("sandbox_init_point")
    )

    if not checkout_url:

        return JSONResponse(
            status_code=500,
            content={
                "erro": "Mercado Pago não retornou URL de checkout.",
                "mercado_pago_response": response_data,
            },
        )

    return RedirectResponse(
        url=checkout_url,
        status_code=303,
    )