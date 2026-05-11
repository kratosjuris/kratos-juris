# app/services/mercadopago.py
from __future__ import annotations

import os
import mercadopago


MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
MP_PUBLIC_KEY = os.getenv("MP_PUBLIC_KEY")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")


if not MP_ACCESS_TOKEN:
    raise RuntimeError(
        "MP_ACCESS_TOKEN não configurado. Verifique o arquivo .env ou as variáveis do Render."
    )


sdk = mercadopago.SDK(MP_ACCESS_TOKEN)


def get_public_key() -> str | None:
    return MP_PUBLIC_KEY


def get_app_base_url() -> str:
    return APP_BASE_URL.rstrip("/")