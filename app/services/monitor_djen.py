"""
app/services/monitor_djen.py

Serviço de monitoramento automático DJEN + DataJud.

Fluxo:
  - job_monitorar_djen(): chamado pelo APScheduler às 7h15.
    Calcula o período correto (feriados nacionais, segunda-feira, etc)
    e cria MonitorTarefa pendente por OAB ativa.
    O browser do advogado executa a consulta DJEN ao fazer login.

  - monitorar_oab(): cria uma MonitorTarefa imediata para execução
    via browser (botão '▶ Agora' na tela de OABs Monitoradas).

  - rodar_monitoramento(): mantido para compatibilidade com
    app/scripts/rodar_monitor.py (CLI).
"""

import re
import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from app.core.database import SessionLocal
from app.core.datetime_utils import now_br
from app.models.oab_monitorada import OabMonitorada, MonitorTarefa
from app.models.migration import MigrationBatch, MigrationRow, BatchStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes de API
# ---------------------------------------------------------------------------

DJEN_API_BASE        = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
DJEN_TIMEOUT         = 30.0
DJEN_ITENS_POR_PAGINA = 100
DJEN_MAX_PAGINAS     = 20

# URL do Cloudflare Worker proxy (variável de ambiente no Render)
DJEN_PROXY_URL = os.environ.get("DJEN_PROXY_URL", "").strip()

DATAJUD_API_BASE = "https://api-publica.datajud.cnj.jus.br"
DATAJUD_API_KEY  = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
DATAJUD_TIMEOUT  = 20.0

INSERT_CHUNK = 300

DATAJUD_TR_MAP = {
    ("8","01"):"tjac",("8","02"):"tjal",("8","03"):"tjap",("8","04"):"tjam",
    ("8","05"):"tjba",("8","06"):"tjce",("8","07"):"tjdft",("8","08"):"tjes",
    ("8","09"):"tjgo",("8","10"):"tjma",("8","11"):"tjmt",("8","12"):"tjms",
    ("8","13"):"tjmg",("8","14"):"tjpa",("8","15"):"tjpb",("8","16"):"tjpr",
    ("8","17"):"tjpe",("8","18"):"tjpi",("8","19"):"tjrj",("8","20"):"tjrn",
    ("8","21"):"tjrs",("8","22"):"tjro",("8","23"):"tjrr",("8","24"):"tjsc",
    ("8","25"):"tjse",("8","26"):"tjsp",("8","27"):"tjto",
    ("4","01"):"trf1",("4","02"):"trf2",("4","03"):"trf3",
    ("4","04"):"trf4",("4","05"):"trf5",("4","06"):"trf6",
    ("5","01"):"trt1",("5","02"):"trt2",("5","03"):"trt3",("5","04"):"trt4",
    ("5","05"):"trt5",("5","06"):"trt6",("5","07"):"trt7",("5","08"):"trt8",
    ("5","09"):"trt9",("5","10"):"trt10",("5","11"):"trt11",("5","12"):"trt12",
    ("5","13"):"trt13",("5","14"):"trt14",("5","15"):"trt15",("5","16"):"trt16",
    ("5","17"):"trt17",("5","18"):"trt18",("5","19"):"trt19",("5","20"):"trt20",
    ("5","21"):"trt21",("5","22"):"trt22",("5","23"):"trt23",("5","24"):"trt24",
    ("2","00"):"stf",("3","00"):"stj",
}

NUM_CNJ_RX = re.compile(r"^\D*(\d{7})\D?\d{2}\D?\d{4}\D?(\d{1})\D?(\d{2})\D?\d{4}\D*$")

DJEN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://comunica.pje.jus.br",
    "Referer": "https://comunica.pje.jus.br/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

# ---------------------------------------------------------------------------
# Feriados nacionais + cálculo de período
# ---------------------------------------------------------------------------

FERIADOS_FIXOS = {
    (1,  1),   # Ano Novo
    (21, 4),   # Tiradentes
    (1,  5),   # Dia do Trabalho
    (7,  9),   # Independência
    (12, 10),  # Nossa Senhora Aparecida
    (2,  11),  # Finados
    (15, 11),  # Proclamação da República
    (20, 11),  # Consciência Negra
    (25, 12),  # Natal
}


def _pascoa(ano: int) -> date:
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


def _feriados_moveis(ano: int) -> set:
    pascoa = _pascoa(ano)
    return {
        pascoa - timedelta(days=48),
        pascoa - timedelta(days=47),
        pascoa - timedelta(days=2),
        pascoa,
        pascoa + timedelta(days=60),
    }


def _eh_feriado(d: date) -> bool:
    if (d.day, d.month) in FERIADOS_FIXOS:
        return True
    if d in _feriados_moveis(d.year):
        return True
    return False


def _eh_dia_util(d: date) -> bool:
    return d.weekday() < 5 and not _eh_feriado(d)


def _calcular_periodo(hoje: date) -> tuple:
    """
    Calcula data_inicio e data_fim para o monitoramento.
    Retrocede até o último dia útil para cobrir fins de semana e feriados.
    """
    data_fim = hoje - timedelta(days=1)
    data_inicio = data_fim
    while not _eh_dia_util(data_inicio):
        data_inicio -= timedelta(days=1)
    return data_inicio, data_fim


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _safe_set(obj, field: str, value):
    if hasattr(obj, field):
        setattr(obj, field, value)


def _parse_date(s) -> Optional[date]:
    if not s:
        return None
    s = str(s).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _clean_text(txt: str) -> str:
    txt = (txt or "").replace("\u00a0", " ").replace("\ufffd", " ")
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def _identificar_tribunal(numero: str) -> Optional[str]:
    digits = re.sub(r"\D+", "", numero or "")
    if len(digits) != 20:
        return None
    return DATAJUD_TR_MAP.get((digits[13], digits[14:16]))


def _extrair_parte(fonte: dict, polo: str) -> Optional[str]:
    polo_upper = polo.strip().upper()
    for p in (fonte.get("partes") or []):
        campo_polo = p.get("polo") or ""
        if isinstance(campo_polo, dict):
            nome_polo = (campo_polo.get("nome") or "").strip().upper()
        else:
            nome_polo = str(campo_polo).strip().upper()
        if nome_polo.startswith(polo_upper[:3]):
            nome = (p.get("nome") or "").strip()
            if nome:
                return nome
    return None


def _resumo_movimentos(fonte: dict, limite: int = 5) -> str:
    movs = sorted(
        fonte.get("movimentos") or [],
        key=lambda m: m.get("dataHora") or "",
        reverse=True,
    )
    linhas = []
    for m in movs[:limite]:
        nome  = (m.get("nome") or "").strip()
        d_raw = (m.get("dataHora") or "")[:10]
        d_obj = _parse_date(d_raw)
        data_br = d_obj.strftime("%d/%m/%Y") if d_obj else d_raw
        if nome:
            linhas.append(f"{data_br} — {nome}")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Chamadas de API (assíncronas) — mantidas para uso do rodar_monitor.py
# ---------------------------------------------------------------------------

async def _fetch_djen(
    numero_oab: str,
    uf_oab: str,
    data_inicio: date,
    data_fim: date,
    client: httpx.AsyncClient,
) -> List[dict]:
    """Consulta DJEN com paginação automática. Usa proxy Cloudflare no Render."""
    todos: List[dict] = []
    num = re.sub(r"\D+", "", numero_oab)

    for pagina in range(1, DJEN_MAX_PAGINAS + 1):
        try:
            if DJEN_PROXY_URL:
                resp = await client.post(
                    DJEN_PROXY_URL,
                    json={
                        "numeroOab": num,
                        "ufOab": uf_oab.upper(),
                        "dataInicio": data_inicio.isoformat(),
                        "dataFim":    data_fim.isoformat(),
                        "pagina":     pagina,
                    },
                    timeout=DJEN_TIMEOUT,
                )
            else:
                resp = await client.get(
                    DJEN_API_BASE,
                    params={
                        "numeroOab": num,
                        "ufOab": uf_oab.upper(),
                        "dataDisponibilizacaoInicio": data_inicio.isoformat(),
                        "dataDisponibilizacaoFim":   data_fim.isoformat(),
                        "itensPorPagina": DJEN_ITENS_POR_PAGINA,
                        "pagina": pagina,
                    },
                    headers=DJEN_HEADERS,
                    timeout=DJEN_TIMEOUT,
                )
        except httpx.RequestError as e:
            raise RuntimeError(f"DJEN — falha de rede: {e}")

        if resp.status_code != 200:
            raise RuntimeError(f"DJEN retornou HTTP {resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            raise RuntimeError("DJEN — resposta não é JSON válido")

        itens = data.get("items") or data.get("result") or []
        if not isinstance(itens, list):
            itens = []

        todos.extend(itens)

        if len(itens) < DJEN_ITENS_POR_PAGINA:
            break

    return todos


async def _fetch_datajud(numero: str, tribunal: str, client: httpx.AsyncClient) -> Optional[dict]:
    digits = re.sub(r"\D+", "", numero)
    if not digits:
        return None
    url  = f"{DATAJUD_API_BASE}/api_publica_{tribunal}/_search"
    body = {"size": 1, "query": {"match": {"numeroProcesso": digits}}}
    hdrs = {"Authorization": f"APIKey {DATAJUD_API_KEY}", "Content-Type": "application/json"}
    try:
        resp = await client.post(url, json=body, headers=hdrs, timeout=DATAJUD_TIMEOUT)
    except httpx.RequestError:
        return None
    if resp.status_code != 200:
        return None
    try:
        hits = (resp.json().get("hits") or {}).get("hits") or []
        return hits[0].get("_source") if hits else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Persistência
# ---------------------------------------------------------------------------

def _insert_chunk(db: Session, rows: List[MigrationRow]) -> Tuple[int, int]:
    if not rows:
        return 0, 0
    inserted = blocked = 0
    try:
        db.bulk_save_objects(rows)
        db.commit()
        inserted = len(rows)
        db.expunge_all()
        return inserted, blocked
    except IntegrityError:
        db.rollback()
        for row in rows:
            try:
                db.add(row)
                db.commit()
                inserted += 1
            except IntegrityError:
                db.rollback()
                blocked += 1
            finally:
                db.expunge_all()
    except Exception:
        db.rollback()
        raise
    return inserted, blocked


# ---------------------------------------------------------------------------
# monitorar_oab — cria MonitorTarefa para execução via browser
# ✅ NOVO: em vez de chamar o DJEN diretamente (bloqueado no Render),
#    cria uma tarefa pendente que o browser executa no login.
# ---------------------------------------------------------------------------

async def monitorar_oab(
    db: Session,
    oab: OabMonitorada,
    data_inicio: date,
    data_fim: date,
) -> dict:
    """
    Cria uma MonitorTarefa pendente para execução via browser do advogado.
    Usado pelo botão '▶ Agora' e pelo job das 7h15.
    """
    tarefa = MonitorTarefa(
        office_id   = oab.office_id,
        oab_id      = oab.id,
        numero_oab  = oab.numero_oab,
        uf_oab      = oab.uf_oab,
        data_inicio = data_inicio,
        data_fim    = data_fim,
        status      = "PENDENTE",
        criado_em   = now_br(),
    )
    db.add(tarefa)
    db.commit()

    return {
        "total_extraidos": 0,
        "total_inseridos": 0,
        "total_ignorados": 0,
        "erros": [],
        "tarefa_id": tarefa.id,
    }


# ---------------------------------------------------------------------------
# rodar_monitoramento — mantido para compatibilidade com rodar_monitor.py
# ---------------------------------------------------------------------------

async def rodar_monitoramento(
    data_inicio: Optional[date] = None,
    data_fim: Optional[date] = None,
) -> None:
    """
    Chamado pelo script CLI (rodar_monitor.py).
    Cria MonitorTarefa pendente para cada OAB ativa.
    """
    hoje = now_br().date()
    if data_inicio is None or data_fim is None:
        data_inicio, data_fim = _calcular_periodo(hoje)

    db: Session = SessionLocal()
    try:
        oabs_ativas: List[OabMonitorada] = (
            db.query(OabMonitorada)
            .filter(OabMonitorada.ativa == True)  # noqa: E712
            .order_by(OabMonitorada.office_id, OabMonitorada.id)
            .all()
        )

        if not oabs_ativas:
            logger.info("[MONITOR] Nenhuma OAB ativa cadastrada.")
            return

        logger.info(
            f"[MONITOR] {len(oabs_ativas)} OAB(s) ativa(s) — "
            f"{data_inicio:%d/%m/%Y} a {data_fim:%d/%m/%Y}"
        )

        for oab in oabs_ativas:
            try:
                await monitorar_oab(db, oab, data_inicio, data_fim)
                logger.info(
                    f"[MONITOR] Tarefa criada — "
                    f"OAB {oab.numero_oab}/{oab.uf_oab} (office {oab.office_id})"
                )
            except Exception as e:
                db.rollback()
                logger.exception(f"[MONITOR] Erro ao criar tarefa: {e}")

    finally:
        db.close()


# ---------------------------------------------------------------------------
# job_monitorar_djen — chamado pelo APScheduler às 7h15
# ✅ NOVO: calcula período automático com feriados nacionais e cria tarefas
# ---------------------------------------------------------------------------

def job_monitorar_djen() -> None:
    """
    Wrapper síncrono chamado pelo APScheduler.
    Calcula o período correto (cobrindo fins de semana e feriados nacionais)
    e cria MonitorTarefa pendente para cada OAB ativa.
    O browser executa a consulta DJEN no próximo login do advogado.
    """
    logger.info("[MONITOR] Job das 7h15 iniciado")

    hoje = now_br().date()
    data_inicio, data_fim = _calcular_periodo(hoje)

    logger.info(
        f"[MONITOR] Período calculado: "
        f"{data_inicio:%d/%m/%Y} a {data_fim:%d/%m/%Y}"
    )

    db: Session = SessionLocal()
    try:
        oabs_ativas: List[OabMonitorada] = (
            db.query(OabMonitorada)
            .filter(OabMonitorada.ativa == True)  # noqa: E712
            .order_by(OabMonitorada.office_id, OabMonitorada.id)
            .all()
        )

        if not oabs_ativas:
            logger.info("[MONITOR] Nenhuma OAB ativa cadastrada.")
            return

        criadas = 0
        for oab in oabs_ativas:
            # Evita criar tarefa duplicada para o mesmo dia
            ja_existe = (
                db.query(MonitorTarefa)
                .filter(
                    MonitorTarefa.office_id == oab.office_id,
                    MonitorTarefa.oab_id    == oab.id,
                    MonitorTarefa.data_fim  == data_fim,
                    MonitorTarefa.status    != "ERRO",
                )
                .first()
            )
            if ja_existe:
                continue

            tarefa = MonitorTarefa(
                office_id   = oab.office_id,
                oab_id      = oab.id,
                numero_oab  = oab.numero_oab,
                uf_oab      = oab.uf_oab,
                data_inicio = data_inicio,
                data_fim    = data_fim,
                status      = "PENDENTE",
                criado_em   = now_br(),
            )
            db.add(tarefa)
            criadas += 1

        db.commit()
        logger.info(
            f"[MONITOR] {criadas} tarefa(s) criada(s) para "
            f"{len(oabs_ativas)} OAB(s) ativa(s)."
        )

    except Exception as e:
        db.rollback()
        logger.exception(f"[MONITOR] Erro ao criar tarefas: {e}")
    finally:
        db.close()

    logger.info("[MONITOR] Job das 7h15 concluído")