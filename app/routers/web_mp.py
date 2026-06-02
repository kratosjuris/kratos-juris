# app/routers/web_mp.py
from __future__ import annotations

import re
import secrets
import string

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.core.config import TEMPLATES_DIR
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.office import Office
from app.models.office_permission import OfficePermission
from app.models.permission import Permission
from app.models.user import User
from app.models.subscription import Subscription
from app.services.mercadopago import sdk, get_app_base_url


router = APIRouter(tags=["Mercado Pago"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _generate_temp_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _slug_username(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "", value)
    return (value or "admin")[:60]


def _split_external_reference(external_reference: str | None) -> tuple[str, str]:
    raw = (external_reference or "").strip()

    if "|" not in raw:
        return "Novo Escritório Kratos", ""

    office_nome, email = raw.split("|", 1)
    return office_nome.strip(), email.strip().lower()


def _grant_all_permissions_to_office(db, office_id: int) -> None:
    all_permissions = db.query(Permission).all()

    for permission in all_permissions:
        exists = (
            db.query(OfficePermission)
            .filter(
                OfficePermission.office_id == office_id,
                OfficePermission.permission_id == permission.id,
            )
            .first()
        )

        if not exists:
            db.add(
                OfficePermission(
                    office_id=office_id,
                    permission_id=permission.id,
                )
            )


def _save_subscription(
    db,
    office_id: int,
    payment_id: str,
    payment_data: dict,
    email: str,
    status: str,
) -> None:
    payer = payment_data.get("payer") or {}

    payer_email = ""
    if isinstance(payer, dict):
        payer_email = (payer.get("email") or "").strip().lower()

    valor = float(payment_data.get("transaction_amount") or 59.90)

    existing_subscription = (
        db.query(Subscription)
        .filter(Subscription.mercadopago_payment_id == payment_id)
        .first()
    )

    if not existing_subscription:
        db.add(
            Subscription(
                office_id=office_id,
                mercadopago_payment_id=payment_id,
                mercadopago_email=payer_email or email,
                valor=valor,
                status=status,
            )
        )


def _update_subscription_from_preapproval(preapproval_data: dict) -> dict:
    preapproval_id = str(preapproval_data.get("id") or "").strip()
    preapproval_status = str(preapproval_data.get("status") or "").strip()

    external_reference = preapproval_data.get("external_reference")
    office_nome, email = _split_external_reference(external_reference)

    payer_email = (
        preapproval_data.get("payer_email")
        or preapproval_data.get("payer", {}).get("email")
        or email
        or ""
    ).strip().lower()

    checkout_url = (
        preapproval_data.get("init_point")
        or preapproval_data.get("sandbox_init_point")
        or ""
    )

    if not preapproval_id:
        return {
            "updated": False,
            "reason": "Preapproval sem ID.",
            "preapproval_status": preapproval_status,
        }

    db = SessionLocal()

    try:
        subscription = None

        subscription = (
            db.query(Subscription)
            .filter(text("mercadopago_preapproval_id = :preapproval_id"))
            .params(preapproval_id=preapproval_id)
            .first()
        )

        if not subscription and payer_email:
            subscription = (
                db.query(Subscription)
                .filter(Subscription.mercadopago_email == payer_email)
                .order_by(Subscription.id.desc())
                .first()
            )

        if not subscription and office_nome:
            office = (
                db.query(Office)
                .filter(Office.nome.ilike(office_nome))
                .first()
            )

            if office:
                subscription = (
                    db.query(Subscription)
                    .filter(Subscription.office_id == office.id)
                    .order_by(Subscription.id.desc())
                    .first()
                )

        if not subscription:
            return {
                "updated": False,
                "reason": "Nenhuma assinatura local encontrada para vincular ao preapproval.",
                "preapproval_id": preapproval_id,
                "preapproval_status": preapproval_status,
                "payer_email": payer_email,
            }

        db.execute(
            text(
                """
                UPDATE subscriptions
                SET
                    mercadopago_preapproval_id = :preapproval_id,
                    preapproval_status = :preapproval_status,
                    recurring_checkout_url = COALESCE(NULLIF(:checkout_url, ''), recurring_checkout_url),
                    recurring_confirmed_at =
                        CASE
                            WHEN :preapproval_status IN ('authorized', 'active') THEN NOW()
                            ELSE recurring_confirmed_at
                        END,
                    updated_at = NOW()
                WHERE id = :subscription_id
                """
            ),
            {
                "subscription_id": subscription.id,
                "preapproval_id": preapproval_id,
                "preapproval_status": preapproval_status,
                "checkout_url": checkout_url,
            },
        )

        db.commit()

        return {
            "updated": True,
            "subscription_id": subscription.id,
            "preapproval_id": preapproval_id,
            "preapproval_status": preapproval_status,
            "payer_email": payer_email,
        }

    except Exception as e:
        db.rollback()
        return {
            "updated": False,
            "reason": f"Erro ao atualizar recorrência: {e}",
            "preapproval_id": preapproval_id,
            "preapproval_status": preapproval_status,
        }

    finally:
        db.close()


def _create_office_and_admin_from_payment(payment_data: dict) -> dict:
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

        existing_office = (
            db.query(Office)
            .filter(Office.nome.ilike(office_nome))
            .first()
        )

        if existing_office:
            office = existing_office
            office.reactivate()
            db.flush()
        else:
            finance_password = _generate_temp_password()

            office = Office(
                nome=office_nome,
                finance_password_hash=hash_password(finance_password),
            )

            db.add(office)
            db.flush()

        _grant_all_permissions_to_office(db, office.id)

        temp_password = _generate_temp_password()

        if existing_user:
            existing_user.nome = admin_nome
            existing_user.office_id = office.id
            existing_user.is_active = True
            existing_user.is_superuser = False
            existing_user.must_change_password = True
            existing_user.password_hash = hash_password(temp_password)
            existing_user.deactivated_at = None
            existing_user.deactivation_reason = None

            _save_subscription(
                db=db,
                office_id=office.id,
                payment_id=payment_id,
                payment_data=payment_data,
                email=email,
                status=status,
            )

            db.commit()
            db.refresh(office)
            db.refresh(existing_user)

            return {
                "created": True,
                "reactivated_existing_user": True,
                "office_id": office.id,
                "office_nome": office.nome,
                "user_id": existing_user.id,
                "nome": existing_user.nome,
                "email": existing_user.email,
                "username": existing_user.username,
                "temporary_password": temp_password,
                "payment_id": payment_id,
                "reason": "Usuário existente foi vinculado/reativado e recebeu nova senha provisória.",
            }

        username_base = _slug_username(email.split("@")[0])
        username = username_base

        counter = 1
        while db.query(User).filter(User.username == username).first():
            counter += 1
            username = f"{username_base}{counter}"

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

        _save_subscription(
            db=db,
            office_id=office.id,
            payment_id=payment_id,
            payment_data=payment_data,
            email=email,
            status=status,
        )

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

    preapproval_id = (
        query_params.get("preapproval_id")
        or query_params.get("preapproval_plan_id")
        or query_params.get("id")
    )

    status = query_params.get("status")
    preference_id = query_params.get("preference_id")
    external_reference = query_params.get("external_reference")
    merchant_order_id = query_params.get("merchant_order_id")

    payment_data = None
    preapproval_data = None
    activation_result = None
    preapproval_result = None

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

    if preapproval_id:
        try:
            preapproval_response = sdk.preapproval().get(preapproval_id)

            print("========== MERCADO PAGO PREAPPROVAL GET ==========")
            print(preapproval_response)
            print("==================================================")

            preapproval_data = preapproval_response.get("response", {})
            preapproval_result = _update_subscription_from_preapproval(preapproval_data)

        except Exception as e:
            preapproval_data = {
                "erro": f"Erro ao consultar assinatura no Mercado Pago: {e}"
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
            "preapproval_id": preapproval_id,
            "preapproval_data": preapproval_data,
            "preapproval_result": preapproval_result,
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

    event_type = (
        query_params.get("type")
        or query_params.get("topic")
        or payload.get("type")
        or payload.get("topic")
        or payload.get("action")
        or ""
    )

    data = payload.get("data") or {}

    resource_id = None

    if isinstance(data, dict):
        resource_id = data.get("id")

    resource_id = (
        resource_id
        or payload.get("id")
        or payload.get("payment_id")
        or query_params.get("id")
        or query_params.get("data.id")
    )

    payment_data = None
    preapproval_data = None
    activation_result = None
    preapproval_result = None

    event_type_lower = str(event_type or "").lower()

    is_preapproval_event = (
        "preapproval" in event_type_lower
        or "subscription" in event_type_lower
        or "plan" in event_type_lower
    )

    if resource_id:
        if is_preapproval_event:
            try:
                preapproval_response = sdk.preapproval().get(resource_id)
                preapproval_data = preapproval_response.get("response", {})
                preapproval_result = _update_subscription_from_preapproval(preapproval_data)

            except Exception as e:
                preapproval_data = {
                    "erro": f"Erro ao consultar assinatura no Mercado Pago: {e}"
                }

        else:
            try:
                payment_response = sdk.payment().get(resource_id)
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
    print("EVENT_TYPE:", event_type)
    print("RESOURCE_ID:", resource_id)
    print("PAYMENT_DATA:", payment_data)
    print("PREAPPROVAL_DATA:", preapproval_data)
    print("ACTIVATION_RESULT:", activation_result)
    print("PREAPPROVAL_RESULT:", preapproval_result)
    print("==========================================")

    return {
        "received": True,
        "event_type": event_type,
        "resource_id": resource_id,
        "payment_data": payment_data,
        "preapproval_data": preapproval_data,
        "activation_result": activation_result,
        "preapproval_result": preapproval_result,
    }