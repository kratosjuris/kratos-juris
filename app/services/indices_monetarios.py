"""
indices_monetarios.py
=====================
Busca automática de índices de correção monetária e juros legais
via API pública do Banco Central do Brasil (BCB/SGS).

Cache primário: banco de dados PostgreSQL (tabela indices_monetarios)
Cache secundário: arquivo JSON em disco (fallback local)

Índices suportados:
  - "tjdft" : INPC até 31/08/2024, IPCA a partir de 01/09/2024
  - "inpc"  : INPC durante todo o período
  - "ipca"  : IPCA durante todo o período

Juros:
  - "legal" : Taxa Legal (Lei 14.905/2024) — série SGS 29543

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
# Cache em disco (fallback quando banco não disponível)
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
        logger.warning("Não foi possível salvar cache em disco: %s", e)


def _cache_is_fresh(cache: dict, chave: str) -> bool:
    meta = cache.get("_meta", {}).get(chave)
    if not meta:
        return False
    salvo_em = datetime.fromisoformat(meta)
    return (datetime.now() - salvo_em).days < _CACHE_TTL_DAYS


# ---------------------------------------------------------------------------
# Cache no banco PostgreSQL
# ---------------------------------------------------------------------------

def _get_db_session():
    """Retorna uma sessão do banco sem depender de injeção FastAPI."""
    try:
        from app.core.database import SessionLocal
        return SessionLocal()
    except Exception:
        return None


def _ler_indices_do_banco(serie: str) -> dict[str, Decimal]:
    """Lê todos os índices de uma série do banco PostgreSQL."""
    db = _get_db_session()
    if not db:
        return {}
    try:
        from app.models.indice_monetario import IndiceMonetario
        registros = db.query(IndiceMonetario).filter(
            IndiceMonetario.serie == serie
        ).all()
        return {r.periodo: Decimal(str(r.valor)) for r in registros}
    except Exception as e:
        logger.warning("Erro ao ler índices do banco: %s", e)
        return {}
    finally:
        db.close()


def _salvar_indices_no_banco(serie: str, dados: dict[str, Decimal]) -> bool:
    """
    Salva/atualiza índices no banco PostgreSQL usando upsert.
    Retorna True se salvou com sucesso.
    """
    db = _get_db_session()
    if not db:
        return False
    try:
        from app.models.indice_monetario import IndiceMonetario
        from sqlalchemy.dialects.postgresql import insert

        # Busca existentes para comparar
        existentes = {
            r.periodo: r
            for r in db.query(IndiceMonetario).filter(
                IndiceMonetario.serie == serie
            ).all()
        }

        novos = 0
        atualizados = 0

        for periodo, valor in dados.items():
            if periodo in existentes:
                reg = existentes[periodo]
                if abs(Decimal(str(reg.valor)) - valor) > Decimal("0.000001"):
                    reg.valor = valor
                    reg.atualizado_em = datetime.now()
                    atualizados += 1
            else:
                db.add(IndiceMonetario(
                    serie=serie,
                    periodo=periodo,
                    valor=valor,
                    atualizado_em=datetime.now(),
                ))
                novos += 1

        db.commit()
        logger.info(
            "Índices %s salvos no banco: %d novos, %d atualizados.",
            serie.upper(), novos, atualizados
        )
        return True

    except Exception as e:
        logger.error("Erro ao salvar índices no banco: %s", e)
        db.rollback()
        return False
    finally:
        db.close()


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
    """Consulta API SGS do BCB com até 3 tentativas."""
    codigo = _SGS_CODIGOS[serie]
    params = {
        "formato": "json",
        "dataInicial": data_inicio.strftime("%d/%m/%Y"),
        "dataFinal":   data_fim.strftime("%d/%m/%Y"),
    }
    url = _BCB_URL.format(codigo=codigo)

    ultimo_erro = None
    for tentativa in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
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

        except Exception as e:
            ultimo_erro = e
            if tentativa < 3:
                logger.warning(
                    "Tentativa %d/%d falhou para %s: %s. Aguardando %ds...",
                    tentativa, 3, serie.upper(), e, 2 * tentativa
                )
                await asyncio.sleep(2 * tentativa)

    raise ultimo_erro


# ---------------------------------------------------------------------------
# Obtenção de índices com cache em camadas
# ---------------------------------------------------------------------------

async def _obter_indices(
    serie: str, data_inicio: date, data_fim: date
) -> dict[str, Decimal]:
    """
    Estratégia de cache em 3 camadas:
      1. Cache em disco (mais rápido, válido por 1 dia)
      2. Banco PostgreSQL (persiste entre deploys)
      3. API do BCB (fonte primária, sujeita a instabilidade)
    """
    ultimo_mes = data_fim.strftime("%Y-%m")

    # ── Camada 1: cache em disco ──────────────────────────────────────────
    cache = _load_cache()
    serie_cache: dict[str, str] = cache.get(serie, {})

    if _cache_is_fresh(cache, serie) and ultimo_mes in serie_cache:
        return {k: Decimal(v) for k, v in serie_cache.items()}

    # ── Camada 2: banco PostgreSQL ────────────────────────────────────────
    dados_banco = _ler_indices_do_banco(serie)
    if dados_banco and ultimo_mes in dados_banco:
        logger.info("Índices %s carregados do banco PostgreSQL.", serie.upper())
        # Atualiza cache em disco com dados do banco
        cache[serie] = {k: str(v) for k, v in dados_banco.items()}
        cache.setdefault("_meta", {})[serie] = datetime.now().isoformat()
        _save_cache(cache)
        return dados_banco

    # ── Camada 3: API do BCB ──────────────────────────────────────────────
    logger.info("Buscando %s na API BCB…", serie.upper())
    try:
        inicio = date(2024, 8, 1) if serie == "taxa_legal" else date(1990, 1, 1)
        novos = await _buscar_bcb(serie, inicio, date.today())

        # Salva no banco (persistente entre deploys)
        _salvar_indices_no_banco(serie, novos)

        # Salva no cache em disco (rápido para próximas requisições)
        cache[serie] = {k: str(v) for k, v in novos.items()}
        cache.setdefault("_meta", {})[serie] = datetime.now().isoformat()
        _save_cache(cache)

        return novos

    except Exception as e:
        logger.error("Falha ao buscar %s na API BCB: %s", serie.upper(), e)

        # Fallback 1: cache em disco desatualizado
        if serie_cache:
            logger.warning("Usando cache em disco desatualizado de %s.", serie.upper())
            return {k: Decimal(v) for k, v in serie_cache.items()}

        # Fallback 2: banco PostgreSQL (mesmo sem o mês mais recente)
        if dados_banco:
            logger.warning("Usando dados do banco PostgreSQL de %s (pode estar desatualizado).", serie.upper())
            return dados_banco

        # Fallback 3: retorna vazio — cálculo usará fator 1.0
        logger.warning(
            "Sem dados disponíveis para %s. Fator de correção será 1.0.",
            serie.upper()
        )
        return {}


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
            return (
                _acumular_fator(indices_inpc, data_inicial, corte)
                * _acumular_fator(indices_ipca, corte, data_final)
            ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    elif indice in ("ipca", "inpc"):
        indices = await _obter_indices(indice, data_inicial, data_final)
        return _acumular_fator(indices, data_inicial, data_final)

    return Decimal("1.000000")


# ---------------------------------------------------------------------------
# Cálculo de juros legais (Taxa Legal)
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
# Detalhamento mês a mês
# ---------------------------------------------------------------------------

async def _obter_detalhamento_async(
    indice: str,
    data_inicio: date,
    data_final: date,
    juros_tipo: str,
    data_inicio_juros: Optional[date],
) -> List[dict]:
    corte_tjdft = date(2024, 9, 1)
    indice = indice.lower()

    if indice == "tjdft":
        serie_antes  = await _obter_indices("inpc", data_inicio, data_final)
        serie_depois = await _obter_indices("ipca", data_inicio, data_final)
    elif indice == "inpc":
        serie_antes  = await _obter_indices("inpc", data_inicio, data_final)
        serie_depois = serie_antes
    else:
        serie_antes  = await _obter_indices("ipca", data_inicio, data_final)
        serie_depois = serie_antes

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

    MESES_PT = ["","Jan","Fev","Mar","Abr","Mai","Jun",
                "Jul","Ago","Set","Out","Nov","Dez"]

    while (ano, mes) < (ano_fim, mes_fim):
        chave     = f"{ano:04d}-{mes:02d}"
        mes_label = f"{MESES_PT[mes]}/{ano}"
        data_ref  = date(ano, mes, 1)

        if indice == "tjdft":
            if data_ref < corte_tjdft:
                taxa_correcao = serie_antes.get(chave) or Decimal("0")
                indice_nome   = "INPC"
            else:
                taxa_correcao = serie_depois.get(chave) or Decimal("0")
                indice_nome   = "IPCA"
        elif indice == "inpc":
            taxa_correcao = serie_antes.get(chave) or Decimal("0")
            indice_nome   = "INPC"
        else:
            taxa_correcao = serie_depois.get(chave) or Decimal("0")
            indice_nome   = "IPCA"

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
            "mes":          mes_label,
            "indice_nome":  indice_nome,
            "correcao":     f"{taxa_correcao:.6f}%",
            "juros_nome":   juros_nome,
            "juros":        taxa_juros_str,
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
    return _run_async(
        _obter_detalhamento_async(
            indice, data_inicio, data_final, juros_tipo, data_inicio_juros
        )
    )


# ---------------------------------------------------------------------------
# Administração
# ---------------------------------------------------------------------------

async def atualizar_cache_indices() -> dict[str, str]:
    """Força download de todos os índices e salva no banco + disco."""
    status: dict[str, str] = {}
    for serie in ("ipca", "inpc", "taxa_legal"):
        try:
            inicio = date(2024, 8, 1) if serie == "taxa_legal" else date(1990, 1, 1)
            dados  = await _buscar_bcb(serie, inicio, date.today())

            # Salva no banco
            ok_banco = _salvar_indices_no_banco(serie, dados)

            # Salva no disco
            cache = _load_cache()
            cache[serie] = {k: str(v) for k, v in dados.items()}
            cache.setdefault("_meta", {})[serie] = datetime.now().isoformat()
            _save_cache(cache)

            ultimo = max(dados.keys()) if dados else "—"
            banco_str = "banco ✓" if ok_banco else "banco ✗"
            status[serie] = f"OK — {len(dados)} meses — último: {ultimo} — {banco_str}"

        except Exception as e:
            status[serie] = f"ERRO: {e}"
    return status


def status_cache() -> dict[str, str]:
    """Retorna estado do cache em disco e banco."""
    cache    = _load_cache()
    resultado: dict[str, str] = {}
    for serie in ("ipca", "inpc", "taxa_legal"):
        disco = cache.get(serie, {})
        meta  = cache.get("_meta", {}).get(serie)
        banco = _ler_indices_do_banco(serie)

        partes = []
        if disco and meta:
            ultimo = max(disco.keys())
            at     = datetime.fromisoformat(meta).strftime("%d/%m/%Y %H:%M")
            partes.append(f"disco: último {ultimo} ({at})")
        else:
            partes.append("disco: ausente")

        if banco:
            partes.append(f"banco: {len(banco)} meses")
        else:
            partes.append("banco: ausente")

        resultado[serie] = " | ".join(partes)
    return resultado