# app/routers/web_superadmin_assinantes.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.database import get_db
from app.models.office import Office
from app.models.subscription import Subscription
from app.models.user import User


router = APIRouter(tags=["Superadmin - Assinantes"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/superadmin/assinantes")
def superadmin_assinantes(
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = getattr(request.state, "current_user", None)

    if not current_user or not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="Acesso restrito aos superadministradores.",
        )

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