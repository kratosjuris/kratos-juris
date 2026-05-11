# app/core/config.py
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

APP_ENV = os.getenv("APP_ENV", "development")
SECRET_KEY = os.getenv("SECRET_KEY", "troque-esta-chave-em-producao")
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "kratos_session")
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", "28800"))  # 8 horas
SECURE_COOKIES = os.getenv("SECURE_COOKIES", "false").lower() == "true"

TEMPLATES_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "app" / "static"