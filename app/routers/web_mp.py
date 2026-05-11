# app/routers/web_mp.py
from __future__ import annotations

import re
import secrets
import string

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from app.core.config import TEMPLATES_DIR
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.office import Office
from app.models.user import User
from app.services.mercadopago import sdk, get_app_base_url


router = APIRouter(tags=["Mercado Pago"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _generate_temp_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _slug_username(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "", value)

    if not value:
        value = "admin"

    return value[:60]


def _split_external_reference(external_reference: str | None) -> tuple[str, str]:
    raw = (external_reference or "").strip()

    if "|" not in raw:
        return "Novo Escritório Kratos", ""

    office_nome, email = raw.split("|", 1)

    return office_nome.strip(), email.strip().lower()


def _create_office_and_admin_from_payment(payment_data: dict) -> dict:
    """
    Cria Office + User admin quando o pagamento estiver aprovado.
    Evita duplicidade por e-mail e por nome de escritório.
    """

    status = payment_data.get("status")
    payment_id = str(payment_data.get("id") or "")
    external_reference = payment_data.get("external_reference")

    office_nome, email = _split_external_reference(external_reference)

    payer = payment_data.get("payer") or {}
    additional_info = payment_data.get("additional_info") or {}
    additional_payer = additional_info.get("payer") or {}

    admin_nome = (
        additional_payer.get("first_name")
        or payer.get("first_name")
        or office_nome
        or "Administrador"
    )

    if not email:
        email = (payer.get("email") or "").strip().lower()

    if status != "approved":
        return {
            "created": False,
            "reason": "Pagamento ainda não aprovado.",
            "payment_status": status,
            "payment_id": payment_id,
        }

    if not email:
        return {
            "created": False,
            "reason": "Não foi possível identificar o e-mail do contratante.",
            "payment_status": status,
            "payment_id": payment_id,
        }

    db = SessionLocal()

    try:
        existing_user = db.query(User).filter(User.email == email).first()

        if existing_user:
            office = None

            if existing_user.office_id:
                office = (
                    db.query(Office)
                    .filter(Office.id == existing_user.office_id)
                    .first()
                )

            if office:
                office.reactivate()
                existing_user.reactivate()
                db.commit()

            return {
                "created": False,
                "already_exists": True,
                "reason": "Já existe usuário com este e-mail. Acesso reativado, se aplicável.",
                "office_id": existing_user.office_id,
                "user_id": existing_user.id,
                "username": existing_user.username,
                "email": existing_user.email,
                "payment_id": payment_id,
            }

        existing_office = (
            db.query(Office)
            .filter(Office.nome.ilike(office_nome))
            .first()
        )

        if existing_office:
            office = existing_office
            office.reactivate()
        else:
            finance_password = _generate_temp_password()

            office = Office(
                nome=office_nome,
                finance_password_hash=hash_password(finance_password),
            )

            db.add(office)
            db.flush()

        username_base = _slug_username(email.split("@")[0])
        username = username_base

        counter = 1
        while db.query(User).filter(User.username == username).first():
            counter += 1
            username = f"{username_base}{counter}"

        temp_password = _generate_temp_password()

        admin = User(
            nome=admin_nome,
            email=email,
            username=username,
            password_hash=hash_password(temp_password),
            office_id=office.id,
            is_active=True,
            is_superuser=False,
            must_change_password=True,
        )

        db.add(admin)
        db.commit()
        db.refresh(office)
        db.refresh(admin)

        return {
            "created": True,
            "office_id": office.id,
            "office_nome": office.nome,
            "user_id": admin.id,
            "nome": admin.nome,
            "email": admin.email,
            "username": admin.username,
            "temporary_password": temp_password,
            "payment_id": payment_id,
        }

    except Exception as e:
        db.rollback()

        return {
            "created": False,
            "reason": f"Erro ao criar escritório/usuário: {e}",
            "payment_id": payment_id,
        }

    finally:
        db.close()


@router.get("/mp/test")
def mp_test():
    base_url = get_app_base_url()

    preference_data = {
        "items": [
            {
                "title": "Assinatura Kratos Juris - Teste",
                "description": "Teste de integração Mercado Pago com Kratos Juris",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": 59.90,
            }
        ],
        "back_urls": {
            "success": f"{base_url}/mp/success",
            "failure": f"{base_url}/mp/failure",
            "pending": f"{base_url}/mp/pending",
        },
        "external_reference": "kratos_test_001",
    }

    response = sdk.preference().create(preference_data)

    return JSONResponse(content=response)


@router.get("/mp/success")
def mp_success(request: Request):
    query_params = dict(request.query_params)

    payment_id = (
        query_params.get("payment_id")
        or query_params.get("collection_id")
        or query_params.get("data.id")
    )

    status = query_params.get("status")
    preference_id = query_params.get("preference_id")
    external_reference = query_params.get("external_reference")
    merchant_order_id = query_params.get("merchant_order_id")

    payment_data = None
    activation_result = None

    if payment_id:
        try:
            payment_response = sdk.payment().get(payment_id)

            print("========== MERCADO PAGO PAYMENT GET ==========")
            print(payment_response)
            print("==============================================")

            payment_data = payment_response.get("response", {})

            status = payment_data.get("status") or status
            external_reference = (
                payment_data.get("external_reference")
                or external_reference
            )

            if status == "approved":
                activation_result = _create_office_and_admin_from_payment(payment_data)

        except Exception as e:
            payment_data = {
                "erro": f"Erro ao consultar pagamento no Mercado Pago: {e}"
            }

    return templates.TemplateResponse(
        "public/payment_success.html",
        {
            "request": request,
            "status": "success",
            "message": "Pagamento aprovado ou retorno de sucesso do Mercado Pago.",
            "payment_id": payment_id,
            "payment_status": status,
            "preference_id": preference_id,
            "external_reference": external_reference,
            "merchant_order_id": merchant_order_id,
            "payment_data": payment_data,
            "activation_result": activation_result,
            "query_params": query_params,
        },
    )


@router.get("/mp/failure")
def mp_failure(request: Request):
    query_params = dict(request.query_params)

    return templates.TemplateResponse(
        "public/payment_failure.html",
        {
            "request": request,
            "status": "failure",
            "message": "Pagamento recusado, cancelado ou não concluído.",
            "query_params": query_params,
        },
    )


@router.get("/mp/pending")
def mp_pending(request: Request):
    query_params = dict(request.query_params)

    return templates.TemplateResponse(
        "public/payment_pending.html",
        {
            "request": request,
            "status": "pending",
            "message": "Pagamento pendente de confirmação.",
            "query_params": query_params,
        },
    )


@router.post("/mp/webhook")
async def mp_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    query_params = dict(request.query_params)

    payment_id = None

    if isinstance(payload, dict):
        data = payload.get("data") or {}

        if isinstance(data, dict):
            payment_id = data.get("id")

        payment_id = (
            payment_id
            or payload.get("id")
            or payload.get("payment_id")
            or query_params.get("id")
            or query_params.get("data.id")
        )

    payment_data = None
    activation_result = None

    if payment_id:
        try:
            payment_response = sdk.payment().get(payment_id)
            payment_data = payment_response.get("response", {})

            if payment_data.get("status") == "approved":
                activation_result = _create_office_and_admin_from_payment(payment_data)

        except Exception as e:
            payment_data = {
                "erro": f"Erro ao consultar pagamento no Mercado Pago: {e}"
            }

    print("========== WEBHOOK MERCADO PAGO ==========")
    print("QUERY PARAMS:", query_params)
    print("PAYLOAD:", payload)
    print("PAYMENT_ID:", payment_id)
    print("PAYMENT_DATA:", payment_data)
    print("ACTIVATION_RESULT:", activation_result)
    print("==========================================")

    return {
        "received": True,
        "payment_id": payment_id,
        "payment_data": payment_data,
        "activation_result": activation_result,
    }