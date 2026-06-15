"""
app/scripts/rodar_monitor.py

Script CLI para executar o monitoramento DJEN manualmente ou via cron externo.

Uso:
    # Roda para ontem (padrão do job diário):
    python -m app.scripts.rodar_monitor

    # Roda para um período específico:
    python -m app.scripts.rodar_monitor --inicio 2026-06-01 --fim 2026-06-14

    # Roda só para uma OAB específica:
    python -m app.scripts.rodar_monitor --oab 123456 --uf BA

Configuração cron (todo dia às 7h, horário de Brasília):
    0 7 * * * /caminho/para/venv/bin/python -m app.scripts.rodar_monitor >> /var/log/monitor_djen.log 2>&1

IMPORTANTE: se o projeto já usa o APScheduler registrado em main.py
(recomendado), este script é opcional — serve apenas para execução manual
pontual ou fallback via cron externo.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path

# Garante que o pacote raiz (onde fica 'app/') está no sys.path,
# independente de onde o script é chamado.
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Carrega .env antes de qualquer import do app
from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

from app.core.database import SessionLocal
from app.models.oab_monitorada import OabMonitorada
from app.services.monitor_djen import rodar_monitoramento, monitorar_oab

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("rodar_monitor")


def _parse_date(s: str) -> date:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s.strip())
    if not m:
        raise argparse.ArgumentTypeError(
            f"Data inválida '{s}'. Use o formato AAAA-MM-DD."
        )
    y, mo, d = m.groups()
    return date(int(y), int(mo), int(d))


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Monitora o DJEN para todas as OABs ativas (ou uma específica).",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument(
        "--inicio",
        type=_parse_date,
        default=None,
        metavar="AAAA-MM-DD",
        help="Data de início do período (default: ontem)",
    )
    p.add_argument(
        "--fim",
        type=_parse_date,
        default=None,
        metavar="AAAA-MM-DD",
        help="Data de fim do período (default: ontem)",
    )
    p.add_argument(
        "--oab",
        type=str,
        default=None,
        metavar="NUMERO",
        help="Filtrar por número de OAB específico (ex: 123456)",
    )
    p.add_argument(
        "--uf",
        type=str,
        default=None,
        metavar="UF",
        help="UF da OAB (obrigatório se --oab for informado)",
    )
    p.add_argument(
        "--office-id",
        type=int,
        default=None,
        metavar="ID",
        help="Filtrar por office_id específico",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas lista as OABs que seriam monitoradas, sem executar",
    )
    return p


async def _main_async(args: argparse.Namespace) -> int:
    from datetime import date as date_type

    hoje = date_type.today()
    data_inicio = args.inicio or (hoje - timedelta(days=1))
    data_fim    = args.fim    or (hoje - timedelta(days=1))

    if data_inicio > data_fim:
        logger.error("--inicio não pode ser posterior a --fim.")
        return 1

    if (data_fim - data_inicio).days > 90:
        logger.error("Período máximo permitido: 90 dias.")
        return 1

    # ---- modo OAB específica ----
    if args.oab:
        if not args.uf:
            logger.error("--uf é obrigatório quando --oab é informado.")
            return 1

        num = re.sub(r"\D+", "", args.oab)
        uf  = args.uf.strip().upper()[:2]

        db = SessionLocal()
        try:
            query = db.query(OabMonitorada).filter(
                OabMonitorada.numero_oab == num,
                OabMonitorada.uf_oab == uf,
            )
            if args.office_id:
                query = query.filter(OabMonitorada.office_id == args.office_id)

            oab = query.first()

            if not oab:
                logger.error(
                    f"OAB {num}/{uf} não encontrada no banco "
                    f"(office_id={args.office_id or 'qualquer'})."
                )
                return 1

            if args.dry_run:
                logger.info(f"[DRY-RUN] Monitoraria: {oab}")
                return 0

            logger.info(f"Monitorando OAB {num}/{uf} — "
                        f"{data_inicio:%d/%m/%Y} a {data_fim:%d/%m/%Y}")
            resultado = await monitorar_oab(db, oab, data_inicio, data_fim)
            logger.info(
                f"Concluído — inseridos: {resultado['total_inseridos']} | "
                f"extraídos: {resultado['total_extraidos']} | "
                f"ignorados: {resultado['total_ignorados']}"
            )
            if resultado["erros"]:
                for err in resultado["erros"]:
                    logger.warning(f"  Erro: {err}")
        finally:
            db.close()

        return 0

    # ---- modo todas as OABs ativas ----
    if args.dry_run:
        db = SessionLocal()
        try:
            query = db.query(OabMonitorada).filter(OabMonitorada.ativa == True)  # noqa: E712
            if args.office_id:
                query = query.filter(OabMonitorada.office_id == args.office_id)
            oabs = query.all()
            logger.info(f"[DRY-RUN] {len(oabs)} OAB(s) seriam monitoradas:")
            for o in oabs:
                logger.info(f"  → {o}")
        finally:
            db.close()
        return 0

    logger.info(
        f"Iniciando monitoramento completo — "
        f"{data_inicio:%d/%m/%Y} a {data_fim:%d/%m/%Y}"
    )
    await rodar_monitoramento(data_inicio, data_fim)
    logger.info("Monitoramento completo concluído.")
    return 0


def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    exit_code = asyncio.run(_main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()