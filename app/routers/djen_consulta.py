"""
============================================================================
 CONSULTA DJEN POR OAB — Integração com o fluxo de Migrações existente
============================================================================
Melhorias v2:
  - data_publicacao calculada como primeiro dia útil após disponibilização
  - enriquecimento DataJud automático em LOTE após inserção no DJEN
  - extração de prazo (rompe_em_dias) dos movimentos DataJud
  - observação estruturada para leitura fácil no modal
============================================================================
"""

import re
import asyncio
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

import httpx
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from urllib.parse import quote

from app.core.database import get_db
from app.core.datetime_utils import now_br
from app.models.migration import MigrationBatch, MigrationRow, BatchStatus


router = APIRouter()

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
DJEN_API_BASE        = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
DJEN_TIMEOUT         = 30.0
DJEN_ITENS_POR_PAGINA = 100
DJEN_MAX_PAGINAS     = 20

DATAJUD_API_BASE = "https://api-publica.datajud.cnj.jus.br"
DATAJUD_API_KEY  = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
DATAJUD_TIMEOUT  = 20.0

INSERT_CHUNK_SIZE = 300

# Mapeamento J+TR → alias tribunal DataJud
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

# ---------------------------------------------------------------------------
# Helpers gerais
# ---------------------------------------------------------------------------

def _redirect_msg(msg: str) -> RedirectResponse:
    return RedirectResponse(url=f"/migracoes?msg={quote(str(msg))}", status_code=303)


def _get_office_id(request: Request) -> int:
    office_id = request.session.get("office_id")
    if not office_id:
        raise HTTPException(status_code=403, detail="Usuário sem escritório vinculado.")
    return int(office_id)


def _safe_set(obj, field: str, value):
    if hasattr(obj, field):
        setattr(obj, field, value)


def _norm_oab(numero: str, uf: str) -> Tuple[str, str]:
    num = re.sub(r"\D+", "", numero or "")
    uf_norm = re.sub(r"[^A-Za-z]", "", uf or "").upper()[:2]
    return num, uf_norm


def _parse_date_input(s) -> Optional[date]:
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


# ---------------------------------------------------------------------------
# ✅ NOVO: calcula data de publicação = primeiro dia útil após disponibilização
# ---------------------------------------------------------------------------

def _primeiro_dia_util_apos(d: date) -> date:
    """Retorna o primeiro dia útil (seg-sex) após a data informada."""
    proximo = d + timedelta(days=1)
    while proximo.weekday() >= 5:   # 5=sab, 6=dom
        proximo += timedelta(days=1)
    return proximo


# ---------------------------------------------------------------------------
# DataJud — identificação e consulta
# ---------------------------------------------------------------------------

def identificar_tribunal_por_numero(numero: str) -> Optional[str]:
    digits = re.sub(r"\D+", "", numero or "")
    if len(digits) != 20:
        return None
    return DATAJUD_TR_MAP.get((digits[13], digits[14:16]))


async def _consultar_datajud(numero: str, tribunal: str, client: httpx.AsyncClient) -> Optional[dict]:
    digits = re.sub(r"\D+", "", numero)
    if not digits:
        return None
    url  = f"{DATAJUD_API_BASE}/api_publica_{tribunal}/_search"
    body = {"size": 1, "query": {"match": {"numeroProcesso": digits}}}
    hdrs = {"Authorization": f"APIKey {DATAJUD_API_KEY}", "Content-Type": "application/json"}
    try:
        resp = await client.post(url, json=body, headers=hdrs, timeout=DATAJUD_TIMEOUT)
    except httpx.RequestError as e:
        print(f"[DATAJUD DEBUG] Erro de conexão para {numero}: {e}")
        return None
    if resp.status_code != 200:
        print(f"[DATAJUD DEBUG] HTTP {resp.status_code} para {numero}")
        return None
    try:
        data = resp.json()
        hits = (data.get("hits") or {}).get("hits") or []
        if not hits:
            print(f"[DATAJUD DEBUG] Nenhum hit para {numero} em {tribunal}")
            return None
        fonte = hits[0].get("_source") or {}

        # ✅ LOG DE DEBUG — imprime partes e orgaoJulgador no console
        import json as _json
        print(f"\n[DATAJUD DEBUG] ===== {numero} ({tribunal.upper()}) =====")
        print(f"[DATAJUD DEBUG] partes: {_json.dumps(fonte.get('partes'), ensure_ascii=False)}")
        print(f"[DATAJUD DEBUG] orgaoJulgador: {_json.dumps(fonte.get('orgaoJulgador'), ensure_ascii=False)}")
        print(f"[DATAJUD DEBUG] movimentos[0]: {_json.dumps((fonte.get('movimentos') or [{}])[:1], ensure_ascii=False)}")
        print(f"[DATAJUD DEBUG] =============================================\n")

        return fonte
    except Exception as e:
        print(f"[DATAJUD DEBUG] Erro ao parsear resposta para {numero}: {e}")
        return None


# ---------------------------------------------------------------------------
# ✅ NOVO: extração de prazo a partir dos movimentos do DataJud
# ---------------------------------------------------------------------------

def _extrair_prazo_do_texto_djen(texto: str) -> Optional[int]:
    """
    Extrai prazo em dias diretamente do texto da intimação DJEN.
    O prazo processual vem no conteúdo da publicação, não nos movimentos DataJud.
    Padrões reconhecidos:
      "prazo de 15 (quinze) dias úteis"
      "no prazo de 30 dias corridos"
      "15 dias para manifestação"
      "prazo de 5 dias"
    Só retorna quando encontra número explícito — nunca assume default.
    """
    if not texto:
        return None

    DIAS_RX = re.compile(
        r"prazo\s+(?:de\s+)?(\d+)"          # "prazo de 15"
        r"|(\d+)\s*(?:\([^)]+\)\s*)?dias?"  # "15 dias" / "15 (quinze) dias"
        r"|(\d+)\s+dias?\s+(?:úteis|corridos|para)",  # "15 dias úteis"
        re.IGNORECASE,
    )

    for m in DIAS_RX.finditer(texto):
        dias_str = m.group(1) or m.group(2) or m.group(3)
        try:
            dias = int(dias_str)
            if 1 <= dias <= 365:
                return dias
        except (ValueError, TypeError):
            pass
    return None


def _extrair_cliente_do_texto_djen(texto: str) -> Optional[str]:
    """
    Extrai nome do cliente do texto da intimação DJEN.
    Usado como fallback quando o DataJud retorna partes=null (comum no TJBA).

    Padrões comuns no DJEN:
      "Polo Ativo: JOÃO DA SILVA"
      "Requerente: MARIA SOUZA"
      "Autor: EMPRESA XYZ LTDA"
      "INTIMAÇÃO: JOÃO DA SILVA (Parte)"
      "Processo: 000... JOÃO DA SILVA x BANCO..."
    """
    if not texto:
        return None

    # padrões explícitos de polo/parte
    padroes = [
        r"(?:polo\s+ativo|requerente|autor(?:a)?|reclamante|impetrante|exequente)\s*[:\-]\s*([A-ZÁÀÃÂÉÊÍÓÔÕÚÜÇÑA-Z][^\n\r,;]{3,80})",
        r"intimad[ao]s?\s*[:\-]\s*([A-ZÁÀÃÂÉÊÍÓÔÕÚÜÇÑA-Z][^\n\r,;]{3,80})",
        r"parte\s+ativa\s*[:\-]\s*([A-ZÁÀÃÂÉÊÍÓÔÕÚÜÇÑA-Z][^\n\r,;]{3,80})",
    ]

    for pat in padroes:
        m = re.search(pat, texto, re.IGNORECASE)
        if m:
            nome = m.group(1).strip().rstrip(".,;:-")
            if len(nome) >= 5 and not nome.isdigit():
                return nome

    return None


def _extrair_nome_parte(fonte: dict, polo: str) -> Optional[str]:
    """
    Extrai nome da parte pelo polo.
    DataJud retorna polo como objeto {"id":"0","nome":"ATIVO"} OU como string "ATIVO".
    Trata os dois formatos.
    """
    polo_upper = polo.strip().upper()
    for parte in (fonte.get("partes") or []):
        campo_polo = parte.get("polo") or ""

        if isinstance(campo_polo, dict):
            nome_polo = (campo_polo.get("nome") or "").strip().upper()
        else:
            nome_polo = str(campo_polo).strip().upper()

        if nome_polo.startswith(polo_upper[:3]):
            nome = (parte.get("nome") or "").strip()
            if nome:
                return nome
    return None


def _montar_resumo_movimentos(fonte: dict, limite: int = 5) -> str:
    movs = sorted(
        fonte.get("movimentos") or [],
        key=lambda m: m.get("dataHora") or "",
        reverse=True,
    )
    linhas = []
    for m in movs[:limite]:
        nome   = (m.get("nome") or "").strip()
        data_h = (m.get("dataHora") or "")[:10]
        d      = _parse_date_input(data_h)
        data_br = d.strftime("%d/%m/%Y") if d else data_h
        if nome:
            linhas.append(f"• {data_br} — {nome}")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# ✅ NOVO: monta observação estruturada e legível
# ---------------------------------------------------------------------------

def _montar_observacao(texto_djen: Optional[str], link_djen: Optional[str]) -> str:
    """
    Formata o conteúdo DJEN de forma limpa e legível para o modal.
    Separa o texto em parágrafos, remove ruídos e adiciona o link.
    """
    partes = []

    if texto_djen:
        # limpa e formata em parágrafos
        texto = _clean_text(texto_djen)
        # quebra em sentenças/parágrafos para melhor leitura
        texto = re.sub(r"([.;])\s+", r"\1\n", texto)
        texto = re.sub(r"\n{3,}", "\n\n", texto)
        partes.append(texto.strip())

    if link_djen:
        partes.append(f"\n🔗 Documento completo: {link_djen}")

    return "\n".join(partes)[:8000]


# ---------------------------------------------------------------------------
# ✅ NOVO: enriquecimento DataJud em lote (chamado após inserção DJEN)
# ---------------------------------------------------------------------------

async def _enriquecer_lote_datajud(db: Session, row_ids: List[int], office_id: int) -> None:
    """
    Para cada MigrationRow recém-inserida (vinda do DJEN), consulta o DataJud
    e preenche automaticamente:
      - cliente       (parte ativa ou passiva)
      - vara_tramitacao (órgão julgador, se ainda vazio)
      - rompe_em_dias  (prazo extraído dos movimentos, se informado)
      - observacao    (anexa bloco DataJud com classe, ajuizamento e movimentos)

    Roda em paralelo com semáforo para não sobrecarregar a API.
    """
    if not row_ids:
        return

    rows = (
        db.query(MigrationRow)
        .filter(
            MigrationRow.office_id == office_id,
            MigrationRow.id.in_(row_ids),
        )
        .all()
    )

    sem = asyncio.Semaphore(5)   # máx 5 consultas simultâneas ao DataJud

    async def _processar_row(row: MigrationRow, client: httpx.AsyncClient) -> None:
        async with sem:
            tribunal = identificar_tribunal_por_numero(row.numero_processo)
            if not tribunal:
                return

            fonte = await _consultar_datajud(row.numero_processo, tribunal, client)
            if not fonte:
                return

            atualizado = False

            # ---- cliente (só preenche se vazio) ----
            if not (row.cliente or "").strip():
                # 1ª tentativa: partes do DataJud
                nome = (
                    _extrair_nome_parte(fonte, "ATIVO")
                    or _extrair_nome_parte(fonte, "PASSIVO")
                )
                # 2ª tentativa (fallback): texto da observação DJEN
                # (comum no TJBA onde partes vem null no DataJud)
                if not nome:
                    obs_atual = (row.observacao or "")
                    nome = _extrair_cliente_do_texto_djen(obs_atual)

                if nome:
                    row.cliente = nome
                    atualizado = True

            # ---- vara (só preenche se vazio) ----
            if not (row.vara_tramitacao or "").strip():
                orgao = ((fonte.get("orgaoJulgador") or {}).get("nome") or "").strip()
                if orgao:
                    row.vara_tramitacao = orgao
                    atualizado = True

            # ---- prazo: NÃO sobrescreve o que já veio do texto DJEN ----
            # O prazo processual está no texto da intimação DJEN, não nos
            # movimentos DataJud. Se já foi extraído na etapa anterior, mantém.

            # ---- bloco DataJud na observação ----
            classe   = ((fonte.get("classe") or {}).get("nome") or "").strip()
            grau     = (fonte.get("grau") or "").strip()
            d_ajuiz  = _parse_date_input(str(fonte.get("dataAjuizamento") or "")[:10])
            resumo   = _montar_resumo_movimentos(fonte, limite=5)

            bloco_partes = []
            if classe:
                bloco_partes.append(f"Classe: {classe}" + (f" ({grau})" if grau else ""))
            if d_ajuiz:
                bloco_partes.append(f"Ajuizamento: {d_ajuiz:%d/%m/%Y}")
            if resumo:
                bloco_partes.append(f"Movimentações recentes:\n{resumo}")

            if bloco_partes:
                bloco = f"\n\n[DataJud — {tribunal.upper()}]\n" + "\n".join(bloco_partes)
                existente = (row.observacao or "").rstrip()
                row.observacao = (existente + bloco)[:8000]
                atualizado = True

            if atualizado:
                db.add(row)

    async with httpx.AsyncClient() as client:
        tarefas = [_processar_row(row, client) for row in rows]
        await asyncio.gather(*tarefas, return_exceptions=True)

    try:
        db.commit()
    except Exception:
        db.rollback()


# ---------------------------------------------------------------------------
# DJEN — consulta paginada
# ---------------------------------------------------------------------------

async def consultar_djen_por_oab(
    numero_oab: str,
    uf_oab: str,
    data_inicio: date,
    data_fim: date,
) -> List[dict]:
    num, uf = _norm_oab(numero_oab, uf_oab)
    if not num:
        raise ValueError("Número da OAB inválido.")
    if not uf:
        raise ValueError("UF da OAB inválida.")
    if data_inicio > data_fim:
        data_inicio, data_fim = data_fim, data_inicio

    todos: List[dict] = []

    async with httpx.AsyncClient(timeout=DJEN_TIMEOUT) as client:
        for pagina in range(1, DJEN_MAX_PAGINAS + 1):
            params = {
                "numeroOab": num,
                "ufOab": uf,
                "dataDisponibilizacaoInicio": data_inicio.isoformat(),
                "dataDisponibilizacaoFim":   data_fim.isoformat(),
                "itensPorPagina": DJEN_ITENS_POR_PAGINA,
                "pagina": pagina,
            }
            try:
                resp = await client.get(DJEN_API_BASE, params=params)
            except httpx.RequestError as e:
                raise ValueError(f"Falha de conexão com o DJEN: {e}")

            if resp.status_code != 200:
                raise ValueError(f"DJEN retornou HTTP {resp.status_code}.")

            try:
                data = resp.json()
            except Exception:
                raise ValueError("Resposta inesperada do DJEN (não é JSON válido).")

            itens = data.get("items") or data.get("result") or []
            if not isinstance(itens, list):
                itens = []
            todos.extend(itens)

            if len(itens) < DJEN_ITENS_POR_PAGINA:
                break

    return todos


# ---------------------------------------------------------------------------
# Conversão DJEN → MigrationRow dict
# ---------------------------------------------------------------------------

def _item_djen_para_dict(item: dict) -> Optional[dict]:
    numero = str(
        item.get("numero_processo")
        or item.get("numeroProcesso")
        or item.get("numero")
        or ""
    ).strip()
    if not numero:
        return None

    data_disp = _parse_date_input(
        item.get("data_disponibilizacao") or item.get("dataDisponibilizacao")
    )

    # ✅ NOVO: data_publicacao = primeiro dia útil após disponibilização
    # (ignora o que vier da API, pois a regra legal é essa)
    data_pub = _primeiro_dia_util_apos(data_disp) if data_disp else None

    orgao    = (item.get("nomeOrgao") or item.get("orgao") or "").strip()
    tipo_com = (item.get("tipoComunicacao") or item.get("tipo_comunicacao") or "").strip()
    trib     = (item.get("siglaTribunal") or item.get("tribunal") or "").strip()

    diario_parts = [p for p in [trib, tipo_com] if p]
    diario = " — ".join(diario_parts) or None

    texto_raw = str(item.get("texto") or item.get("conteudo") or "")
    link      = item.get("link")

    # ✅ extrai prazo do texto da intimação DJEN (onde o prazo realmente está)
    prazo_dias = _extrair_prazo_do_texto_djen(texto_raw)

    # ✅ observação estruturada e legível
    obs = _montar_observacao(texto_raw, link)

    return {
        "data_disponibilizacao": data_disp,
        "data_publicacao":       data_pub,
        "numero_processo":       numero,
        "diario":                diario,
        "cliente":               None,
        "vara_tramitacao":       orgao or None,
        "_obs":                  obs,
        "_prazo_dias":           prazo_dias,  # ✅ novo
    }


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


def _processar_itens_djen(
    db: Session,
    office_id: int,
    batch_id: int,
    itens_djen: List[dict],
    nums_hoje: set,
    permitir_dup_hoje: bool,
) -> dict:
    total_extraidos = total_inseridos = total_ignorados = blocked_by_db = 0
    periodo_ini: Optional[date] = None
    periodo_fim: Optional[date] = None
    seen: set = set()
    buffer: List[MigrationRow] = []
    ids_inseridos: List[int] = []   # ✅ para enriquecimento DataJud em lote

    for raw in itens_djen:
        parsed = _item_djen_para_dict(raw)
        if parsed is None:
            continue

        total_extraidos += 1

        disp = parsed.get("data_disponibilizacao")
        pub  = parsed.get("data_publicacao")

        if disp and (periodo_ini is None or disp < periodo_ini):
            periodo_ini = disp
        if pub and (periodo_fim is None or pub > periodo_fim):
            periodo_fim = pub
        elif disp and (periodo_fim is None or disp > periodo_fim):
            periodo_fim = disp

        num = (parsed.get("numero_processo") or "").strip()
        if not num or num in seen:
            total_ignorados += 1
            continue
        if num in nums_hoje and not permitir_dup_hoje:
            total_ignorados += 1
            continue

        seen.add(num)

        row = MigrationRow(
            office_id=office_id,
            batch_id=batch_id,
            data_disponibilizacao=disp,
            data_publicacao=pub,
            numero_processo=num,
            diario=parsed.get("diario"),
        )
        _safe_set(row, "vara_tramitacao", parsed.get("vara_tramitacao"))
        _safe_set(row, "tipo_contagem", "uteis")
        _safe_set(row, "observacao", parsed.get("_obs") or None)

        # ✅ prazo extraído do texto DJEN (só preenche quando explícito)
        prazo_djen = parsed.get("_prazo_dias")
        if prazo_djen:
            _safe_set(row, "rompe_em_dias", prazo_djen)

        buffer.append(row)

        if len(buffer) >= INSERT_CHUNK_SIZE:
            ins, blk = _insert_chunk(db, buffer)
            total_inseridos += ins
            blocked_by_db   += blk
            total_ignorados += blk
            buffer.clear()

    if buffer:
        ins, blk = _insert_chunk(db, buffer)
        total_inseridos += ins
        blocked_by_db   += blk
        total_ignorados += blk
        buffer.clear()

    # coleta IDs inseridos para o enriquecimento DataJud em lote
    rows_inseridas = (
        db.query(MigrationRow.id)
        .filter(
            MigrationRow.office_id == office_id,
            MigrationRow.batch_id  == batch_id,
            MigrationRow.enviado_em.is_(None),
        )
        .all()
    )
    ids_inseridos = [r[0] for r in rows_inseridas]

    return {
        "total_extraidos":  total_extraidos,
        "total_inseridos":  total_inseridos,
        "total_ignorados":  total_ignorados,
        "blocked_by_db":    blocked_by_db,
        "periodo_ini":      periodo_ini,
        "periodo_fim":      periodo_fim,
        "ids_inseridos":    ids_inseridos,   # ✅ novo campo
    }


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

@router.post("/migracoes/consultar-djen")
async def migracoes_consultar_djen(
    request: Request,
    numero_oab: str = Form(...),
    uf_oab: str = Form(...),
    data_inicio: str = Form(...),
    data_fim: str = Form(...),
    dup_hoje: str = Form("nao"),
    db: Session = Depends(get_db),
):
    office_id = _get_office_id(request)
    permitir_dup_hoje = (dup_hoje or "").strip().lower() == "sim"

    di = _parse_date_input(data_inicio)
    df = _parse_date_input(data_fim)

    if not di or not df:
        return _redirect_msg("Datas inválidas. Use o formato AAAA-MM-DD.")
    if (df - di).days > 90:
        return _redirect_msg("Período máximo de consulta ao DJEN é de 90 dias.")

    num_oab, uf = _norm_oab(numero_oab, uf_oab)
    if not num_oab:
        return _redirect_msg("Informe um número de OAB válido.")
    if not uf:
        return _redirect_msg("Informe a UF da OAB (ex: SP, BA, RJ).")

    # ---- batch ----
    batch = MigrationBatch(office_id=office_id, criado_em=now_br())
    _safe_set(batch, "status", BatchStatus.PROCESSANDO)
    _safe_set(batch, "arquivo_nome",
              f"DJEN — OAB {num_oab}/{uf} ({di:%d/%m/%Y} a {df:%d/%m/%Y})")
    _safe_set(batch, "total_extraidos", 0)
    _safe_set(batch, "total_inseridos", 0)
    _safe_set(batch, "total_ignorados", 0)
    db.add(batch)
    db.commit()
    db.refresh(batch)
    batch_id = batch.id

    # ---- duplicidade ----
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

    # ---- consulta DJEN ----
    try:
        itens = await consultar_djen_por_oab(num_oab, uf, di, df)
    except ValueError as e:
        batch.status = BatchStatus.ERRO
        _safe_set(batch, "erro_processamento", str(e)[:10000])
        _safe_set(batch, "processado_em", now_br())
        db.add(batch); db.commit()
        return _redirect_msg(f"Falha na consulta ao DJEN: {e}")

    if not itens:
        batch.status = BatchStatus.CONCLUIDO
        _safe_set(batch, "processado_em", now_br())
        db.add(batch); db.commit()
        return _redirect_msg(
            f"Nenhuma intimação encontrada para OAB {num_oab}/{uf} "
            f"no período {di:%d/%m/%Y} a {df:%d/%m/%Y}."
        )

    # ---- processa e insere ----
    try:
        resultado = _processar_itens_djen(
            db=db,
            office_id=office_id,
            batch_id=batch_id,
            itens_djen=itens,
            nums_hoje=nums_hoje,
            permitir_dup_hoje=permitir_dup_hoje,
        )
    except Exception as e:
        db.rollback()
        batch = db.query(MigrationBatch).filter(MigrationBatch.id == batch_id).first()
        if batch:
            batch.status = BatchStatus.ERRO
            _safe_set(batch, "erro_processamento", str(e)[:10000])
            _safe_set(batch, "processado_em", now_br())
            db.add(batch); db.commit()
        return _redirect_msg(f"Falha ao processar resultados do DJEN: {e}")

    # ---- ✅ NOVO: enriquecimento DataJud automático em lote ----
    ids_inseridos = resultado.get("ids_inseridos") or []
    if ids_inseridos:
        try:
            await _enriquecer_lote_datajud(db, ids_inseridos, office_id)
        except Exception:
            pass   # enriquecimento é best-effort; não bloqueia o fluxo

    # ---- finaliza batch ----
    batch = db.query(MigrationBatch).filter(MigrationBatch.id == batch_id).first()
    if batch:
        batch.periodo_inicio = resultado["periodo_ini"]
        batch.periodo_fim    = resultado["periodo_fim"]
        batch.status         = BatchStatus.CONCLUIDO
        _safe_set(batch, "total_extraidos", resultado["total_extraidos"])
        _safe_set(batch, "total_inseridos", resultado["total_inseridos"])
        _safe_set(batch, "total_ignorados", resultado["total_ignorados"])
        _safe_set(batch, "processado_em", now_br())
        db.add(batch); db.commit()

    total_extraidos = resultado["total_extraidos"]
    total_inseridos = resultado["total_inseridos"]
    total_ignorados = resultado["total_ignorados"]
    blocked_by_db   = resultado["blocked_by_db"]

    if total_inseridos <= 0 and total_extraidos > 0:
        return _redirect_msg(
            f"Consulta DJEN concluída, mas nenhum item novo inserido. "
            f"Extraídos: {total_extraidos}. Ignorados: {total_ignorados}."
        )
    if blocked_by_db > 0:
        return _redirect_msg(
            f"Consulta DJEN concluída. Inseridos: {total_inseridos}. "
            f"Ignorados: {total_ignorados}. Bloqueados por duplicidade: {blocked_by_db}."
        )
    return _redirect_msg(
        f"Consulta DJEN concluída (OAB {num_oab}/{uf}). "
        f"Inseridos: {total_inseridos}. Ignorados: {total_ignorados}."
    )


@router.post("/migracoes/{row_id}/enriquecer-datajud")
async def migracoes_enriquecer_datajud(
    request: Request,
    row_id: int,
    db: Session = Depends(get_db),
):
    """Enriquece um item individual via DataJud (botão ⚖️ DataJud na tabela)."""
    office_id = _get_office_id(request)

    row = (
        db.query(MigrationRow)
        .filter(MigrationRow.id == row_id, MigrationRow.office_id == office_id)
        .first()
    )
    if not row:
        return _redirect_msg("Item não encontrado.")
    if row.enviado_em is not None:
        return _redirect_msg("Este item já foi migrado — não é possível enriquecer.")

    numero = (row.numero_processo or "").strip()
    if not numero:
        return _redirect_msg("Item sem número de processo válido.")

    tribunal = identificar_tribunal_por_numero(numero)
    if not tribunal:
        return _redirect_msg(
            f"Tribunal não identificado para '{numero}' "
            f"(fora do padrão CNJ ou não mapeado)."
        )

    async with httpx.AsyncClient() as client:
        fonte = await _consultar_datajud(numero, tribunal, client)

    if not fonte:
        return _redirect_msg(
            f"Processo {numero} não encontrado no DataJud ({tribunal.upper()}). "
            f"Pode haver defasagem de atualização."
        )

    atualizado = []

    # cliente
    if not (row.cliente or "").strip():
        # 1ª tentativa: partes do DataJud
        nome = _extrair_nome_parte(fonte, "ATIVO") or _extrair_nome_parte(fonte, "PASSIVO")
        # 2ª tentativa: texto da intimação DJEN na observação (fallback p/ TJBA)
        if not nome:
            nome = _extrair_cliente_do_texto_djen(row.observacao or "")
        if nome:
            row.cliente = nome
            atualizado.append("cliente")

    # vara
    if not (row.vara_tramitacao or "").strip():
        orgao = ((fonte.get("orgaoJulgador") or {}).get("nome") or "").strip()
        if orgao:
            row.vara_tramitacao = orgao
            atualizado.append("vara")

    # bloco DataJud na observação
    classe  = ((fonte.get("classe") or {}).get("nome") or "").strip()
    grau    = (fonte.get("grau") or "").strip()
    d_ajuiz = _parse_date_input(str(fonte.get("dataAjuizamento") or "")[:10])
    resumo  = _montar_resumo_movimentos(fonte, limite=5)

    bloco_partes = []
    if classe:
        bloco_partes.append(f"Classe: {classe}" + (f" ({grau})" if grau else ""))
    if d_ajuiz:
        bloco_partes.append(f"Ajuizamento: {d_ajuiz:%d/%m/%Y}")
    if resumo:
        bloco_partes.append(f"Movimentações recentes:\n{resumo}")

    if bloco_partes:
        bloco = f"\n\n[DataJud — {tribunal.upper()}]\n" + "\n".join(bloco_partes)
        existente = (row.observacao or "").rstrip()
        row.observacao = (existente + bloco)[:8000]
        atualizado.append("movimentações")

    db.add(row)
    db.commit()

    if not atualizado:
        return _redirect_msg(
            f"Processo {numero} encontrado no DataJud ({tribunal.upper()}), "
            f"sem novas informações para preencher."
        )
    return _redirect_msg(
        f"Processo {numero} enriquecido via DataJud ({tribunal.upper()}). "
        f"Atualizado: {', '.join(atualizado)}."
    )