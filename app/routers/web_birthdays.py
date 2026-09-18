from app.core.datetime_utils import now_br
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import extract

from app.core.database import get_db
from app.models.client import Client
from app.services.whatsapp import (
    build_wa_me_link,
    build_client_message,
    build_client_message_from_template_text,
    ensure_default_whatsapp_templates,
    get_active_template,
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


def _get_office_name(request: Request) -> str:
    current_user = getattr(request.state, "current_user", None)
    office = getattr(current_user, "office", None) if current_user else None
    office_name = getattr(office, "nome", None) if office else None
    return (office_name or "Escritório").strip()


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
    office_id = _get_office_id(request)
    user_id = _get_user_id(request)
    office_name = _get_office_name(request)

    hoje = now_br().date()
    mes = hoje.month

    clientes = (
        db.query(Client)
        .filter(
            Client.office_id == office_id,
            Client.nascimento.is_not(None),
            extract("month", Client.nascimento) == mes,
        )
        .order_by(extract("day", Client.nascimento).asc(), Client.nome.asc())
        .all()
    )

    # ✅ CORREÇÃO: o template de mensagem é o mesmo para todo mundo nesta
    # lista (mesmo office_id, mesmo tipo="aniversario_cliente"). Antes,
    # essa busca rodava uma vez POR CLIENTE dentro do loop abaixo — com
    # muitos aniversariantes, isso virava dezenas de idas ao banco
    # repetindo a mesma pergunta. Agora busca uma única vez, aqui fora.
    ensure_default_whatsapp_templates(db, office_id=office_id, user_id=user_id)
    tpl = get_active_template(db, office_id=office_id, tipo="aniversario_cliente")

    itens = []
    for c in clientes:
        fone = _normalize_phone_br(getattr(c, "telefone", None) or getattr(c, "phone", None))
        nome_cliente = getattr(c, "nome", None) or getattr(c, "name", None) or "Cliente"

        # Mesma lógica que build_client_message_from_template já fazia,
        # só que sem consultar o banco a cada iteração: usa o template
        # já carregado, ou cai no texto padrão se não houver template ativo.
        if tpl:
            msg = build_client_message_from_template_text(
                template_text=tpl.conteudo,
                client_name=nome_cliente,
                process_number="",
                promovido="",
                starts_at=None,
                modalidade="",
                extension_code=None,
                office_name=office_name,
            )
        else:
            msg = build_client_message(
                client_name=nome_cliente,
                process_number="",
                promovido="",
                starts_at=None,
                modalidade="",
                extension_code=None,
                public_base_url="",
                office_name=office_name,
            )

        wa = None
        if fone:
            wa = build_wa_me_link(fone, msg)

        itens.append({"c": c, "wa": wa})

    return templates.TemplateResponse(
        "birthdays/month.html",
        {
            "request": request,
            "title": "Aniversariantes do mês",
            "hoje": hoje,
            "itens": itens,
        },
    )