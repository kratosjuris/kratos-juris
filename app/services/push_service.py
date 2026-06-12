from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Iterable

from pywebpush import webpush, WebPushException

from app.core.database import SessionLocal
from app.models.push_subscription import PushSubscription


# =========================================================
# CONFIG VAPID (lidas do .env)
# =========================================================
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").strip()
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "").strip()

# E-mail de contato exigido pelo padrão VAPID (troque pelo seu)
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:contato@kratosjuris.com").strip()

VAPID_CLAIMS = {"sub": VAPID_SUBJECT}


# =========================================================
# ENVIO PARA UMA INSCRIÇÃO
# =========================================================
def _send_to_subscription(sub: PushSubscription, payload: dict) -> bool:
    """
    Envia um push para UMA inscrição.
    Retorna True se enviado; False se a inscrição estiver morta
    (404/410) e dever ser removida.
    """

    try:
        webpush(
            subscription_info=sub.as_subscription_info(),
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=dict(VAPID_CLAIMS),
            ttl=60 * 60 * 12,  # guarda até 12h se o device estiver offline
        )
        return True

    except WebPushException as e:
        # 404/410 = inscrição expirada/cancelada -> sinaliza para remoção
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (404, 410):
            print(f"[PUSH] inscrição morta (status={status}), id={sub.id}")
            return False
        print(f"[PUSH] erro ao enviar para id={sub.id}: {e}")
        return True  # erro transitório; não apaga a inscrição

    except Exception as e:
        print(f"[PUSH] erro inesperado id={sub.id}: {e}")
        return True


# =========================================================
# ENVIO PARA UM CONJUNTO DE USUÁRIOS
# =========================================================
def send_push_to_users(user_ids: Iterable[int], payload: dict) -> int:
    """
    Envia o mesmo payload para todas as inscrições dos usuários informados.
    Remove automaticamente inscrições mortas. Retorna a quantidade enviada.

    payload esperado (livre, mas o sw.js usa estes campos):
        {
          "title": "Texto do título",
          "body": "Corpo da notificação",
          "url": "/dashboard",          # opcional: pra onde abrir ao tocar
          "tag": "aniversarios-07h"     # opcional: agrupa/atualiza
        }
    """

    user_ids = list({int(u) for u in user_ids})
    if not user_ids:
        return 0

    db = SessionLocal()
    enviados = 0
    mortas: list[int] = []

    try:
        subs = (
            db.query(PushSubscription)
            .filter(PushSubscription.user_id.in_(user_ids))
            .all()
        )

        for sub in subs:
            ok = _send_to_subscription(sub, payload)
            if ok:
                enviados += 1
                sub.last_used_at = datetime.utcnow()
            else:
                mortas.append(sub.id)

        # limpeza das inscrições mortas
        if mortas:
            db.query(PushSubscription).filter(
                PushSubscription.id.in_(mortas)
            ).delete(synchronize_session=False)

        db.commit()

    except Exception as e:
        db.rollback()
        print(f"[PUSH] erro no envio em lote: {e}")

    finally:
        db.close()

    print(f"[PUSH] enviados={enviados} mortas_removidas={len(mortas)}")
    return enviados


def send_push_to_office(office_id: int, payload: dict) -> int:
    """Envia para todos os usuários de um escritório."""

    db = SessionLocal()
    try:
        rows = (
            db.query(PushSubscription.user_id)
            .filter(PushSubscription.office_id == office_id)
            .distinct()
            .all()
        )
        user_ids = [r[0] for r in rows]
    finally:
        db.close()

    return send_push_to_users(user_ids, payload)