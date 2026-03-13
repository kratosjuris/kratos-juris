from datetime import date
import urllib.parse

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import extract

from app.core.database import get_db
from app.models.client import Client

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _normalize_phone_br(phone: str | None) -> str | None:
    """
    Normaliza telefone para formato aceito pelo wa.me:
    - remove caracteres não numéricos
    - adiciona DDI 55 se não existir
    """
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        return None
    if digits.startswith("55"):
        return digits
    return "55" + digits


@router.get("/aniversarios", response_class=HTMLResponse)
def aniversarios_mes(request: Request, db: Session = Depends(get_db)):
    hoje = date.today()
    mes = hoje.month

    clientes = (
        db.query(Client)
        .filter(Client.nascimento.is_not(None))
        .filter(extract("month", Client.nascimento) == mes)
        .order_by(extract("day", Client.nascimento).asc(), Client.nome.asc())
        .all()
    )

    itens = []
    for c in clientes:
        fone = _normalize_phone_br(c.telefone)

        msg = (
            f"Olá, {c.nome}! 🎉\n\n"
            f"A equipe do Escritório Clementino & Silva Lopes "
            f"lhe deseja um Feliz Aniversário!\n\n"
            f"Que este novo ano de vida seja repleto de saúde, conquistas e tranquilidade. "
            f"Reafirmamos nosso compromisso de estarmos sempre à sua disposição, "
            f"lado a lado, para auxiliá-lo(a) em todas as demandas jurídicas que se fizerem necessárias.\n\n"
            f"Conte sempre conosco.\n"
            f"Atenciosamente,\n"
            f"Escritório Clementino & Silva Lopes"
        )

        wa = None
        if fone:
            wa = f"https://wa.me/{fone}?text={urllib.parse.quote(msg)}"

        itens.append({"c": c, "wa": wa})

    return templates.TemplateResponse(
        "birthdays/month.html",
        {"request": request, "title": "Aniversariantes do mês", "hoje": hoje, "itens": itens},
    )
