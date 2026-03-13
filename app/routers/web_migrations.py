import re
from datetime import datetime, date, timedelta
from typing import List, Tuple, Optional

from fastapi import APIRouter, Request, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from app.core.database import get_db
from app.models.migration import MigrationBatch, MigrationRow
from app.models.process_item import ProcessItem

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ==========================================================
# ✅ FILTRO JINJA: br_date (DD/MM/AAAA)
# ==========================================================
def _br_date(value) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, datetime):
            return value.strftime("%d/%m/%Y")
        if isinstance(value, date):
            return value.strftime("%d/%m/%Y")

        s = str(value).strip()
        if not s:
            return ""

        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
        if m:
            y, mo, d = m.groups()
            return f"{d}/{mo}/{y}"

        m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
        if m:
            return s

        return s
    except Exception:
        return str(value)


templates.env.filters["br_date"] = _br_date


# =========================
# Utils
# =========================
def _ext(filename: str) -> str:
    filename = (filename or "").lower().strip()
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1]


def _parse_date_br(val) -> Optional[date]:
    if val is None:
        return None
    try:
        if hasattr(val, "to_pydatetime"):
            return val.to_pydatetime().date()
    except Exception:
        pass

    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val

    s = str(val).strip()
    if not s:
        return None

    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        d, mo, y = m.groups()
        return date(int(y), int(mo), int(d))

    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        y, mo, d = m.groups()
        return date(int(y), int(mo), int(d))

    return None


def add_business_days(start: date, days: int) -> date:
    if days <= 0:
        return start
    cur = start
    added = 0
    while added < days:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur


def _normalize_status(dest: str) -> str:
    """
    Retorna o CÓDIGO da aba usado em /processos?status=...
    """
    dest_up = (dest or "").strip().upper()
    if dest_up in {"PRAZOS", "PRAZO", "CONTROLE DE PRAZOS", "CONTROLE DE PRAZO"}:
        return "PRAZOS"
    if dest_up in {"PROCEDENTE", "AÇÕES PROCEDENTES", "ACOES PROCEDENTES"}:
        return "PROCEDENTE"
    if dest_up in {"EXECUCAO", "EXECUÇÃO", "AÇÕES EM EXECUÇÃO", "ACOES EM EXECUCAO"}:
        return "EXECUCAO"
    return "PRAZOS"


def _safe_set(obj, field: str, value):
    """Seta somente se o atributo existir no modelo (evita quebrar por diferença de schema)."""
    if hasattr(obj, field):
        setattr(obj, field, value)


# ==========================================================
# ✅ Campos NOT NULL do ProcessItem (defaults seguros)
# ==========================================================
def _default_parte_autora(cliente: str) -> str:
    c = (cliente or "").strip()
    return c if c else "(não informado)"


def _default_vara(vara: str) -> str:
    v = (vara or "").strip()
    return v if v else "(não informada)"


def _set_obs_compat(obj, text: str):
    """
    Sua tela de processos usa 'obs' (não 'observacao').
    Alguns bancos antigos podem ter 'observacao' -> então preenche os dois, se existirem.
    """
    t = (text or "").strip()
    if not t:
        return
    _safe_set(obj, "obs", t)
    _safe_set(obj, "observacao", t)


# ==========================================================
# ✅ Campo do número do processo no ProcessItem + normalização
# ==========================================================
def _process_number_fields():
    return [
        "numero_processo",
        "numero",
        "processo",
        "processo_numero",
        "n_processo",
        "num_processo",
    ]


def _norm_numproc(s: str) -> Tuple[str, str]:
    raw = (s or "").strip()
    digits = re.sub(r"\D+", "", raw) if raw else ""
    return raw, digits


def _set_process_number(item: ProcessItem, numero: str) -> bool:
    raw, digits = _norm_numproc(numero)
    for f in _process_number_fields():
        if hasattr(item, f):
            setattr(item, f, raw)  # mantém formatado
            return True
    return False


def _find_existing_process_item(db: Session, numero: str) -> Optional[ProcessItem]:
    raw, digits = _norm_numproc(numero)
    if not raw and not digits:
        return None

    for f in _process_number_fields():
        if hasattr(ProcessItem, f):
            col = getattr(ProcessItem, f)

            if raw:
                obj = db.query(ProcessItem).filter(col == raw).first()
                if obj:
                    return obj

            if digits:
                obj = db.query(ProcessItem).filter(col == digits).first()
                if obj:
                    return obj

    return None


# =========================
# Parser (HTML/XLS/XLSX/TXT)
# =========================
PERIODO_RX = re.compile(
    r"per[ií]odo:\s*(\d{2}/\d{2}/\d{4})\s*at[eé]\s*(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)


def _norm_label(v) -> str:
    s = ("" if v is None else str(v)).strip().lower()
    s = s.replace("º", "").replace("°", "")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^data(?=[a-zà-ú])", "data ", s, flags=re.IGNORECASE)
    s = s.replace("datadisponibilização", "data disponibilização").replace("datadisponibilizacao", "data disponibilizacao")
    s = s.replace("datapublicação", "data publicação").replace("datapublicacao", "data publicacao")
    return s.strip()


def _find_periodo_in_matrix(matrix: List[List[object]]) -> Tuple[Optional[date], Optional[date]]:
    for row in matrix[:80]:
        for cell in row[:60]:
            if cell is None:
                continue
            s = str(cell)
            m = PERIODO_RX.search(s)
            if m:
                ini = _parse_date_br(m.group(1))
                fim = _parse_date_br(m.group(2))
                return ini, fim
    return None, None


def _find_header_in_matrix(matrix: List[List[object]]) -> Tuple[int, dict]:
    want = {
        "disp": {
            "disponibilização", "data disponibilização", "data de disponibilização", "disponibilizacao",
            "data disponibilizacao", "data de disponibilizacao",
        },
        "pub": {
            "publicação", "data publicação", "data da publicação", "publicacao",
            "data publicacao", "data da publicacao",
        },
        "proc": {
            "n processo", "no processo", "nº processo",
            "número do processo", "numero do processo",
            "processo", "n. processo",
        },
        "diario": {"diário", "diario", "dj", "djen", "diário de justiça"},
    }

    for r in range(min(120, len(matrix))):
        row = matrix[r]
        col_map = {}
        for c in range(min(120, len(row))):
            label = _norm_label(row[c])
            if not label:
                continue
            for key, variants in want.items():
                if label in variants:
                    col_map[key] = c
        if "disp" in col_map and "pub" in col_map and "proc" in col_map:
            return r, col_map

    raise ValueError("Não consegui encontrar o cabeçalho (Disponibilização/Publicação/Nº Processo).")


def _is_xls_ole(file_bytes: bytes) -> bool:
    return file_bytes[:8] == b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"


def _is_zip_xlsx(file_bytes: bytes) -> bool:
    return file_bytes[:4] == b"PK\x03\x04"


def _is_html(file_bytes: bytes) -> bool:
    head = file_bytes[:4096].lstrip().lower()
    return head.startswith(b"<html") or b"<table" in head


def _read_text_table_to_matrix(file_bytes: bytes) -> List[List[object]]:
    import io
    import pandas as pd

    for sep in ["\t", ";", ","]:
        try:
            df = pd.read_csv(
                io.BytesIO(file_bytes),
                sep=sep,
                header=None,
                encoding="utf-8-sig",
                engine="python",
            )
            if df.shape[1] <= 1 and sep != ",":
                continue
            return df.where(df.notna(), None).values.tolist()
        except Exception:
            continue

    raise ValueError("Arquivo parece ser texto, mas não consegui interpretar (TSV/CSV).")


def _read_html_tables_stdlib(file_bytes: bytes) -> List[List[List[object]]]:
    from html.parser import HTMLParser

    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tables = []
            self._in_table = False
            self._in_tr = False
            self._in_cell = False
            self._cell = ""
            self._cur_table = []
            self._cur_row = []

        def handle_starttag(self, tag, attrs):
            tag = tag.lower()
            if tag == "table":
                self._in_table = True
                self._cur_table = []
            elif tag == "tr" and self._in_table:
                self._in_tr = True
                self._cur_row = []
            elif tag in ("td", "th") and self._in_tr and self._in_table:
                self._in_cell = True
                self._cell = ""

        def handle_data(self, data):
            if self._in_cell and self._in_table and self._in_tr:
                self._cell += data

        def handle_endtag(self, tag):
            tag = tag.lower()
            if tag in ("td", "th") and self._in_cell:
                self._in_cell = False
                txt = re.sub(r"\s+", " ", self._cell).strip()
                self._cur_row.append(txt if txt != "" else None)
                self._cell = ""
            elif tag == "tr" and self._in_tr:
                self._in_tr = False
                if self._cur_row:
                    self._cur_table.append(self._cur_row)
                self._cur_row = []
            elif tag == "table" and self._in_table:
                self._in_table = False
                if self._cur_table:
                    self.tables.append(self._cur_table)
                self._cur_table = []

    html = file_bytes.decode("utf-8", errors="ignore")
    p = Parser()
    p.feed(html)
    return p.tables


def _choose_best_table(tables: List[List[List[object]]]) -> List[List[object]]:
    best = None
    for t in tables:
        try:
            _find_header_in_matrix(t)
            return t
        except Exception:
            best = best or t
    if best is None:
        raise ValueError("Não encontrei nenhuma tabela no HTML.")
    return best


def _read_any_to_matrix(file_bytes: bytes, filename: str) -> Tuple[List[List[object]], Optional[date], Optional[date]]:
    import io
    import pandas as pd

    if _is_zip_xlsx(file_bytes):
        df = pd.read_excel(io.BytesIO(file_bytes), header=None, engine="openpyxl")
        matrix = df.where(df.notna(), None).values.tolist()
        return matrix, *_find_periodo_in_matrix(matrix)

    if _is_xls_ole(file_bytes):
        df = pd.read_excel(io.BytesIO(file_bytes), header=None, engine="xlrd")
        matrix = df.where(df.notna(), None).values.tolist()
        return matrix, *_find_periodo_in_matrix(matrix)

    if _is_html(file_bytes):
        tables = _read_html_tables_stdlib(file_bytes)
        best = _choose_best_table(tables)

        periodo_ini = None
        periodo_fim = None
        for t in tables:
            ini, fim = _find_periodo_in_matrix(t)
            if ini and (periodo_ini is None or ini < periodo_ini):
                periodo_ini = ini
            if fim and (periodo_fim is None or fim > periodo_fim):
                periodo_fim = fim

        return best, periodo_ini, periodo_fim

    matrix = _read_text_table_to_matrix(file_bytes)
    return matrix, *_find_periodo_in_matrix(matrix)


def parse_planilha_bytes(file_bytes: bytes, filename: str) -> Tuple[List[dict], Optional[date], Optional[date]]:
    matrix, periodo_ini, periodo_fim = _read_any_to_matrix(file_bytes, filename)
    header_r, col_map = _find_header_in_matrix(matrix)

    disp_c = col_map.get("disp")
    pub_c = col_map.get("pub")
    proc_c = col_map.get("proc")
    diario_c = col_map.get("diario")

    rows = []
    empty_streak = 0

    for r in range(header_r + 1, len(matrix)):
        row = matrix[r]
        numero = row[proc_c] if proc_c is not None and proc_c < len(row) else None
        numero_str = ("" if numero is None else str(numero)).strip()

        if not numero_str:
            empty_streak += 1
            if empty_streak >= 2:
                break
            continue
        empty_streak = 0

        disp = _parse_date_br(row[disp_c]) if disp_c is not None and disp_c < len(row) else None
        pub = _parse_date_br(row[pub_c]) if pub_c is not None and pub_c < len(row) else None

        diario = None
        if diario_c is not None and diario_c < len(row):
            dv = row[diario_c]
            diario = ("" if dv is None else str(dv)).strip() or None

        rows.append(
            {
                "data_disponibilizacao": disp,
                "data_publicacao": pub,
                "numero_processo": numero_str,
                "diario": diario,
            }
        )

    return rows, periodo_ini, periodo_fim


# =========================
# Views
# =========================
@router.get("/migracoes", response_class=HTMLResponse)
def migracoes_view(request: Request, db: Session = Depends(get_db)):
    last_batch = db.query(MigrationBatch).order_by(MigrationBatch.id.desc()).first()

    pendentes = (
        db.query(MigrationRow)
        .filter(MigrationRow.enviado_em.is_(None))
        .order_by(MigrationRow.data_disponibilizacao.asc().nullslast(), MigrationRow.id.asc())
        .all()
    )

    from collections import Counter
    nums = [p.numero_processo for p in pendentes if (p.numero_processo or "").strip()]
    c = Counter(nums)
    dup_nums = [n for n, qtd in c.items() if qtd > 1]

    msg = request.query_params.get("msg")
    return templates.TemplateResponse(
        "migrations/index.html",
        {
            "request": request,
            "title": "Migrações",
            "last_batch": last_batch,
            "pendentes": pendentes,
            "msg": msg,
            "dup_nums": dup_nums,
        },
    )


# =========================
# Upload
# =========================
@router.post("/migracoes/upload")
async def migracoes_upload(
    files: List[UploadFile] = File(...),
    dup_hoje: str = Form("nao"),
    db: Session = Depends(get_db),
):
    permitir_dup_hoje = (dup_hoje or "").strip().lower() == "sim"

    batch = MigrationBatch(criado_em=datetime.utcnow())
    db.add(batch)
    db.commit()
    db.refresh(batch)

    periodo_ini = None
    periodo_fim = None

    seen_in_this_upload = set()

    hoje = date.today()
    nums_hoje = set(
        x[0] for x in
        db.query(MigrationRow.numero_processo)
        .join(MigrationBatch, MigrationBatch.id == MigrationRow.batch_id)
        .filter(func.date(MigrationBatch.criado_em) == hoje)
        .all()
        if x and x[0]
    )

    duplicated_today_ignored = 0
    duplicated_today_inserted = 0
    blocked_by_db = 0

    for f in files:
        content = await f.read()
        if not content:
            continue

        ext = _ext(f.filename)
        if ext not in {"xls", "xlsx", "xlsm", "csv", "txt", "html", "htm"}:
            msg = f"Arquivo '{f.filename}' não suportado. Envie .XLS/.XLSX/.XLSM (ou exportações texto/HTML)."
            return RedirectResponse(url=f"/migracoes?msg={msg}", status_code=303)

        try:
            parsed_rows, p_ini, p_fim = parse_planilha_bytes(content, f.filename)
        except Exception as e:
            msg = f"Falha ao ler '{f.filename}'. Motivo: {str(e)}"
            return RedirectResponse(url=f"/migracoes?msg={msg}", status_code=303)

        if p_ini and (periodo_ini is None or p_ini < periodo_ini):
            periodo_ini = p_ini
        if p_fim and (periodo_fim is None or p_fim > periodo_fim):
            periodo_fim = p_fim

        for r in parsed_rows:
            num = (r.get("numero_processo") or "").strip()
            if not num:
                continue

            if num in seen_in_this_upload:
                continue
            seen_in_this_upload.add(num)

            if (num in nums_hoje) and (not permitir_dup_hoje):
                duplicated_today_ignored += 1
                continue

            if (num in nums_hoje) and permitir_dup_hoje:
                duplicated_today_inserted += 1

            row = MigrationRow(
                batch_id=batch.id,
                data_disponibilizacao=r.get("data_disponibilizacao"),
                data_publicacao=r.get("data_publicacao"),
                numero_processo=num,
                diario=r.get("diario"),
            )
            db.add(row)

            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                blocked_by_db += 1
                continue

    batch.periodo_inicio = periodo_ini
    batch.periodo_fim = periodo_fim
    db.commit()

    if duplicated_today_ignored > 0 and not permitir_dup_hoje:
        msg = (
            f"Atenção: {duplicated_today_ignored} processo(s) deste upload já foram migrados hoje e foram ignorados, "
            f"pois você marcou 'Não' em duplicar."
        )
        return RedirectResponse(url=f"/migracoes?msg={msg}", status_code=303)

    if permitir_dup_hoje:
        if duplicated_today_inserted > 0:
            msg = (
                f"Atenção: você escolheu 'Sim' e {duplicated_today_inserted} processo(s) já migrados hoje foram inseridos novamente "
                f"(destacados em vermelho)."
            )
            if blocked_by_db > 0:
                msg += f" Obs.: {blocked_by_db} registro(s) foram bloqueados pelo banco por duplicidade dentro do mesmo lote."
            return RedirectResponse(url=f"/migracoes?msg={msg}", status_code=303)
        else:
            msg = "Você escolheu 'Sim', mas não havia processos já migrados hoje neste upload. Nenhuma duplicidade foi gerada."
            return RedirectResponse(url=f"/migracoes?msg={msg}", status_code=303)

    if blocked_by_db > 0:
        msg = f"Atenção: {blocked_by_db} registro(s) foram bloqueados pelo banco por duplicidade dentro do mesmo lote."
        return RedirectResponse(url=f"/migracoes?msg={msg}", status_code=303)

    return RedirectResponse(url="/migracoes", status_code=303)


# ==========================================================
# ✅ SALVAR/MIGRAR (UPSERT robusto) - CORRIGIDO p/ DJEN + OBS
# ==========================================================
def _migrar_row_para_process_item(
    db: Session,
    row: MigrationRow,
    cliente: str,
    vara: str,
    obs: str,
    rompe_em: int,
    dest: str
):
    aba_code = _normalize_status(dest)  # "PROCEDENTE" | "EXECUCAO" | "PRAZOS"

    # NOT NULL
    parte_autora = _default_parte_autora(cliente)
    vara_value = _default_vara(vara)

    # ✅ DJEN (data de início da contagem) — a tela de Processos usa data_intimacao
    djen = row.data_publicacao or row.data_disponibilizacao or date.today()

    # ✅ prazo e vencimento — a tela usa prazo_dias e vencimento
    try:
        prazo_int = int(rompe_em or 0)
    except Exception:
        prazo_int = 0

    venc = add_business_days(djen, prazo_int) if prazo_int > 0 else None

    existing = _find_existing_process_item(db, row.numero_processo)

    if existing:
        _safe_set(existing, "aba", aba_code)
        _safe_set(existing, "parte_autora", parte_autora)
        _safe_set(existing, "vara", vara_value)

        # compat se existir
        _safe_set(existing, "vara_tramitacao", vara_value)
        _safe_set(existing, "cliente", (cliente or "").strip() or getattr(existing, "cliente", None))

        # ✅ DJEN + Prazo + Vencimento
        _safe_set(existing, "data_intimacao", djen)
        _safe_set(existing, "prazo_dias", prazo_int if prazo_int > 0 else getattr(existing, "prazo_dias", None))
        _safe_set(existing, "vencimento", venc)

        # ✅ Observação (campo correto é 'obs')
        if (obs or "").strip():
            old = (getattr(existing, "obs", None) or getattr(existing, "observacao", None) or "").strip()
            nova = (obs or "").strip()
            tag = f"[MIGRAÇÃO {date.today().strftime('%d/%m/%Y')}]"
            merged = (old + ("\n" if old else "") + f"{tag} {nova}").strip()
            _set_obs_compat(existing, merged)

        # ✅ REGRA: ao enviar para PRAZOS (Controle de Prazos), sempre voltar para PENDENTE
        if aba_code == "PRAZOS" and hasattr(existing, "cumprimento"):
            _safe_set(existing, "cumprimento", "PENDENTE")

        _safe_set(existing, "atualizado_em", datetime.utcnow())
        db.add(existing)
        db.flush()

    else:
        item = ProcessItem()
        if not _set_process_number(item, row.numero_processo):
            raise HTTPException(status_code=500, detail="ProcessItem não possui campo para número do processo.")

        _safe_set(item, "aba", aba_code)
        _safe_set(item, "parte_autora", parte_autora)
        _safe_set(item, "vara", vara_value)

        # compat se existir
        _safe_set(item, "vara_tramitacao", vara_value)
        _safe_set(item, "cliente", (cliente or "").strip() or None)

        # ✅ DJEN + Prazo + Vencimento
        _safe_set(item, "data_intimacao", djen)
        _safe_set(item, "prazo_dias", prazo_int if prazo_int > 0 else None)
        _safe_set(item, "vencimento", venc)

        # ✅ Observação
        _set_obs_compat(item, (obs or "").strip())

        # default cumprimento
        if aba_code == "PRAZOS" and hasattr(item, "cumprimento"):
            _safe_set(item, "cumprimento", "PENDENTE")

        _safe_set(item, "criado_em", datetime.utcnow())
        _safe_set(item, "atualizado_em", datetime.utcnow())

        db.add(item)
        try:
            db.flush()
        except IntegrityError as e:
            db.rollback()
            existing2 = _find_existing_process_item(db, row.numero_processo)
            if existing2:
                _safe_set(existing2, "aba", aba_code)
                _safe_set(existing2, "parte_autora", parte_autora)
                _safe_set(existing2, "vara", vara_value)
                _safe_set(existing2, "data_intimacao", djen)
                _safe_set(existing2, "prazo_dias", prazo_int if prazo_int > 0 else getattr(existing2, "prazo_dias", None))
                _safe_set(existing2, "vencimento", venc)

                if (obs or "").strip():
                    old = (getattr(existing2, "obs", None) or getattr(existing2, "observacao", None) or "").strip()
                    nova = (obs or "").strip()
                    tag = f"[MIGRAÇÃO {date.today().strftime('%d/%m/%Y')}]"
                    merged = (old + ("\n" if old else "") + f"{tag} {nova}").strip()
                    _set_obs_compat(existing2, merged)

                # ✅ REGRA: ao enviar para PRAZOS (Controle de Prazos), sempre voltar para PENDENTE
                if aba_code == "PRAZOS" and hasattr(existing2, "cumprimento"):
                    _safe_set(existing2, "cumprimento", "PENDENTE")

                _safe_set(existing2, "atualizado_em", datetime.utcnow())
                db.add(existing2)
                db.flush()
            else:
                detail = str(e.orig) if getattr(e, "orig", None) else str(e)
                raise HTTPException(status_code=409, detail=f"Falha ao salvar por constraint/duplicidade: {detail}")

    # marca MigrationRow como enviado (apenas log/histórico)
    row.cliente = cliente
    row.vara_tramitacao = vara
    row.observacao = obs
    row.rompe_em_dias = prazo_int if str(rompe_em or "").strip() else None
    row.enviar_para = aba_code
    row.enviado_em = datetime.utcnow()
    row.enviado_para_status = aba_code
    db.add(row)


# =========================
# Salvar individual
# =========================
@router.post("/migracoes/salvar/{row_id}")
def migracoes_salvar_individual(
    row_id: int,
    cliente: str = Form(""),
    vara_tramitacao: str = Form(""),
    observacao: str = Form(""),
    rompe_em: int = Form(0),
    enviar_para: str = Form("PRAZOS"),
    db: Session = Depends(get_db),
):
    row = db.query(MigrationRow).filter(MigrationRow.id == row_id).first()
    if not row:
        return RedirectResponse(url="/migracoes?msg=Item não encontrado.", status_code=303)

    if row.enviado_em is not None:
        return RedirectResponse(url="/migracoes?msg=Este item já foi migrado.", status_code=303)

    try:
        _migrar_row_para_process_item(db, row, cliente, vara_tramitacao, observacao, rompe_em, enviar_para)
        db.commit()
    except HTTPException as e:
        db.rollback()
        return RedirectResponse(url=f"/migracoes?msg={e.detail}", status_code=303)
    except Exception as e:
        db.rollback()
        return RedirectResponse(url=f"/migracoes?msg=Erro ao migrar: {str(e)}", status_code=303)

    return RedirectResponse(url="/migracoes?msg=Item migrado com sucesso.", status_code=303)


# =========================
# Salvar lote (selecionados)
# =========================
@router.post("/migracoes/salvar-lote")
async def migracoes_salvar_lote(
    request: Request,
    selected_ids: List[int] = Form([]),
    db: Session = Depends(get_db),
):
    if not selected_ids:
        return RedirectResponse(url="/migracoes?msg=Nenhum item selecionado.", status_code=303)

    rows = (
        db.query(MigrationRow)
        .filter(MigrationRow.id.in_(selected_ids))
        .filter(MigrationRow.enviado_em.is_(None))
        .all()
    )

    form = await request.form()

    ok = 0
    fail = 0

    for row in rows:
        rid = row.id
        cliente = str(form.get(f"cliente_{rid}", "") or "")
        vara = str(form.get(f"vara_{rid}", "") or "")
        obs = str(form.get(f"obs_{rid}", "") or "")
        rompe = form.get(f"rompe_{rid}", "0") or "0"
        dest = str(form.get(f"dest_{rid}", "PRAZOS") or "PRAZOS")

        try:
            rompe_int = int(str(rompe).strip() or "0")
        except Exception:
            rompe_int = 0

        try:
            _migrar_row_para_process_item(db, row, cliente, vara, obs, rompe_int, dest)
            ok += 1
        except Exception:
            db.rollback()
            fail += 1

    try:
        db.commit()
    except Exception:
        db.rollback()

    msg = f"Migração concluída. Sucesso: {ok}. Falhas: {fail}."
    return RedirectResponse(url=f"/migracoes?msg={msg}", status_code=303)


# =========================
# Excluir pendente individual
# =========================
@router.post("/migracoes/pendente/{row_id}/excluir")
def migracoes_excluir_pendente(row_id: int, db: Session = Depends(get_db)):
    row = db.query(MigrationRow).filter(MigrationRow.id == row_id).first()
    if not row:
        return RedirectResponse(url="/migracoes?msg=Item não encontrado.", status_code=303)

    if row.enviado_em is not None:
        return RedirectResponse(url="/migracoes?msg=Não é possível excluir: item já foi migrado.", status_code=303)

    db.delete(row)
    db.commit()
    return RedirectResponse(url="/migracoes?msg=Item excluído.", status_code=303)


# =========================
# Excluir lote
# =========================
@router.post("/migracoes/pendente/excluir-lote")
def migracoes_excluir_lote(ids: str = Form(""), db: Session = Depends(get_db)):
    ids = (ids or "").strip()
    if not ids:
        return RedirectResponse(url="/migracoes?msg=Nenhum item selecionado para excluir.", status_code=303)

    try:
        id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    except Exception:
        id_list = []

    if not id_list:
        return RedirectResponse(url="/migracoes?msg=IDs inválidos.", status_code=303)

    rows = (
        db.query(MigrationRow)
        .filter(MigrationRow.id.in_(id_list))
        .filter(MigrationRow.enviado_em.is_(None))
        .all()
    )

    for r in rows:
        db.delete(r)

    db.commit()
    return RedirectResponse(url="/migracoes?msg=Itens excluídos.", status_code=303)
