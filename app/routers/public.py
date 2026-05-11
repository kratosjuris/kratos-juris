from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.client_invite import ClientInvite

router = APIRouter()

@router.get("/cadastro/{token}", response_class=HTMLResponse)
def form_cadastro(token: str, request: Request, db: Session = Depends(get_db)):
    invite = db.query(ClientInvite).filter_by(token=token).first()

    if not invite or invite.used:
        return HTMLResponse("<h3>Link inválido ou já utilizado</h3>")

    return request.app.state.templates.TemplateResponse(
        "public/public_form.html",
        {"request": request, "token": token}
    )