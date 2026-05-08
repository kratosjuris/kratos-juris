# app/routers/web_account.py
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import hash_password, verify_password, validate_new_password
from app.models.user import User

router = APIRouter(prefix="/minha-conta", tags=["Minha Conta"])

APP_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = APP_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _current_user(request: Request) -> User | None:
    return getattr(request.state, "current_user", None)


@router.get("/alterar-senha", response_class=HTMLResponse)
def change_password_form(
    request: Request,
):
    user = _current_user(request)

    return templates.TemplateResponse(
        "account/change_password.html",
        {
            "request": request,
            "title": "Alterar senha",
            "user": user,
            "erro": None,
            "sucesso": None,
        },
    )


@router.post("/alterar-senha", response_class=HTMLResponse)
def change_password_submit(
    request: Request,
    db: Session = Depends(get_db),
    senha_atual: str = Form(""),
    nova_senha: str = Form(""),
    confirmar_senha: str = Form(""),
):
    current_user = _current_user(request)

    if not current_user:
        return templates.TemplateResponse(
            "account/change_password.html",
            {
                "request": request,
                "title": "Alterar senha",
                "user": None,
                "erro": "Usuário não autenticado.",
                "sucesso": None,
            },
            status_code=401,
        )

    user = (
        db.query(User)
        .filter(User.id == current_user.id)
        .first()
    )

    if not user:
        return templates.TemplateResponse(
            "account/change_password.html",
            {
                "request": request,
                "title": "Alterar senha",
                "user": current_user,
                "erro": "Usuário não encontrado.",
                "sucesso": None,
            },
            status_code=404,
        )

    if not verify_password(senha_atual, user.password_hash):
        return templates.TemplateResponse(
            "account/change_password.html",
            {
                "request": request,
                "title": "Alterar senha",
                "user": user,
                "erro": "Senha atual incorreta.",
                "sucesso": None,
            },
            status_code=400,
        )

    ok, erro = validate_new_password(
        nova_senha,
        confirmar_senha,
    )

    if not ok:
        return templates.TemplateResponse(
            "account/change_password.html",
            {
                "request": request,
                "title": "Alterar senha",
                "user": user,
                "erro": erro,
                "sucesso": None,
            },
            status_code=400,
        )

    user.password_hash = hash_password(nova_senha)
    user.must_change_password = False

    db.add(user)
    db.commit()

    return templates.TemplateResponse(
        "account/change_password.html",
        {
            "request": request,
            "title": "Alterar senha",
            "user": user,
            "erro": None,
            "sucesso": "Senha alterada com sucesso.",
        },
    )