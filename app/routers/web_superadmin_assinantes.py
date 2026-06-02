# app/routers/web_superadmin_assinantes.py
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.database import get_db
from app.models.office import Office
from app.models.subscription import Subscription
from app.models.user import User
from app.services.mercadopago import sdk, get_app_base_url


router = APIRouter(tags=["Superadmin - Assinantes"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _require_superadmin(request: Request):
    current_user = getattr(request.state, "current_user", None)

    if not current_user or not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="Acesso restrito aos superadministradores.",
        )

    return current_user


@router.get("/superadmin/assinantes")
def superadmin_assinantes(
    request: Request,
    db: Session = Depends(get_db),
):
    _require_superadmin(request)

    assinantes = (
        db.query(Subscription, Office)
        .join(Office, Office.id == Subscription.office_id)
        .order_by(Subscription.created_at.desc())
        .all()
    )

    dados = []

    for subscription, office in assinantes:
        admin = (
            db.query(User)
            .filter(
                User.office_id == office.id,
                User.is_superuser == False,
            )
            .order_by(User.id.asc())
            .first()
        )

        dados.append(
            {
                "subscription": subscription,
                "office": office,
                "admin": admin,
            }
        )

    return templates.TemplateResponse(
        "superadmin/assinantes.html",
        {
            "request": request,
            "assinantes": dados,
        },
    )


@router.get("/superadmin/assinantes/{subscription_id}/gerar-link-recorrente")
def gerar_link_recorrente(
    subscription_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _require_superadmin(request)

    subscription = (
        db.query(Subscription)
        .filter(Subscription.id == subscription_id)
        .first()
    )

    if not subscription:
        raise HTTPException(status_code=404, detail="Assinatura não encontrada.")

    office = (
        db.query(Office)
        .filter(Office.id == subscription.office_id)
        .first()
    )

    if not office:
        raise HTTPException(status_code=404, detail="Escritório não encontrado.")

    admin = (
        db.query(User)
        .filter(
            User.office_id == office.id,
            User.is_superuser == False,
        )
        .order_by(User.id.asc())
        .first()
    )

    email = (
        subscription.mercadopago_email
        or (admin.email if admin else "")
        or ""
    ).strip().lower()

    if not email:
        raise HTTPException(
            status_code=400,
            detail="Não foi possível localizar o e-mail do assinante.",
        )

    base_url = get_app_base_url()

    is_local = (
        "127.0.0.1" in base_url
        or "localhost" in base_url
        or base_url.startswith("http://")
    )

    if is_local:
        raise HTTPException(
            status_code=400,
            detail="A geração de assinatura recorrente exige URL pública HTTPS.",
        )

    valor = float(subscription.valor or 59.90)
    external_reference = f"{office.nome}|{email}"
    start_date = datetime.utcnow() + timedelta(minutes=5)

    preapproval_data = {
        "reason": "Assinatura Kratos Juris",
        "external_reference": external_reference,
        "payer_email": email,
        "back_url": f"{base_url}/mp/success",
        "notification_url": f"{base_url}/mp/webhook",
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": valor,
            "currency_id": "BRL",
            "start_date": start_date.isoformat(timespec="seconds") + "Z",
        },
        "metadata": {
            "office_id": office.id,
            "office_nome": office.nome,
            "email": email,
            "admin_nome": admin.nome if admin else "",
        },
    }

    response = sdk.preapproval().create(preapproval_data)

    print("========== MERCADO PAGO PREAPPROVAL ADMIN ==========")
    print(response)
    print("====================================================")

    response_data = response.get("response", {})

    checkout_url = (
        response_data.get("init_point")
        or response_data.get("sandbox_init_point")
    )

    preapproval_id = response_data.get("id")
    preapproval_status = response_data.get("status")

    if not checkout_url:
        raise HTTPException(
            status_code=500,
            detail=f"Mercado Pago não retornou link recorrente: {response_data}",
        )

    subscription.mercadopago_preapproval_id = preapproval_id
    subscription.preapproval_status = preapproval_status
    subscription.recurring_checkout_url = checkout_url

    db.commit()
    db.refresh(subscription)

    return templates.TemplateResponse(
        "superadmin/link_recorrente.html",
        {
            "request": request,
            "subscription": subscription,
            "office": office,
            "admin": admin,
            "checkout_url": checkout_url,
        },
    )