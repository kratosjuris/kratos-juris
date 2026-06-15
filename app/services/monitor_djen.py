"""
app/services/monitor_djen.py

Serviço de monitoramento automático DJEN + DataJud.

Fluxo por OAB ativa:
  1. Consulta DJEN (comunicaapi.pje.jus.br) pelo período informado
  2. Injeta os resultados como MigrationRow (mesmo padrão do upload)
  3. Para cada item novo, chama o DataJud e preenche automaticamente:
     - cliente (parte ativa/passiva)
     - vara_tramitacao (órgão julgador)
     - observacao (classe, ajuizamento, últimas movimentações)
  4. Atualiza OabMonitorada com status e resumo do resultado

Chamado por:
  - app/scripts/rodar_monitor.py  (cron diário)
  - app/main.py via APScheduler   (job agendado no startup)
"""

import re
import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from app.core.database import SessionLocal
from app.core.datetime_utils import now_br
from app.models.oab_monitorada import OabMonitorada
from app.models.migration import MigrationBatch, MigrationRow, BatchStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes de API
# ---------------------------------------------------------------------------
DJEN_API_BASE   = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
DJEN_TIMEOUT    = 30.0
DJEN_ITENS_POR_PAGINA = 100
DJEN_MAX_PAGINAS = 20

DATAJUD_API_BASE = "https://api-publica.datajud.cnj.jus.br"
DATAJUD_API_KEY  = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
DATAJUD_TIMEOUT  = 20.0

INSERT_CHUNK = 300

# Mapeamento J+TR -> alias do tribunal (DataJud)
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

# Headers de browser para contornar bloqueio 403 da API DJEN em servidores cloud
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
    j  = digits[13]
    tr = digits[14:16]
    return DATAJUD_TR_MAP.get((j, tr))


def _extrair_parte(fonte: dict, polo: str) -> Optional[str]:
    """
    Extrai nome da parte pelo polo.
    DataJud retorna polo como objeto {"id":"0","nome":"ATIVO"} OU como string "ATIVO".
    Trata os dois formatos.
    """
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
# Chamadas de API (assíncronas)
# ---------------------------------------------------------------------------

async def _fetch_djen(
    numero_oab: str,
    uf_oab: str,
    data_inicio: date,
    data_fim: date,
    client: httpx.AsyncClient,
) -> List[dict]:
    """Consulta DJEN com paginação automática."""
    todos: List[dict] = []
    num = re.sub(r"\D+", "", numero_oab)

    for pagina in range(1, DJEN_MAX_PAGINAS + 1):
        params = {
            "numeroOab": num,
            "ufOab": uf_oab.upper(),
            "dataDisponibilizacaoInicio": data_inicio.isoformat(),
            "dataDisponibilizacaoFim":   data_fim.isoformat(),
            "itensPorPagina": DJEN_ITENS_POR_PAGINA,
            "pagina": pagina,
        }
        try:
            resp = await client.get(DJEN_API_BASE, params=params, timeout=DJEN_TIMEOUT, headers=DJEN_HEADERS)
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
    """Consulta capa processual no DataJud."""
    digits = re.sub(r"\D+", "", numero)
    if not digits:
        return None

    url = f"{DATAJUD_API_BASE}/api_publica_{tribunal}/_search"
    body = {"size": 1, "query": {"match": {"numeroProcesso": digits}}}
    headers = {
        "Authorization": f"APIKey {DATAJUD_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = await client.post(url, json=body, headers=headers, timeout=DATAJUD_TIMEOUT)
    except httpx.RequestError:
        return None

    if resp.status_code != 200:
        return None

    try:
        data = resp.json()
    except Exception:
        return None

    hits = (data.get("hits") or {}).get("hits") or []
    return hits[0].get("_source") if hits else None


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
# Núcleo: processa uma OAB em um período
# ---------------------------------------------------------------------------

async def monitorar_oab(
    db: Session,
    oab: OabMonitorada,
    data_inicio: date,
    data_fim: date,
) -> dict:
    """
    Executa o ciclo completo para uma OAB:
      DJEN → MigrationRow → DataJud (enriquecimento automático)

    Retorna dict com:
      total_extraidos, total_inseridos, total_ignorados, erros: List[str]
    """
    office_id = oab.office_id
    numero_oab = oab.numero_oab
    uf_oab = oab.uf_oab

    erros: List[str] = []
    total_extraidos = total_inseridos = total_ignorados = 0

    # ---- cria batch ----
    batch = MigrationBatch(office_id=office_id, criado_em=now_br())
    _safe_set(batch, "status", BatchStatus.PROCESSANDO)
    _safe_set(batch, "arquivo_nome",
              f"Monitor DJEN — OAB {numero_oab}/{uf_oab} "
              f"({data_inicio:%d/%m/%Y} a {data_fim:%d/%m/%Y})")
    _safe_set(batch, "total_extraidos", 0)
    _safe_set(batch, "total_inseridos", 0)
    _safe_set(batch, "total_ignorados", 0)
    db.add(batch)
    db.commit()
    db.refresh(batch)
    batch_id = batch.id

    # ---- duplicidade do dia ----
    hoje = now_br().date()
    nums_hoje = set(
        x[0] for x in (
            db.query(MigrationRow.numero_processo)
            .join(MigrationBatch, MigrationBatch.id == MigrationRow.batch_id)
            .filter(
                MigrationBatch.office_id == office_id,
                func.date(MigrationBatch.criado_em) == hoje,
            )
            .all()
        ) if x and x[0]
    )

    async with httpx.AsyncClient() as client:

        # ---- 1. consulta DJEN ----
        try:
            itens_djen = await _fetch_djen(numero_oab, uf_oab, data_inicio, data_fim, client)
        except RuntimeError as e:
            erros.append(str(e))
            _safe_set(batch, "status", BatchStatus.ERRO)
            _safe_set(batch, "erro_processamento", str(e)[:10000])
            _safe_set(batch, "processado_em", now_br())
            db.add(batch)
            db.commit()
            return {
                "total_extraidos": 0,
                "total_inseridos": 0,
                "total_ignorados": 0,
                "erros": erros,
            }

        # ---- 2. converte e persiste ----
        seen: set = set()
        buffer: List[MigrationRow] = []
        rows_para_enriquecer: List[MigrationRow] = []

        for raw in itens_djen:
            numero = (
                str(raw.get("numero_processo") or raw.get("numeroProcesso") or "")
            ).strip()

            if not numero or numero in seen or numero in nums_hoje:
                total_ignorados += 1
                continue

            seen.add(numero)
            total_extraidos += 1

            d_disp = _parse_date(raw.get("data_disponibilizacao") or raw.get("dataDisponibilizacao"))
            # ✅ data_publicacao = primeiro dia útil após disponibilização
            d_pub = (d_disp + timedelta(days=1)) if d_disp else None
            if d_pub:
                while d_pub.weekday() >= 5:
                    d_pub += timedelta(days=1)

            orgao = (raw.get("nomeOrgao") or raw.get("orgao") or "").strip()
            tipo  = (raw.get("tipoComunicacao") or raw.get("tipo_comunicacao") or "").strip()
            trib  = (raw.get("siglaTribunal") or raw.get("tribunal") or "").strip()

            diario_parts = [p for p in [trib, tipo] if p]
            diario = " — ".join(diario_parts) or None

            texto = _clean_text(str(raw.get("texto") or raw.get("conteudo") or ""))
            link  = raw.get("link")

            # ✅ extrai prazo do texto DJEN (onde o prazo realmente está)
            prazo_djen = None
            if texto:
                import re as _re
                DIAS_RX = _re.compile(
                    r"prazo\s+(?:de\s+)?(\d+)|(\d+)\s*(?:\([^)]+\)\s*)?dias?|(\d+)\s+dias?\s+(?:úteis|corridos|para)",
                    _re.IGNORECASE,
                )
                for m in DIAS_RX.finditer(texto):
                    dias_str = m.group(1) or m.group(2) or m.group(3)
                    try:
                        dias = int(dias_str)
                        if 1 <= dias <= 365:
                            prazo_djen = dias
                            break
                    except (ValueError, TypeError):
                        pass

            # formata observação legível
            obs_parts = []
            if texto:
                texto_fmt = _re.sub(r"([.;])\s+", r"\1\n", texto)
                obs_parts.append(texto_fmt.strip())
            if link:
                obs_parts.append(f"\n🔗 Documento completo: {link}")

            row = MigrationRow(
                office_id=office_id,
                batch_id=batch_id,
                data_disponibilizacao=d_disp,
                data_publicacao=d_pub,
                numero_processo=numero,
                diario=diario,
            )
            _safe_set(row, "vara_tramitacao", orgao or None)
            _safe_set(row, "tipo_contagem", "uteis")
            _safe_set(row, "observacao", "\n".join(obs_parts)[:8000] or None)
            if prazo_djen:
                _safe_set(row, "rompe_em_dias", prazo_djen)

            buffer.append(row)

            if len(buffer) >= INSERT_CHUNK:
                ins, blk = _insert_chunk(db, buffer)
                total_inseridos += ins
                total_ignorados += blk
                rows_para_enriquecer.extend(buffer[:ins])
                buffer.clear()

        if buffer:
            ins, blk = _insert_chunk(db, buffer)
            total_inseridos += ins
            total_ignorados += blk
            rows_para_enriquecer.extend(buffer[:ins])
            buffer.clear()

        # ---- 3. enriquecimento DataJud automático ----
        for row in rows_para_enriquecer:
            # re-busca o objeto do banco (pode ter sido expungido)
            row_db = db.query(MigrationRow).filter(MigrationRow.id == row.id).first()
            if not row_db:
                continue

            tribunal = _identificar_tribunal(row_db.numero_processo)
            if not tribunal:
                continue

            try:
                fonte = await _fetch_datajud(row_db.numero_processo, tribunal, client)
            except Exception:
                continue

            if not fonte:
                continue

            atualizado = False

            # preenche cliente se vazio
            if not (row_db.cliente or "").strip():
                nome = _extrair_parte(fonte, "ATIVO") or _extrair_parte(fonte, "PASSIVO")
                if nome:
                    row_db.cliente = nome
                    atualizado = True

            # preenche vara se vazio
            if not (row_db.vara_tramitacao or "").strip():
                orgao_dj = ((fonte.get("orgaoJulgador") or {}).get("nome") or "").strip()
                if orgao_dj:
                    row_db.vara_tramitacao = orgao_dj
                    atualizado = True

            # anexa bloco DataJud na observação
            classe   = ((fonte.get("classe") or {}).get("nome") or "").strip()
            grau     = (fonte.get("grau") or "").strip()
            d_ajuiz  = _parse_date(str(fonte.get("dataAjuizamento") or "")[:10])
            resumo   = _resumo_movimentos(fonte, limite=5)

            bloco_partes = []
            if classe:
                bloco_partes.append(f"Classe: {classe}" + (f" ({grau})" if grau else ""))
            if d_ajuiz:
                bloco_partes.append(f"Ajuizamento: {d_ajuiz:%d/%m/%Y}")
            if resumo:
                bloco_partes.append(f"Últimas movimentações:\n{resumo}")

            if bloco_partes:
                bloco = f"[DataJud — {tribunal.upper()}]\n" + "\n".join(bloco_partes)
                existente = (row_db.observacao or "").strip()
                row_db.observacao = (
                    existente + ("\n\n" if existente else "") + bloco
                )[:8000]
                atualizado = True

            if atualizado:
                db.add(row_db)

        db.commit()

    # ---- finaliza batch ----
    batch = db.query(MigrationBatch).filter(MigrationBatch.id == batch_id).first()
    if batch:
        _safe_set(batch, "status", BatchStatus.CONCLUIDO)
        _safe_set(batch, "total_extraidos", total_extraidos)
        _safe_set(batch, "total_inseridos", total_inseridos)
        _safe_set(batch, "total_ignorados", total_ignorados)
        _safe_set(batch, "processado_em", now_br())
        db.add(batch)
        db.commit()

    return {
        "total_extraidos": total_extraidos,
        "total_inseridos": total_inseridos,
        "total_ignorados": total_ignorados,
        "erros": erros,
    }


# ---------------------------------------------------------------------------
# Ponto de entrada: roda para TODOS os escritórios com OABs ativas
# ---------------------------------------------------------------------------

async def rodar_monitoramento(
    data_inicio: Optional[date] = None,
    data_fim: Optional[date] = None,
) -> None:
    """
    Chamado pelo APScheduler (main.py) ou pelo script CLI.
    Varre todos os escritórios que têm OABs ativas e executa
    `monitorar_oab` para cada uma.

    Se data_inicio/data_fim não forem passadas, usa ontem como período
    (padrão para o job diário automático).
    """
    hoje = now_br().date()
    if data_inicio is None:
        data_inicio = hoje - timedelta(days=1)
    if data_fim is None:
        data_fim = hoje - timedelta(days=1)

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

        logger.info(f"[MONITOR] {len(oabs_ativas)} OAB(s) ativa(s) — "
                    f"período {data_inicio:%d/%m/%Y} a {data_fim:%d/%m/%Y}")

        for oab in oabs_ativas:
            label = f"OAB {oab.numero_oab}/{oab.uf_oab} (office {oab.office_id})"
            logger.info(f"[MONITOR] Iniciando {label}")

            try:
                resultado = await monitorar_oab(db, oab, data_inicio, data_fim)

                resumo = (
                    f"{resultado['total_inseridos']} intimação(ões) nova(s) | "
                    f"extraídas: {resultado['total_extraidos']} | "
                    f"ignoradas: {resultado['total_ignorados']}"
                )

                status = "VAZIO" if resultado["total_inseridos"] == 0 else "OK"
                if resultado["erros"]:
                    status = "ERRO"
                    resumo += " | Erros: " + "; ".join(resultado["erros"])

                oab.ultimo_monitoramento_em     = now_br()
                oab.ultimo_monitoramento_status  = status
                oab.ultimo_monitoramento_resumo  = resumo[:1000]
                oab.atualizado_em               = now_br()
                db.add(oab)
                db.commit()

                logger.info(f"[MONITOR] {label} → {status} — {resumo}")

            except Exception as e:
                db.rollback()
                logger.exception(f"[MONITOR] Erro inesperado em {label}: {e}")

                try:
                    oab.ultimo_monitoramento_em     = now_br()
                    oab.ultimo_monitoramento_status  = "ERRO"
                    oab.ultimo_monitoramento_resumo  = str(e)[:1000]
                    oab.atualizado_em               = now_br()
                    db.add(oab)
                    db.commit()
                except Exception:
                    db.rollback()

    finally:
        db.close()


# ---------------------------------------------------------------------------
# Wrapper síncrono para o APScheduler (BackgroundScheduler é síncrono)
# ---------------------------------------------------------------------------

def job_monitorar_djen() -> None:
    """
    Wrapper síncrono chamado pelo APScheduler.
    Cria um event loop temporário para rodar o código assíncrono.
    """
    logger.info("[MONITOR] Job diário DJEN iniciado")
    try:
        asyncio.run(rodar_monitoramento())
    except Exception as e:
        logger.exception(f"[MONITOR] Falha no job diário: {e}")
    logger.info("[MONITOR] Job diário DJEN concluído")