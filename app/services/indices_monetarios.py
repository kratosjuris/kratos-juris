"""
indices_monetarios.py
=====================
Busca automática de índices de correção monetária e juros legais
via API pública do Banco Central do Brasil (BCB/SGS).

Índices de correção suportados:
  - "tjdft" : INPC até 31/08/2024, IPCA a partir de 01/09/2024
  - "inpc"  : INPC durante todo o período
  - "ipca"  : IPCA durante todo o período

Juros suportados:
  - "legal" : Taxa Legal (Lei 14.905/2024) — SELIC − IPCA, juros simples
              Série SGS 29543 do Banco Central

Dependências:
  pip install httpx
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache em disco
# ---------------------------------------------------------------------------
_CACHE_FILE = Path(__file__).parent / "_indices_cache.json"
_CACHE_TTL_DAYS = 1


def _load_cache() -> dict:
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_cache(data: dict) -> None:
    try:
        _CACHE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("Não foi possível salvar cache de índices: %s", e)


def _cache_is_fresh(cache: dict, chave: str) -> bool:
    meta = cache.get("_meta", {}).get(chave)
    if not meta:
        return False
    salvo_em = datetime.fromisoformat(meta)
    return (datetime.now() - salvo_em).days < _CACHE_TTL_DAYS


# ---------------------------------------------------------------------------
# Séries SGS do Banco Central
# ---------------------------------------------------------------------------
_SGS_CODIGOS = {
    "ipca":       433,
    "inpc":       188,
    "taxa_legal": 29543,
}

_BCB_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"


async def _buscar_bcb(
    serie: str, data_inicio: date, data_fim: date
) -> dict[str, Decimal]:
    codigo = _SGS_CODIGOS[serie]
    params = {
        "formato": "json",
        "dataInicial": data_inicio.strftime("%d/%m/%Y"),
        "dataFinal": data_fim.strftime("%d/%m/%Y"),
    }
    url = _BCB_URL.format(codigo=codigo)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        dados = resp.json()

    resultado: dict[str, Decimal] = {}
    for item in dados:
        try:
            dt = datetime.strptime(item["data"], "%d/%m/%Y")
            chave = dt.strftime("%Y-%m")
            resultado[chave] = Decimal(str(item["valor"]))
        except Exception:
            continue

    return resultado


async def _obter_indices(
    serie: str, data_inicio: date, data_fim: date
) -> dict[str, Decimal]:
    cache = _load_cache()
    ultimo_mes_necessario = data_fim.strftime("%Y-%m")
    serie_cache: dict[str, str] = cache.get(serie, {})

    if _cache_is_fresh(cache, serie) and ultimo_mes_necessario in serie_cache:
        return {k: Decimal(v) for k, v in serie_cache.items()}

    logger.info("Buscando %s na API BCB…", serie.upper())
    try:
        inicio = date(2024, 8, 1) if serie == "taxa_legal" else date(1990, 1, 1)
        novos = await _buscar_bcb(serie, inicio, date.today())
    except Exception as e:
        logger.error("Falha ao buscar %s: %s", serie.upper(), e)
        if serie_cache:
            logger.warning("Usando cache desatualizado de %s.", serie.upper())
            return {k: Decimal(v) for k, v in serie_cache.items()}
        raise RuntimeError(
            f"Não foi possível obter {serie.upper()} da API BCB. Verifique sua conexão."
        ) from e

    cache[serie] = {k: str(v) for k, v in novos.items()}
    cache.setdefault("_meta", {})[serie] = datetime.now().isoformat()
    _save_cache(cache)
    return novos


# ---------------------------------------------------------------------------
# Cálculo do fator de correção
# ---------------------------------------------------------------------------

def _acumular_fator(
    indices_mensais: dict[str, Decimal], data_inicial: date, data_final: date
) -> Decimal:
    fator = Decimal("1")
    ano, mes = data_inicial.year, data_inicial.month
    ano_fim, mes_fim = data_final.year, data_final.month

    while (ano, mes) < (ano_fim, mes_fim):
        chave = f"{ano:04d}-{mes:02d}"
        taxa = indices_mensais.get(chave) or Decimal("0")
        fator *= Decimal("1") + taxa / Decimal("100")
        mes += 1
        if mes > 12:
            mes = 1
            ano += 1

    return fator.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


async def _calcular_fator_async(
    data_inicial: date, data_final: date, indice: str
) -> Decimal:
    if not data_inicial or not data_final or data_final <= data_inicial:
        return Decimal("1.000000")

    indice = indice.lower()

    if indice == "tjdft":
        corte = date(2024, 9, 1)
        if data_final <= corte:
            indices = await _obter_indices("inpc", data_inicial, data_final)
            return _acumular_fator(indices, data_inicial, data_final)
        elif data_inicial >= corte:
            indices = await _obter_indices("ipca", data_inicial, data_final)
            return _acumular_fator(indices, data_inicial, data_final)
        else:
            indices_inpc, indices_ipca = await asyncio.gather(
                _obter_indices("inpc", data_inicial, corte),
                _obter_indices("ipca", corte, data_final),
            )
            return (_acumular_fator(indices_inpc, data_inicial, corte)
                    * _acumular_fator(indices_ipca, corte, data_final)
                    ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    elif indice in ("ipca", "inpc"):
        indices = await _obter_indices(indice, data_inicial, data_final)
        return _acumular_fator(indices, data_inicial, data_final)

    return Decimal("1.000000")


# ---------------------------------------------------------------------------
# Cálculo de juros legais
# ---------------------------------------------------------------------------

async def _calcular_juros_legais_async(
    valor_corrigido: Decimal, data_inicio: date, data_final: date
) -> Tuple[Decimal, Decimal]:
    if not data_inicio or not data_final or data_final <= data_inicio:
        return Decimal("0.00"), Decimal("0.00")

    indices = await _obter_indices("taxa_legal", data_inicio, data_final)
    percentual_total = Decimal("0")
    ano, mes = data_inicio.year, data_inicio.month
    ano_fim, mes_fim = data_final.year, data_final.month

    while (ano, mes) < (ano_fim, mes_fim):
        chave = f"{ano:04d}-{mes:02d}"
        taxa = indices.get(chave) or Decimal("0")
        if taxa < Decimal("0"):
            taxa = Decimal("0")
        percentual_total += taxa
        mes += 1
        if mes > 12:
            mes = 1
            ano += 1

    valor_juros = valor_corrigido * (percentual_total / Decimal("100"))
    return valor_juros, percentual_total


# ---------------------------------------------------------------------------
# Detalhamento mês a mês dos índices aplicados
# ---------------------------------------------------------------------------

async def _obter_detalhamento_async(
    indice: str,
    data_inicio: date,
    data_final: date,
    juros_tipo: str,
    data_inicio_juros: Optional[date],
) -> List[dict]:
    """
    Retorna lista de dicts com o índice de cada mês no período, ex.:
    [
      { "mes": "Abr/2024", "indice_nome": "INPC", "correcao": "0,42%", "juros": "0,61%", "juros_nome": "Taxa Legal" },
      ...
    ]
    """
    corte_tjdft = date(2024, 9, 1)
    indice = indice.lower()

    # Quais séries de correção buscar
    if indice == "tjdft":
        serie_antes = await _obter_indices("inpc", data_inicio, data_final)
        serie_depois = await _obter_indices("ipca", data_inicio, data_final)
    elif indice == "inpc":
        serie_antes = await _obter_indices("inpc", data_inicio, data_final)
        serie_depois = serie_antes
    else:
        serie_antes = await _obter_indices("ipca", data_inicio, data_final)
        serie_depois = serie_antes

    # Série de juros
    serie_juros: dict[str, Decimal] = {}
    juros_nome = ""
    if juros_tipo == "legal":
        serie_juros = await _obter_indices("taxa_legal", data_inicio, data_final)
        juros_nome = "Taxa Legal"
    elif juros_tipo == "um_porcento":
        juros_nome = "1% a.m."
    elif juros_tipo == "percentual":
        juros_nome = "Percentual fixo"

    resultado = []
    ano, mes = data_inicio.year, data_inicio.month
    ano_fim, mes_fim = data_final.year, data_final.month

    MESES_PT = [
        "", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
        "Jul", "Ago", "Set", "Out", "Nov", "Dez"
    ]

    while (ano, mes) < (ano_fim, mes_fim):
        chave = f"{ano:04d}-{mes:02d}"
        mes_label = f"{MESES_PT[mes]}/{ano}"

        # Correção monetária
        data_ref = date(ano, mes, 1)
        if indice == "tjdft":
            if data_ref < corte_tjdft:
                taxa_correcao = serie_antes.get(chave) or Decimal("0")
                indice_nome = "INPC"
            else:
                taxa_correcao = serie_depois.get(chave) or Decimal("0")
                indice_nome = "IPCA"
        elif indice == "inpc":
            taxa_correcao = serie_antes.get(chave) or Decimal("0")
            indice_nome = "INPC"
        else:
            taxa_correcao = serie_depois.get(chave) or Decimal("0")
            indice_nome = "IPCA"

        # Juros
        taxa_juros_str = "—"
        if juros_tipo == "legal" and data_inicio_juros:
            if data_ref >= date(data_inicio_juros.year, data_inicio_juros.month, 1):
                t = serie_juros.get(chave) or Decimal("0")
                if t < Decimal("0"):
                    t = Decimal("0")
                taxa_juros_str = f"{t:.6f}%"
        elif juros_tipo == "um_porcento" and data_inicio_juros:
            if data_ref >= date(data_inicio_juros.year, data_inicio_juros.month, 1):
                taxa_juros_str = "1,000000%"
        elif juros_tipo == "percentual" and data_inicio_juros:
            if data_ref >= date(data_inicio_juros.year, data_inicio_juros.month, 1):
                taxa_juros_str = "conforme contrato"

        resultado.append({
            "mes": mes_label,
            "indice_nome": indice_nome,
            "correcao": f"{taxa_correcao:.6f}%",
            "juros_nome": juros_nome,
            "juros": taxa_juros_str,
        })

        mes += 1
        if mes > 12:
            mes = 1
            ano += 1

    return resultado


# ---------------------------------------------------------------------------
# Executor async seguro
# ---------------------------------------------------------------------------

def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return loop.run_until_complete(coro)
    except Exception as e:
        logger.error("Erro ao executar coroutine: %s", e)
        raise


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def get_indice_nome(indice: str) -> str:
    if indice == "tjdft":
        return "Índices oficiais TJDFT: INPC até 31/08/2024 e IPCA a partir de 01/09/2024"
    if indice == "inpc":
        return "INPC durante todo o período"
    if indice == "ipca":
        return "IPCA durante todo o período"
    return "Índice não informado"


def calcular_fator_correcao(
    data_inicial: date, data_final: date, indice: str
) -> Decimal:
    return _run_async(_calcular_fator_async(data_inicial, data_final, indice))


def calcular_juros_legais(
    valor_corrigido: Decimal, data_inicio: date, data_final: date
) -> Tuple[Decimal, Decimal]:
    return _run_async(
        _calcular_juros_legais_async(valor_corrigido, data_inicio, data_final)
    )


def obter_detalhamento_indices(
    indice: str,
    data_inicio: date,
    data_final: date,
    juros_tipo: str = "sem",
    data_inicio_juros: Optional[date] = None,
) -> List[dict]:
    """
    Retorna lista mês a mês com índice de correção e juros aplicados.
    Usado pelo relatório para exibir a memória de índices.
    """
    return _run_async(
        _obter_detalhamento_async(
            indice, data_inicio, data_final, juros_tipo, data_inicio_juros
        )
    )


# ---------------------------------------------------------------------------
# Utilitários de administração
# ---------------------------------------------------------------------------

async def atualizar_cache_indices() -> dict[str, str]:
    status: dict[str, str] = {}
    for serie in ("ipca", "inpc", "taxa_legal"):
        try:
            inicio = date(2024, 8, 1) if serie == "taxa_legal" else date(1990, 1, 1)
            dados = await _buscar_bcb(serie, inicio, date.today())
            cache = _load_cache()
            cache[serie] = {k: str(v) for k, v in dados.items()}
            cache.setdefault("_meta", {})[serie] = datetime.now().isoformat()
            _save_cache(cache)
            ultimo = max(dados.keys()) if dados else "—"
            status[serie] = f"OK — {len(dados)} meses — último: {ultimo}"
        except Exception as e:
            status[serie] = f"ERRO: {e}"
    return status


def status_cache() -> dict[str, str]:
    cache = _load_cache()
    resultado: dict[str, str] = {}
    for serie in ("ipca", "inpc", "taxa_legal"):
        dados = cache.get(serie, {})
        meta = cache.get("_meta", {}).get(serie)
        if dados and meta:
            ultimo = max(dados.keys())
            atualizado = datetime.fromisoformat(meta).strftime("%d/%m/%Y %H:%M")
            resultado[serie] = f"Cache OK — último mês: {ultimo} — atualizado em: {atualizado}"
        else:
            resultado[serie] = "Cache ausente — será buscado na próxima chamada"
    return resultado