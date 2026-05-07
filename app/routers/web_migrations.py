import gc
import os
import re
import tempfile
from datetime import datetime, date, timedelta
from typing import List, Tuple, Optional, Iterable
from urllib.parse import quote

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

from fastapi import APIRouter, Request, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from app.core.database import get_db
from app.core.datetime_utils import now_br
from app.models.migration import MigrationBatch, MigrationRow
from app.models.process_item import ProcessItem


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


MAX_UPLOAD_MB = 150
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
INSERT_CHUNK_SIZE = 300


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


def _set_batch_status(
    db: Session,
    batch: MigrationBatch,
    status: str,
    erro: Optional[str] = None,
    total_extraidos: Optional[int] = None,
    total_inseridos: Optional[int] = None,
    total_ignorados: Optional[int] = None,
    processado: bool = False,
):
    _safe_set(batch, "status", status)

    if erro is not None:
        _safe_set(batch, "erro_processamento", str(erro)[:10000])

    if total_extraidos is not None:
        _safe_set(batch, "total_extraidos", int(total_extraidos or 0))

    if total_inseridos is not None:
        _safe_set(batch, "total_inseridos", int(total_inseridos or 0))

    if total_ignorados is not None:
        _safe_set(batch, "total_ignorados", int(total_ignorados or 0))

    if processado:
        _safe_set(batch, "processado_em", now_br())

    db.add(batch)
    db.commit()
    db.refresh(batch)


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
    dest_up = (dest or "").strip().upper()

    if dest_up in {"PRAZOS", "PRAZO", "CONTROLE DE PRAZOS", "CONTROLE DE PRAZO"}:
        return "PRAZOS"

    if dest_up in {"PROCEDENTE", "AÇÕES PROCEDENTES", "ACOES PROCEDENTES"}:
        return "PROCEDENTE"

    if dest_up in {"EXECUCAO", "EXECUÇÃO", "AÇÕES EM EXECUÇÃO", "ACOES EM EXECUCAO"}:
        return "EXECUCAO"

    return "PRAZOS"


def _default_parte_autora(cliente: str) -> str:
    c = (cliente or "").strip()
    return c if c else "(não informado)"


def _default_vara(vara: str) -> str:
    v = (vara or "").strip()
    return v if v else "(não informada)"


def _set_obs_compat(obj, text: str):
    t = (text or "").strip()
    if not t:
        return

    _safe_set(obj, "obs", t)
    _safe_set(obj, "observacao", t)


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
    raw, _digits = _norm_numproc(numero)

    for f in _process_number_fields():
        if hasattr(item, f):
            setattr(item, f, raw)
            return True

    return False


def _find_existing_process_item(db: Session, office_id: int, numero: str) -> Optional[ProcessItem]:
    raw, digits = _norm_numproc(numero)

    if not raw and not digits:
        return None

    for f in _process_number_fields():
        if hasattr(ProcessItem, f):
            col = getattr(ProcessItem, f)

            if raw:
                obj = (
                    db.query(ProcessItem)
                    .filter(
                        ProcessItem.office_id == office_id,
                        col == raw,
                    )
                    .first()
                )
                if obj:
                    return obj

            if digits:
                obj = (
                    db.query(ProcessItem)
                    .filter(
                        ProcessItem.office_id == office_id,
                        col == digits,
                    )
                    .first()
                )
                if obj:
                    return obj

    return None


def _find_existing_process_items_map(
    db: Session,
    office_id: int,
    numeros: List[str],
) -> dict:
    result = {}

    cleaned = []
    for n in numeros:
        raw, digits = _norm_numproc(n)
        if raw:
            cleaned.append(raw)
        if digits:
            cleaned.append(digits)

    cleaned = list(set(cleaned))

    if not cleaned:
        return result

    for f in _process_number_fields():
        if not hasattr(ProcessItem, f):
            continue

        col = getattr(ProcessItem, f)

        found = (
            db.query(ProcessItem)
            .filter(
                ProcessItem.office_id == office_id,
                col.in_(cleaned),
            )
            .all()
        )

        for item in found:
            val = getattr(item, f, None)
            raw, digits = _norm_numproc(val)
            if raw:
                result[raw] = item
            if digits:
                result[digits] = item

    return result


PERIODO_RX = re.compile(
    r"per[ií]odo:\s*(\d{2}/\d{2}/\d{4})\s*at[eé]\s*(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)


PDF_BLOCK_MARKER_RX = re.compile(
    r"(?mi)^(PUBLICAÇÃO:\s*\d+(?:\s+de\s+\d+)?|Sequencial:\s*\d+)"
)


def _norm_label(v) -> str:
    s = ("" if v is None else str(v)).strip().lower()
    s = s.replace("º", "").replace("°", "")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^data(?=[a-zà-ú])", "data ", s, flags=re.IGNORECASE)
    s = s.replace("datadisponibilização", "data disponibilização").replace(
        "datadisponibilizacao",
        "data disponibilizacao",
    )
    s = s.replace("datapublicação", "data publicação").replace(
        "datapublicacao",
        "data publicacao",
    )
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
            "disponibilização",
            "data disponibilização",
            "data de disponibilização",
            "disponibilizacao",
            "data disponibilizacao",
            "data de disponibilizacao",
        },
        "pub": {
            "publicação",
            "data publicação",
            "data da publicação",
            "publicacao",
            "data publicacao",
            "data da publicacao",
        },
        "proc": {
            "n processo",
            "no processo",
            "nº processo",
            "número do processo",
            "numero do processo",
            "processo",
            "n. processo",
        },
        "diario": {
            "diário",
            "diario",
            "dj",
            "djen",
            "diário de justiça",
        },
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


def _is_pdf_by_path(path: str, filename: str = "") -> bool:
    if (filename or "").lower().endswith(".pdf"):
        return True

    try:
        with open(path, "rb") as fp:
            return fp.read(5) == b"%PDF-"
    except Exception:
        return False


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


def _clean_pdf_text(text: str) -> str:
    text = text or ""
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", " ")
    text = text.replace("\ufffd", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _extract_vara_from_conteudo(txt: str) -> Optional[str]:
    txt = _clean_pdf_text(txt)

    patterns = [
        r"Conteúdo:\s*Processo:\s*[0-9\.\-]+\s+(.+?)\s+(?:CUMPRIMENTO|PROCEDIMENTO|RECURSO|EXECUÇÃO|EXECUCAO|MANDADO|AÇÃO|ACAO|INTIMAÇÃO|INTIMACAO)\b",
        r"Conteúdo:\s*Processo:\s*[0-9]+\s+(.+?)\s+(?:CUMPRIMENTO|PROCEDIMENTO|RECURSO|EXECUÇÃO|EXECUCAO|MANDADO|AÇÃO|ACAO|INTIMAÇÃO|INTIMACAO)\b",
        r"Processo:\s*[0-9]+\s+(.+?)\s+(?:CUMPRIMENTO|PROCEDIMENTO|RECURSO|EXECUÇÃO|EXECUCAO|MANDADO|AÇÃO|ACAO|INTIMAÇÃO|INTIMACAO)\b",
    ]

    for pat in patterns:
        m = re.search(pat, txt, flags=re.IGNORECASE | re.DOTALL)

        if m:
            vara = re.sub(r"\s+", " ", m.group(1)).strip(" -:\n\r\t")
            if vara and "vara não informada" not in vara.lower():
                return vara

    return None


def _extract_cliente_from_pdf_block(txt: str) -> Optional[str]:
    txt = _clean_pdf_text(txt)

    patterns = [
        r"POLO ATIVO:\s*(.+?)\s+ADVOGADO:",
        r"PARTE:\s*(.+?)\s*-\s*POLO ATIVO",
        r"PARTE:\s*(.+?)\s*-\s*POLO PASSIVO",
        r"PARTE:\s*(.+?)\s+ADVOGADO:",
        r"POLO PASSIVO:\s*(.+?)\s+ADVOGADO:",
    ]

    for pat in patterns:
        m = re.search(pat, txt, flags=re.IGNORECASE | re.DOTALL)

        if m:
            nome = re.sub(r"\s+", " ", m.group(1)).strip(" -:\n\r\t")
            if nome:
                return nome

    return None


def _extract_numero_processo_from_pdf_block(txt: str) -> Optional[str]:
    txt = _clean_pdf_text(txt)

    patterns = [
        r"N[º°]?\s*do\s*processo:\s*([0-9\.-]+)",
        r"Nº do processo:\s*([0-9\.-]+)",
        r"Processo:\s*([0-9]{7}-[0-9]{2}\.[0-9]{4}\.[0-9]\.[0-9]{2}\.[0-9]{4})",
        r"PROCESSO:\s*([0-9]{7}-[0-9]{2}\.[0-9]{4}\.[0-9]\.[0-9]{2}\.[0-9]{4})",
    ]

    for pat in patterns:
        m = re.search(pat, txt, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()

    m = re.search(r"\b([0-9]{20})\b", txt)

    if m:
        digits = m.group(1)
        return f"{digits[0:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13]}.{digits[14:16]}.{digits[16:20]}"

    return None


def _extract_vara_from_pdf_block(txt: str) -> Optional[str]:
    txt = _clean_pdf_text(txt)

    patterns = [
        r"Vara:\s*(.+?)\s+Cidade:",
        r"Vara:\s*(.+?)\s+Termo de pesquisa:",
        r"Vara:\s*(.+?)\s+Conteúdo:",
        r"Vara:\s*(.+)",
    ]

    for pat in patterns:
        m = re.search(pat, txt, flags=re.IGNORECASE | re.DOTALL)

        if m:
            vara = re.sub(r"\s+", " ", m.group(1)).strip(" -:\n\r\t")
            if vara and "vara não informada" not in vara.lower():
                return vara

    vara_conteudo = _extract_vara_from_conteudo(txt)

    if vara_conteudo:
        return vara_conteudo

    return None


def _extract_diario_from_pdf_block(txt: str) -> Optional[str]:
    txt = _clean_pdf_text(txt)

    patterns = [
        r"Jornal:\s*(.+?)\s+Tribunal:",
        r"Jornal:\s*(.+?)\s+Página:",
        r"Jornal:\s*(.+?)\s+Data publicação:",
        r"Jornal:\s*(.+)",
    ]

    for pat in patterns:
        m = re.search(pat, txt, flags=re.IGNORECASE | re.DOTALL)

        if m:
            diario = re.sub(r"\s+", " ", m.group(1)).strip(" -:\n\r\t")
            if diario:
                return diario

    return None


def _parse_pdf_block_to_row(txt: str) -> Optional[dict]:
    txt = _clean_pdf_text(txt)

    if not txt:
        return None

    data_disp = None
    data_pub = None

    m = re.search(r"Data Disponibilização:\s*(\d{2}/\d{2}/\d{4})", txt, flags=re.IGNORECASE)
    if m:
        data_disp = _parse_date_br(m.group(1))

    m = re.search(r"Data disponibilização:\s*(\d{2}/\d{2}/\d{4})", txt, flags=re.IGNORECASE)
    if m and not data_disp:
        data_disp = _parse_date_br(m.group(1))

    m = re.search(r"Data publicação:\s*(\d{2}/\d{2}/\d{4})", txt, flags=re.IGNORECASE)
    if m:
        data_pub = _parse_date_br(m.group(1))

    numero = _extract_numero_processo_from_pdf_block(txt)

    if not numero:
        return None

    cliente = _extract_cliente_from_pdf_block(txt)
    vara = _extract_vara_from_pdf_block(txt)
    diario = _extract_diario_from_pdf_block(txt)

    return {
        "data_disponibilizacao": data_disp,
        "data_publicacao": data_pub,
        "numero_processo": numero,
        "diario": diario,
        "cliente": cliente,
        "vara_tramitacao": vara,
    }


def _iter_pdf_blocks_from_path(path: str) -> Iterable[str]:
    if PdfReader is None:
        raise RuntimeError("Biblioteca 'pypdf' não instalada. Rode: pip install pypdf")

    reader = PdfReader(path)
    buffer = ""

    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""

        txt = _clean_pdf_text(txt)

        if not txt:
            continue

        combined = (buffer + "\n" + txt).strip() if buffer else txt
        matches = list(PDF_BLOCK_MARKER_RX.finditer(combined))

        if len(matches) >= 2:
            for i in range(len(matches) - 1):
                start = matches[i].start()
                end = matches[i + 1].start()
                bloco = combined[start:end].strip()
                if bloco:
                    yield bloco

            buffer = combined[matches[-1].start():].strip()

        elif len(matches) == 1:
            if buffer and matches[0].start() > 0:
                prefix = combined[:matches[0].start()].strip()
                if prefix and _extract_numero_processo_from_pdf_block(prefix):
                    yield prefix

            buffer = combined[matches[0].start():].strip()

        else:
            buffer = combined

            if len(buffer) > 3_000_000:
                possible = _parse_pdf_block_to_row(buffer)
                if possible:
                    yield buffer
                    buffer = ""
                else:
                    buffer = buffer[-1_000_000:]

        del txt
        del combined
        gc.collect()

    if buffer.strip():
        yield buffer.strip()

    del reader
    gc.collect()


def _iter_pdf_rows_from_path(path: str) -> Iterable[dict]:
    found = False

    for bloco in _iter_pdf_blocks_from_path(path):
        item = _parse_pdf_block_to_row(bloco)

        if item:
            found = True
            yield item

        del bloco

    if not found:
        raise ValueError("Não consegui localizar publicações válidas dentro do PDF.")


def _read_any_to_matrix_from_bytes(file_bytes: bytes, filename: str) -> Tuple[List[List[object]], Optional[date], Optional[date]]:
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
    matrix, periodo_ini, periodo_fim = _read_any_to_matrix_from_bytes(file_bytes, filename)
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
                "cliente": None,
                "vara_tramitacao": None,
            }
        )

    return rows, periodo_ini, periodo_fim


def _update_periodo_from_row(
    row: dict,
    periodo_ini: Optional[date],
    periodo_fim: Optional[date],
) -> Tuple[Optional[date], Optional[date]]:
    disp = row.get("data_disponibilizacao")
    pub = row.get("data_publicacao")

    if disp and (periodo_ini is None or disp < periodo_ini):
        periodo_ini = disp

    if pub and (periodo_fim is None or pub > periodo_fim):
        periodo_fim = pub
    elif disp and (periodo_fim is None or disp > periodo_fim):
        periodo_fim = disp

    return periodo_ini, periodo_fim


def _save_upload_to_temp(upload: UploadFile) -> Tuple[str, int]:
    suffix = f".{_ext(upload.filename)}" if _ext(upload.filename) else ""

    fd, path = tempfile.mkstemp(prefix="kj_migration_", suffix=suffix, dir="/tmp")
    total = 0

    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = upload.file.read(1024 * 1024)

                if not chunk:
                    break

                total += len(chunk)

                if total > MAX_UPLOAD_BYTES:
                    raise ValueError(f"Arquivo excede o limite técnico de {MAX_UPLOAD_MB}MB.")

                out.write(chunk)

        return path, total

    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass

        try:
            os.remove(path)
        except Exception:
            pass

        raise


def _load_non_pdf_file_bytes(path: str) -> bytes:
    size = os.path.getsize(path)

    if size > MAX_UPLOAD_BYTES:
        raise ValueError(f"Arquivo excede o limite técnico de {MAX_UPLOAD_MB}MB.")

    with open(path, "rb") as fp:
        return fp.read()


def _insert_rows_chunk(
    db: Session,
    rows_to_insert: List[MigrationRow],
) -> Tuple[int, int]:
    if not rows_to_insert:
        return 0, 0

    inserted = 0
    blocked = 0

    try:
        db.bulk_save_objects(rows_to_insert)
        db.commit()
        inserted += len(rows_to_insert)
        db.expunge_all()
        return inserted, blocked

    except IntegrityError:
        db.rollback()

        for row in rows_to_insert:
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


def _process_parsed_rows_into_migration_rows(
    db: Session,
    office_id: int,
    batch_id: int,
    parsed_rows: Iterable[dict],
    nums_hoje: set,
    seen_in_this_upload: set,
    permitir_dup_hoje: bool,
) -> Tuple[int, int, int, int, Optional[date], Optional[date]]:
    total_extraidos = 0
    total_inseridos = 0
    total_ignorados = 0
    blocked_by_db = 0
    periodo_ini = None
    periodo_fim = None

    buffer_insert = []

    for r in parsed_rows:
        total_extraidos += 1

        periodo_ini, periodo_fim = _update_periodo_from_row(r, periodo_ini, periodo_fim)

        num = (r.get("numero_processo") or "").strip()

        if not num:
            total_ignorados += 1
            continue

        if num in seen_in_this_upload:
            total_ignorados += 1
            continue

        seen_in_this_upload.add(num)

        if (num in nums_hoje) and (not permitir_dup_hoje):
            total_ignorados += 1
            continue

        row = MigrationRow(
            office_id=office_id,
            batch_id=batch_id,
            data_disponibilizacao=r.get("data_disponibilizacao"),
            data_publicacao=r.get("data_publicacao"),
            numero_processo=num,
            diario=r.get("diario"),
        )

        _safe_set(row, "cliente", (r.get("cliente") or "").strip() or None)
        _safe_set(row, "vara_tramitacao", (r.get("vara_tramitacao") or "").strip() or None)

        buffer_insert.append(row)

        if len(buffer_insert) >= INSERT_CHUNK_SIZE:
            inserted, blocked = _insert_rows_chunk(db, buffer_insert)
            total_inseridos += inserted
            blocked_by_db += blocked
            total_ignorados += blocked
            buffer_insert.clear()
            gc.collect()

    if buffer_insert:
        inserted, blocked = _insert_rows_chunk(db, buffer_insert)
        total_inseridos += inserted
        blocked_by_db += blocked
        total_ignorados += blocked
        buffer_insert.clear()
        gc.collect()

    return (
        total_extraidos,
        total_inseridos,
        total_ignorados,
        blocked_by_db,
        periodo_ini,
        periodo_fim,
    )


@router.get("/migracoes", response_class=HTMLResponse)
def migracoes_view(request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)

    last_batch = (
        db.query(MigrationBatch)
        .filter(MigrationBatch.office_id == office_id)
        .order_by(MigrationBatch.id.desc())
        .first()
    )

    pendentes = (
        db.query(MigrationRow)
        .filter(
            MigrationRow.office_id == office_id,
            MigrationRow.enviado_em.is_(None),
        )
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


@router.post("/migracoes/upload")
async def migracoes_upload(
    request: Request,
    files: List[UploadFile] = File(...),
    dup_hoje: str = Form("nao"),
    db: Session = Depends(get_db),
):
    office_id = _get_office_id(request)
    permitir_dup_hoje = (dup_hoje or "").strip().lower() == "sim"

    batch = MigrationBatch(
        office_id=office_id,
        criado_em=now_br(),
    )

    _safe_set(batch, "status", "PROCESSANDO")
    _safe_set(batch, "arquivo_nome", ", ".join([(f.filename or "") for f in files])[:255])
    _safe_set(batch, "total_extraidos", 0)
    _safe_set(batch, "total_inseridos", 0)
    _safe_set(batch, "total_ignorados", 0)

    db.add(batch)
    db.commit()
    db.refresh(batch)

    batch_id = batch.id

    periodo_ini_final = None
    periodo_fim_final = None

    total_extraidos_final = 0
    total_inseridos_final = 0
    total_ignorados_final = 0
    blocked_by_db_total = 0

    seen_in_this_upload = set()

    hoje = now_br().date()

    nums_hoje = set(
        x[0]
        for x in (
            db.query(MigrationRow.numero_processo)
            .join(MigrationBatch, MigrationBatch.id == MigrationRow.batch_id)
            .filter(
                MigrationBatch.office_id == office_id,
                func.date(MigrationBatch.criado_em) == hoje,
            )
            .all()
        )
        if x and x[0]
    )

    temp_paths = []

    try:
        for f in files:
            filename = f.filename or "arquivo"
            ext = _ext(filename)

            if ext not in {"xls", "xlsx", "xlsm", "csv", "txt", "html", "htm", "pdf"}:
                raise ValueError(
                    f"Arquivo '{filename}' não suportado. Envie .XLS/.XLSX/.XLSM/.PDF "
                    f"(ou exportações texto/HTML)."
                )

            temp_path, total_bytes = _save_upload_to_temp(f)
            temp_paths.append(temp_path)

            if not total_bytes:
                continue

            content = None
            parsed_rows = None

            if _is_pdf_by_path(temp_path, filename):
                parsed_iter = _iter_pdf_rows_from_path(temp_path)
            else:
                content = _load_non_pdf_file_bytes(temp_path)
                parsed_rows, p_ini, p_fim = parse_planilha_bytes(content, filename)

                if p_ini and (periodo_ini_final is None or p_ini < periodo_ini_final):
                    periodo_ini_final = p_ini

                if p_fim and (periodo_fim_final is None or p_fim > periodo_fim_final):
                    periodo_fim_final = p_fim

                parsed_iter = iter(parsed_rows)

            (
                total_extraidos,
                total_inseridos,
                total_ignorados,
                blocked_by_db,
                p_ini2,
                p_fim2,
            ) = _process_parsed_rows_into_migration_rows(
                db=db,
                office_id=office_id,
                batch_id=batch_id,
                parsed_rows=parsed_iter,
                nums_hoje=nums_hoje,
                seen_in_this_upload=seen_in_this_upload,
                permitir_dup_hoje=permitir_dup_hoje,
            )

            total_extraidos_final += total_extraidos
            total_inseridos_final += total_inseridos
            total_ignorados_final += total_ignorados
            blocked_by_db_total += blocked_by_db

            if p_ini2 and (periodo_ini_final is None or p_ini2 < periodo_ini_final):
                periodo_ini_final = p_ini2

            if p_fim2 and (periodo_fim_final is None or p_fim2 > periodo_fim_final):
                periodo_fim_final = p_fim2

            try:
                del parsed_iter
            except Exception:
                pass

            try:
                del content
            except Exception:
                pass

            try:
                del parsed_rows
            except Exception:
                pass

            gc.collect()

        batch = db.query(MigrationBatch).filter(MigrationBatch.id == batch_id).first()

        if not batch:
            raise ValueError("Lote de migração não encontrado após processamento.")

        batch.periodo_inicio = periodo_ini_final
        batch.periodo_fim = periodo_fim_final

        _set_batch_status(
            db=db,
            batch=batch,
            status="CONCLUIDO",
            total_extraidos=total_extraidos_final,
            total_inseridos=total_inseridos_final,
            total_ignorados=total_ignorados_final,
            processado=True,
        )

    except Exception as e:
        db.rollback()

        try:
            batch = db.query(MigrationBatch).filter(MigrationBatch.id == batch_id).first()
            if batch:
                _set_batch_status(
                    db=db,
                    batch=batch,
                    status="ERRO",
                    erro=str(e),
                    total_extraidos=total_extraidos_final,
                    total_inseridos=total_inseridos_final,
                    total_ignorados=total_ignorados_final,
                    processado=True,
                )
        except Exception:
            db.rollback()

        return _redirect_msg(f"Falha na migração. Motivo: {str(e)}")

    finally:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass

        gc.collect()

    if total_inseridos_final <= 0 and total_extraidos_final > 0:
        return _redirect_msg(
            f"Migração concluída, mas nenhum novo item foi inserido. "
            f"Extraídos: {total_extraidos_final}. Ignorados: {total_ignorados_final}."
        )

    if blocked_by_db_total > 0:
        return _redirect_msg(
            f"Migração concluída. Inseridos: {total_inseridos_final}. "
            f"Ignorados: {total_ignorados_final}. "
            f"Bloqueados por duplicidade no banco: {blocked_by_db_total}."
        )

    return _redirect_msg(
        f"Migração concluída. Extraídos: {total_extraidos_final}. "
        f"Inseridos: {total_inseridos_final}. Ignorados: {total_ignorados_final}."
    )


def _migrar_row_para_process_item(
    db: Session,
    office_id: int,
    row: MigrationRow,
    cliente: str,
    vara: str,
    obs: str,
    rompe_em: int,
    dest: str,
):
    aba_code = _normalize_status(dest)

    parte_autora = _default_parte_autora(cliente)
    vara_value = _default_vara(vara)

    djen = row.data_publicacao or row.data_disponibilizacao or now_br().date()

    try:
        prazo_int = int(rompe_em or 0)
    except Exception:
        prazo_int = 0

    venc = add_business_days(djen, prazo_int) if prazo_int > 0 else None

    existing = _find_existing_process_item(db, office_id, row.numero_processo)

    if existing:
        _safe_set(existing, "office_id", office_id)
        _safe_set(existing, "aba", aba_code)
        _safe_set(existing, "parte_autora", parte_autora)
        _safe_set(existing, "vara", vara_value)
        _safe_set(existing, "vara_tramitacao", vara_value)
        _safe_set(existing, "cliente", (cliente or "").strip() or getattr(existing, "cliente", None))
        _safe_set(existing, "data_intimacao", djen)
        _safe_set(existing, "prazo_dias", prazo_int if prazo_int > 0 else getattr(existing, "prazo_dias", None))
        _safe_set(existing, "vencimento", venc)

        if (obs or "").strip():
            old = (getattr(existing, "obs", None) or getattr(existing, "observacao", None) or "").strip()
            nova = (obs or "").strip()
            tag = f"[MIGRAÇÃO {now_br().date().strftime('%d/%m/%Y')}]"
            merged = (old + ("\n" if old else "") + f"{tag} {nova}").strip()
            _set_obs_compat(existing, merged)

        if aba_code == "PRAZOS" and hasattr(existing, "cumprimento"):
            _safe_set(existing, "cumprimento", "PENDENTE")

        _safe_set(existing, "atualizado_em", now_br())
        db.add(existing)
        db.flush()

    else:
        item = ProcessItem()
        _safe_set(item, "office_id", office_id)

        if not _set_process_number(item, row.numero_processo):
            raise HTTPException(status_code=500, detail="ProcessItem não possui campo para número do processo.")

        _safe_set(item, "aba", aba_code)
        _safe_set(item, "parte_autora", parte_autora)
        _safe_set(item, "vara", vara_value)
        _safe_set(item, "vara_tramitacao", vara_value)
        _safe_set(item, "cliente", (cliente or "").strip() or None)
        _safe_set(item, "data_intimacao", djen)
        _safe_set(item, "prazo_dias", prazo_int if prazo_int > 0 else None)
        _safe_set(item, "vencimento", venc)

        _set_obs_compat(item, (obs or "").strip())

        if aba_code == "PRAZOS" and hasattr(item, "cumprimento"):
            _safe_set(item, "cumprimento", "PENDENTE")

        _safe_set(item, "criado_em", now_br())
        _safe_set(item, "atualizado_em", now_br())

        db.add(item)

        try:
            db.flush()
        except IntegrityError as e:
            db.rollback()

            existing2 = _find_existing_process_item(db, office_id, row.numero_processo)

            if existing2:
                _safe_set(existing2, "office_id", office_id)
                _safe_set(existing2, "aba", aba_code)
                _safe_set(existing2, "parte_autora", parte_autora)
                _safe_set(existing2, "vara", vara_value)
                _safe_set(existing2, "data_intimacao", djen)
                _safe_set(existing2, "prazo_dias", prazo_int if prazo_int > 0 else getattr(existing2, "prazo_dias", None))
                _safe_set(existing2, "vencimento", venc)

                if (obs or "").strip():
                    old = (getattr(existing2, "obs", None) or getattr(existing2, "observacao", None) or "").strip()
                    nova = (obs or "").strip()
                    tag = f"[MIGRAÇÃO {now_br().date().strftime('%d/%m/%Y')}]"
                    merged = (old + ("\n" if old else "") + f"{tag} {nova}").strip()
                    _set_obs_compat(existing2, merged)

                if aba_code == "PRAZOS" and hasattr(existing2, "cumprimento"):
                    _safe_set(existing2, "cumprimento", "PENDENTE")

                _safe_set(existing2, "atualizado_em", now_br())
                db.add(existing2)
                db.flush()
            else:
                detail = str(e.orig) if getattr(e, "orig", None) else str(e)
                raise HTTPException(status_code=409, detail=f"Falha ao salvar por constraint/duplicidade: {detail}")

    row.cliente = cliente
    row.vara_tramitacao = vara
    row.observacao = obs
    row.rompe_em_dias = prazo_int if str(rompe_em or "").strip() else None
    row.enviar_para = aba_code
    row.enviado_em = now_br()
    row.enviado_para_status = aba_code
    db.add(row)


@router.post("/migracoes/salvar/{row_id}")
def migracoes_salvar_individual(
    request: Request,
    row_id: int,
    cliente: str = Form(""),
    vara_tramitacao: str = Form(""),
    observacao: str = Form(""),
    rompe_em: int = Form(0),
    enviar_para: str = Form("PRAZOS"),
    db: Session = Depends(get_db),
):
    office_id = _get_office_id(request)

    row = (
        db.query(MigrationRow)
        .filter(
            MigrationRow.id == row_id,
            MigrationRow.office_id == office_id,
        )
        .first()
    )

    if not row:
        return _redirect_msg("Item não encontrado.")

    if row.enviado_em is not None:
        return _redirect_msg("Este item já foi migrado.")

    try:
        _migrar_row_para_process_item(
            db,
            office_id,
            row,
            cliente,
            vara_tramitacao,
            observacao,
            rompe_em,
            enviar_para,
        )
        db.commit()
    except HTTPException as e:
        db.rollback()
        return _redirect_msg(e.detail)
    except Exception as e:
        db.rollback()
        return _redirect_msg(f"Erro ao migrar: {str(e)}")

    return _redirect_msg("Item migrado com sucesso.")


@router.post("/migracoes/salvar-lote")
async def migracoes_salvar_lote(
    request: Request,
    selected_ids: List[int] = Form([]),
    db: Session = Depends(get_db),
):
    office_id = _get_office_id(request)

    if not selected_ids:
        return _redirect_msg("Nenhum item selecionado.")

    rows = (
        db.query(MigrationRow)
        .filter(
            MigrationRow.office_id == office_id,
            MigrationRow.id.in_(selected_ids),
            MigrationRow.enviado_em.is_(None),
        )
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
            _migrar_row_para_process_item(db, office_id, row, cliente, vara, obs, rompe_int, dest)
            db.commit()
            ok += 1
        except Exception:
            db.rollback()
            fail += 1

    gc.collect()

    return _redirect_msg(f"Migração concluída. Sucesso: {ok}. Falhas: {fail}.")


@router.post("/migracoes/pendente/{row_id}/excluir")
def migracoes_excluir_pendente(
    request: Request,
    row_id: int,
    db: Session = Depends(get_db),
):
    office_id = _get_office_id(request)

    row = (
        db.query(MigrationRow)
        .filter(
            MigrationRow.id == row_id,
            MigrationRow.office_id == office_id,
        )
        .first()
    )

    if not row:
        return _redirect_msg("Item não encontrado.")

    if row.enviado_em is not None:
        return _redirect_msg("Não é possível excluir: item já foi migrado.")

    db.delete(row)
    db.commit()

    return _redirect_msg("Item excluído.")


@router.post("/migracoes/pendente/excluir-lote")
def migracoes_excluir_lote(
    request: Request,
    ids: str = Form(""),
    db: Session = Depends(get_db),
):
    office_id = _get_office_id(request)

    ids = (ids or "").strip()

    if not ids:
        return _redirect_msg("Nenhum item selecionado para excluir.")

    try:
        id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    except Exception:
        id_list = []

    if not id_list:
        return _redirect_msg("IDs inválidos.")

    rows = (
        db.query(MigrationRow)
        .filter(
            MigrationRow.office_id == office_id,
            MigrationRow.id.in_(id_list),
            MigrationRow.enviado_em.is_(None),
        )
        .all()
    )

    for r in rows:
        db.delete(r)

    db.commit()
    gc.collect()

    return _redirect_msg("Itens excluídos.")