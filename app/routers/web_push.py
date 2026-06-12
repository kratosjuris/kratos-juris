from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.database import SessionLocal
from app.core.session_manager import get_session_user_id, get_session_office_id

from app.models.push_subscription import PushSubscription
from app.services.push_service import send_push_to_users


router = APIRouter(tags=["push"])

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "").strip()


# =========================================================
# CHAVE PÚBLICA — o frontend pega daqui para se inscrever
# =========================================================
@router.get("/push/public-key", include_in_schema=False)
def push_public_key():
    return {"publicKey": VAPID_PUBLIC_KEY}


# =========================================================
# SALVAR / ATUALIZAR INSCRIÇÃO
# =========================================================
@router.post("/push/subscribe", include_in_schema=False)
async def push_subscribe(request: Request):
    """
    Recebe a inscrição gerada pelo navegador e salva no Neon,
    ligada ao usuário logado. Idempotente: se o endpoint já existir,
    apenas atualiza as chaves.
    """

    user_id = get_session_user_id(request)
    office_id = get_session_office_id(request)

    if not user_id:
        return JSONResponse({"ok": False, "error": "não autenticado"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "json inválido"}, status_code=400)

    endpoint = (body or {}).get("endpoint")
    keys = (body or {}).get("keys") or {}
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        return JSONResponse({"ok": False, "error": "dados incompletos"}, status_code=400)

    user_agent = request.headers.get("user-agent", "")[:400]

    db = SessionLocal()
    try:
        sub = (
            db.query(PushSubscription)
            .filter(PushSubscription.endpoint == endpoint)
            .first()
        )

        if sub:
            sub.user_id = user_id
            sub.office_id = office_id
            sub.p256dh = p256dh
            sub.auth = auth
            sub.user_agent = user_agent
        else:
            sub = PushSubscription(
                user_id=user_id,
                office_id=office_id,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                user_agent=user_agent,
            )
            db.add(sub)

        db.commit()
        return {"ok": True}

    except Exception as e:
        db.rollback()
        print(f"[PUSH] erro ao salvar inscrição: {e}")
        return JSONResponse({"ok": False, "error": "erro interno"}, status_code=500)

    finally:
        db.close()


# =========================================================
# CANCELAR INSCRIÇÃO (quando o usuário desativa)
# =========================================================
@router.post("/push/unsubscribe", include_in_schema=False)
async def push_unsubscribe(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}

    endpoint = (body or {}).get("endpoint")
    if not endpoint:
        return JSONResponse({"ok": False}, status_code=400)

    db = SessionLocal()
    try:
        db.query(PushSubscription).filter(
            PushSubscription.endpoint == endpoint
        ).delete(synchronize_session=False)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# =========================================================
# DISPARO DE TESTE — só para o próprio usuário logado
# =========================================================
@router.post("/push/test", include_in_schema=False)
def push_test(request: Request):
    """
    Envia uma notificação de teste para o próprio usuário.
    Útil para validar a configuração ponta a ponta.
    """

    user_id = get_session_user_id(request)
    if not user_id:
        return JSONResponse({"ok": False, "error": "não autenticado"}, status_code=401)

    enviados = send_push_to_users(
        [user_id],
        {
            "title": "Kratos Juris",
            "body": "Notificações ativadas com sucesso! ⚖️",
            "url": "/dashboard",
            "tag": "teste",
        },
    )

    return {"ok": True, "enviados": enviados}