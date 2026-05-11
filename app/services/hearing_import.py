# app/services/hearing_import.py
from __future__ import annotations

import re
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from io import BytesIO
import csv
import importlib

import pdfplumber

# ✅ HTML (opcional) — se não tiver bs4 instalado, funciona via regex
try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None  # type: ignore


# =========================
# ✅ Import do parser PJe TJBA (PDF) em módulo separado
# =========================
extract_hearings_pje_tjba_from_pdf = None  # type: ignore
_PJE_TJBA_IMPORT_ERROR: str | None = None

# tenta caminhos mais comuns
for _modname in (
    "app.services.hearing_import_pje_tjba",
    "services.hearing_import_pje_tjba",
):
    try:
        _mod = importlib.import_module(_modname)
        _fn = getattr(_mod, "extract_hearings_pje_tjba_from_pdf", None)
        if callable(_fn):
            extract_hearings_pje_tjba_from_pdf = _fn  # type: ignore
            _PJE_TJBA_IMPORT_ERROR = None
            break
        _PJE_TJBA_IMPORT_ERROR = f"Função extract_hearings_pje_tjba_from_pdf não encontrada em {_modname}"
    except Exception as e:
        _PJE_TJBA_IMPORT_ERROR = f"Falha ao importar {_modname}: {type(e).__name__}: {e}"


# =========================
# Regex úteis
# =========================
CNJ_RE = re.compile(r"\b(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})\b")
CNJ_SPLIT_SUFFIX_RE = re.compile(r"\b(\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})\b")

DT_RE = re.compile(
    r"(?P<d>\d{2})/(?P<m>\d{2})/(?P<y>\d{2,4}).{0,40}?(?P<h>\d{1,2}):(?P<min>\d{2})",
    re.IGNORECASE,
)

PJE_HEAD_RE = re.compile(
    r"(?P<date>\d{2}/\d{2}/\d{2,4})\s+(?P<time>\d{1,2}:\d{2})\s+(?P<prefix>\d{7}-)",
    re.IGNORECASE,
)

CPF_RE = re.compile(r"\bCPF:\s*[\d\.\-]+", re.IGNORECASE)
CNPJ_RE = re.compile(r"\bCNPJ:\s*[\d\.\-/]+", re.IGNORECASE)

TRT5_EN_DT_RE = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"\d{1,2}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\b"
)

PJE_PARTES_RX = re.compile(
    r"(?P<autor>[\s\S]{3,800}?)\s*-\s*CPF:\s*[\d\.\-]+\s*\(\s*AUTOR(?:A)?\s*\)\s*"
    r"[\s\S]{0,80}?\bX\b[\s\S]{0,80}?"
    r"(?P<reu>[\s\S]{3,800}?)\s*-\s*CNPJ:\s*[\d\.\-/]+\s*\(\s*R?E[ÉE]U\s*\)",
    re.IGNORECASE,
)


# =========================
# Utils
# =========================
def _norm_space(s: str) -> str:
    return " ".join((s or "").replace("\xa0", " ").strip().split())


def _clean_role_suffix(s: str) -> str:
    s = _norm_space(s)
    s = re.sub(r"\(\s*Promovente\s*\)\s*$", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\(\s*Promovido\s*\)\s*$", "", s, flags=re.IGNORECASE).strip()
    return _norm_space(s)


def _parse_dt(text: str) -> Optional[datetime]:
    t = _norm_space(text)
    t = t.replace(" s ", " às ").replace("  s ", " às ").replace(" h", "")
    m = DT_RE.search(t)
    if not m:
        return None

    d = int(m.group("d"))
    mo = int(m.group("m"))
    y_raw = m.group("y")
    h = int(m.group("h"))
    mi = int(m.group("min"))

    y = (2000 + int(y_raw)) if len(y_raw) == 2 else int(y_raw)

    try:
        return datetime(y, mo, d, h, mi, 0)
    except Exception:
        return None


def _build_item(
    process_number: str,
    starts_at: datetime,
    modalidade: str = "",
    promovente: str = "",
    promovido: str = "",
    extension_code: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    promovente = _norm_space(promovente) or ""
    promovido = _norm_space(promovido) or ""
    modalidade = _norm_space(modalidade) or ""
    extension_code = _norm_space(extension_code or "") or None
    notes = _norm_space(notes or "") or None

    first_prom = ""
    if promovente:
        first_prom = promovente.split("/")[0].strip()

    return {
        "process_number": _norm_space(process_number),
        "starts_at": starts_at,
        "modalidade": modalidade or None,
        "promovente": promovente or None,
        "promovido": promovido or None,
        "client_name_guess": first_prom or promovente or None,
        "extension_code": extension_code,
        "notes": notes,
    }


# =========================
# ✅ EXTRAÇÃO (HTML Projudi)
# =========================
def _extract_from_projudi_html(html_text: str) -> List[Dict[str, Any]]:
    html_text = (html_text or "").replace("\xa0", " ")
    out: List[Dict[str, Any]] = []

    if BeautifulSoup is not None:
        soup = BeautifulSoup(html_text, "html.parser")

        trs = soup.find_all("tr")
        for tr in trs:
            a = tr.find("a")
            if not a:
                continue

            pn = _norm_space(a.get_text(" ", strip=True))
            if not pn or not CNJ_RE.search(pn):
                continue

            tds = tr.find_all("td")
            if len(tds) < 5:
                continue

            prom_list = []
            for li in tds[1].find_all("li"):
                val = _clean_role_suffix(li.get_text(" ", strip=True))
                if val:
                    prom_list.append(val)

            prov_list = []
            for li in tds[2].find_all("li"):
                val = _clean_role_suffix(li.get_text(" ", strip=True))
                if val:
                    prov_list.append(val)

            dt_txt = _norm_space(tds[3].get_text(" ", strip=True))
            dt = _parse_dt(dt_txt)
            if not dt:
                continue

            modalidade = _norm_space(tds[4].get_text(" ", strip=True))

            promovente = " / ".join(prom_list) if prom_list else ""
            promovido = " / ".join(prov_list) if prov_list else ""

            out.append(_build_item(pn, dt, modalidade=modalidade, promovente=promovente, promovido=promovido))

        return out

    tr_blocks = re.findall(r"(<tr\b[^>]*>.*?</tr>)", html_text, flags=re.IGNORECASE | re.DOTALL)
    for block in tr_blocks:
        m_pn = CNJ_RE.search(block)
        if not m_pn:
            continue
        pn = m_pn.group(1)

        tds = re.findall(r"<td\b[^>]*>(.*?)</td>", block, flags=re.IGNORECASE | re.DOTALL)
        if len(tds) < 5:
            continue

        prom_lis = re.findall(r"<li\b[^>]*>(.*?)</li>", tds[1], flags=re.IGNORECASE | re.DOTALL)
        prom_list = []
        for li in prom_lis:
            txt = re.sub(r"<[^>]+>", " ", li)
            txt = _clean_role_suffix(txt)
            if txt:
                prom_list.append(txt)

        prov_lis = re.findall(r"<li\b[^>]*>(.*?)</li>", tds[2], flags=re.IGNORECASE | re.DOTALL)
        prov_list = []
        for li in prov_lis:
            txt = re.sub(r"<[^>]+>", " ", li)
            txt = _clean_role_suffix(txt)
            if txt:
                prov_list.append(txt)

        dt_txt = _norm_space(re.sub(r"<[^>]+>", " ", tds[3]))
        dt = _parse_dt(dt_txt)
        if not dt:
            continue

        modalidade = _norm_space(re.sub(r"<[^>]+>", " ", tds[4]))

        promovente = " / ".join(prom_list) if prom_list else ""
        promovido = " / ".join(prov_list) if prov_list else ""

        out.append(_build_item(pn, dt, modalidade=modalidade, promovente=promovente, promovido=promovido))

    return out


# =========================
# ✅ EXTRAÇÃO (PDF PJe)
# =========================
def _extract_text_pdf(pdf_bytes: bytes) -> str:
    parts: List[str] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            t = t.replace("\xa0", " ").replace("\ufffd", "")
            if t.strip():
                parts.append(t)
    return "\n".join(parts).strip()


def _looks_like_tjba_pauta(text: str) -> bool:
    """
    Heurística bem segura: se for pauta TJBA, a gente FORÇA parser TJBA e impede fallback genérico.
    """
    t = (text or "").lower()
    return (
        ("pauta de audiência" in t or "pauta de audien" in t)
        and ("cpf" in t and "cnpj" in t)
        and ("tjba" in t or "tribunal de justiça do estado da bahia" in t or "tribunal de justica do estado da bahia" in t)
    )


def _extract_from_pje_tjba_pdf_via_module(pdf_bytes: bytes) -> List[Dict[str, Any]]:
    """
    ✅ TJBA via app/services/hearing_import_pje_tjba.py
    """
    if extract_hearings_pje_tjba_from_pdf is None:
        if _PJE_TJBA_IMPORT_ERROR:
            print(f"[PJeTJBA] Parser NÃO carregado: {_PJE_TJBA_IMPORT_ERROR}")
        else:
            print("[PJeTJBA] Parser NÃO carregado: motivo desconhecido (extract_hearings_pje_tjba_from_pdf=None)")
        return []

    try:
        raw_items = extract_hearings_pje_tjba_from_pdf(pdf_bytes)
    except Exception as e:
        print(f"[PJeTJBA] Erro executando parser: {type(e).__name__}: {e}")
        return []

    if not raw_items:
        print("[PJeTJBA] Parser carregado, mas retornou 0 itens.")
        return []

    out: List[Dict[str, Any]] = []
    for it in raw_items:
        if not isinstance(it, dict):
            continue

        processo = _norm_space(it.get("processo") or "")
        data_hora = _norm_space(it.get("data_hora") or "")
        promovente = _norm_space(it.get("promovente") or "")
        promovido = _norm_space(it.get("promovido") or "")
        modalidade = _norm_space(it.get("modalidade") or "")

        if not processo or not data_hora:
            continue

        dt = _parse_dt(data_hora)
        if not dt:
            print(f"[PJeTJBA] Ignorado (data/hora inválida): '{data_hora}' processo={processo}")
            continue

        # ✅ defesa: se vier promovente/promovido vazio, não cria item
        if not promovente or not promovido:
            print(f"[PJeTJBA] Ignorado (parte vazia): processo={processo} prom='{promovente}' prov='{promovido}'")
            continue

        out.append(
            _build_item(
                process_number=processo,
                starts_at=dt,
                modalidade=modalidade,
                promovente=promovente,
                promovido=promovido,
                extension_code=None,
                notes=None,
            )
        )

    uniq: Dict[Tuple[str, datetime], Dict[str, Any]] = {}
    for it in out:
        pn = str(it.get("process_number") or "")
        st = it.get("starts_at")
        if pn and isinstance(st, datetime):
            uniq[(pn, st)] = it

    final = list(uniq.values())
    print(f"[PJeTJBA] Sucesso: {len(final)} audiência(s) extraída(s).")
    return final


def _pick_tipo_audiencia_pje(block: str) -> Optional[str]:
    b = _norm_space((block or "").replace("\r", "\n").replace("\n", " "))

    m = re.search(
        r"\b(Concilia[cç][aã]o|Instru[cç][aã]o|Audi[eê]ncia\s+Una|Una|Media[cç][aã]o|Sess[aã]o|Saneamento)\b",
        b,
        re.IGNORECASE,
    )
    if not m:
        return None

    base = _norm_space(m.group(1))
    if re.search(r"\bCEJUSC\b", b, re.IGNORECASE):
        if re.search(r"\bConcilia[cç][aã]o\b", base, re.IGNORECASE):
            return "Conciliação CEJUSC"
        return f"{base} CEJUSC"

    return base


def _clean_autor_name(s: str) -> str:
    x = (s or "").replace("\xa0", " ")
    x = CPF_RE.sub("", x)
    x = _norm_space(x)
    if " - " in x:
        x = x.split(" - ")[0].strip()
    return _norm_space(x)


def _clean_reu_name(s: str) -> str:
    x = (s or "").replace("\xa0", " ")
    x = CNPJ_RE.sub("", x)
    x = _norm_space(x)
    if " - " in x:
        x = x.split(" - ")[0].strip()
    return _norm_space(x)


def _extract_autor_from_headline(line: str) -> Optional[str]:
    ln = _norm_space(line)
    m = re.search(r"\bE\s+([A-ZÀ-Ü][A-ZÀ-Ü\s]{5,200})\s*-\s*", ln)
    if m:
        return _clean_autor_name(m.group(1))
    return None


def _extract_reu_from_block(block: str) -> Optional[str]:
    b = (block or "").replace("\xa0", " ").replace("\r", "\n")

    m = re.search(
        r"(?P<name>[A-ZÀ-Ü0-9][A-ZÀ-Ü0-9\s\.\-'/]{3,200}?)\s*-\s*CNPJ:\s*[\s\S]{0,220}?\(REU\)",
        b,
        re.IGNORECASE,
    )
    if m:
        return _clean_reu_name(m.group("name"))

    m2 = re.search(r"([A-ZÀ-Ü0-9][A-ZÀ-Ü0-9\s]{5,200})\s*\(REU\)", b, re.IGNORECASE)
    if m2:
        return _clean_reu_name(m2.group(1))

    return None


def _best_name_from_chunk(chunk: str) -> str:
    c = _norm_space((chunk or "").replace("\r", "\n").replace("\n", " "))
    if not c:
        return ""

    cand_rx = re.compile(r"\b[A-ZÀ-Ü]{2,}(?:\s+[A-ZÀ-Ü]{2,}){1,8}\b")

    bad = {
        "VARA", "JUIZADO", "FEITOS", "REL", "CONS", "CIV", "CIVIL", "CÍVEL",
        "PROCEDIMENTO", "ESPECIAL", "AUDIENCIA", "AUDIÊNCIA", "SALA", "SITUACAO", "SITUAÇÃO",
        "DESIGNADA", "ORGAO", "ÓRGÃO", "JULGADOR", "CONCILIACAO", "CONCILIAÇÃO",
        "INSTRUCAO", "INSTRUÇÃO", "SESSAO", "SESSÃO", "CEJUSC", "CLASSE"
    }

    best = ""
    for m in cand_rx.finditer(c):
        s = _norm_space(m.group(0))
        up = s.upper()
        if any(b in up.split() for b in bad):
            continue
        best = s

    return best


def _extract_partes_pje_from_block(block: str) -> Tuple[str, str]:
    b = (block or "").replace("\xa0", " ").replace("\r", "\n")
    b_norm = b

    autor_matches = list(
        re.finditer(
            r"(?P<name>[A-ZÀ-Ü][A-ZÀ-Ü\s\.\-'/]{3,220}?)\s*-\s*CPF:\s*[\d\.\-]+",
            b_norm,
            flags=re.IGNORECASE,
        )
    )
    reu_matches = list(
        re.finditer(
            r"(?P<name>[A-ZÀ-Ü0-9][A-ZÀ-Ü0-9\s\.\-'/&]{3,240}?)\s*-\s*CNPJ:\s*[\d\.\-/]+",
            b_norm,
            flags=re.IGNORECASE,
        )
    )

    if autor_matches and reu_matches:
        am = autor_matches[-1]
        rm = reu_matches[-1]
        a_end = am.end()
        r_start = rm.start()

        if a_end < r_start:
            mid = b_norm[a_end:r_start]
            if re.search(r"\bX\b", mid, flags=re.IGNORECASE):
                autor = _clean_autor_name(am.group("name"))
                reu = _clean_reu_name(rm.group("name"))
                if autor or reu:
                    return (autor, reu)

    m2 = re.search(
        r"(?P<autor>[\s\S]{3,800}?)\s*\(\s*AUTOR(?:A)?\s*\)\s*[\s\S]{0,120}?\bX\b[\s\S]{0,120}?(?P<reu>[\s\S]{3,800}?)\s*\(\s*R?E[ÉE]U\s*\)",
        b_norm,
        re.IGNORECASE,
    )
    if m2:
        autor = _best_name_from_chunk(m2.group("autor")) or _clean_autor_name(m2.group("autor"))
        reu = _best_name_from_chunk(m2.group("reu")) or _clean_reu_name(m2.group("reu"))
        return (autor, reu)

    m3 = PJE_PARTES_RX.search(b_norm)
    if m3:
        autor_raw = m3.group("autor")
        reu_raw = m3.group("reu")
        return (_clean_autor_name(autor_raw), _clean_reu_name(reu_raw))

    b2 = _norm_space(b_norm.replace("\n", " "))
    parts = re.split(r"\s+\bX\b\s+", b2, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) >= 2:
        autor = _best_name_from_chunk(parts[0]) or _clean_autor_name(parts[0])
        reu = _best_name_from_chunk(parts[1]) or _clean_reu_name(parts[1])
        return (autor, reu)

    return ("", "")


def _parse_pje_pdf_text(full_text: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not full_text:
        return items

    txt = full_text.replace("\xa0", " ").replace("\r", "\n")
    WINDOW_CHARS = 2400

    for m in PJE_HEAD_RE.finditer(txt):
        date_str = m.group("date")
        time_str = m.group("time")
        prefix = m.group("prefix")

        dt = _parse_dt(f"{date_str} {time_str}")
        if not dt:
            continue

        start = m.start()
        block = txt[start:start + WINDOW_CHARS]

        msuf = CNJ_SPLIT_SUFFIX_RE.search(block)
        if msuf:
            cnj = (prefix + msuf.group(1)).replace(" ", "")
        else:
            mf = CNJ_RE.search(block)
            if not mf:
                continue
            cnj = mf.group(1)

        autor, reu = _extract_partes_pje_from_block(block)

        if not autor:
            first_line = block.splitlines()[0] if block else ""
            autor = _extract_autor_from_headline(first_line) or ""
        if not reu:
            reu = _extract_reu_from_block(block) or ""

        tipo = _pick_tipo_audiencia_pje(block) or "PJe"

        items.append(
            _build_item(
                process_number=cnj,
                starts_at=dt,
                modalidade=tipo,
                promovente=autor,
                promovido=reu,
            )
        )

    uniq: Dict[Tuple[str, datetime], Dict[str, Any]] = {}
    for it in items:
        pn = str(it.get("process_number") or "")
        st = it.get("starts_at")
        if pn and isinstance(st, datetime):
            uniq[(pn, st)] = it
    return list(uniq.values())


def _extract_from_pje_pdf(pdf_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Ordem:
    1) ✅ TJBA (via módulo separado)
    2) fallback: parser genérico (SÓ quando NÃO for TJBA pauta)
    """
    preview = _extract_text_pdf(pdf_bytes)[:7000]
    is_tjba = _looks_like_tjba_pauta(preview)

    if is_tjba:
        print("[PJeTJBA] Detectado PDF como PAUTA TJBA. Forçando parser TJBA (sem fallback genérico).")
        return _extract_from_pje_tjba_pdf_via_module(pdf_bytes)

    # caso geral
    items_tjba = _extract_from_pje_tjba_pdf_via_module(pdf_bytes)
    if items_tjba:
        return items_tjba

    text = _extract_text_pdf(pdf_bytes)
    if not text:
        return []
    return _parse_pje_pdf_text(text)


# =========================
# ✅ EXTRAÇÃO (CSV PJe - export calendário)
# =========================
def _decode_csv_bytes(b: bytes) -> str:
    try:
        return b.decode("utf-8-sig", errors="replace")
    except Exception:
        return b.decode("latin-1", errors="replace")


def _parse_time_hhmmss(t: str) -> str:
    tt = _norm_space(t)
    m = re.match(r"^(\d{1,2}:\d{2})(:\d{2})?$", tt)
    return m.group(1) if m else tt


def _parse_dt_from_csv(start_date: str, start_time: str) -> Optional[datetime]:
    d = _norm_space(start_date)
    t = _parse_time_hhmmss(start_time)
    dt = _parse_dt(f"{d} {t}")
    if dt:
        return dt
    try:
        return datetime.fromisoformat(f"{d} {t}")
    except Exception:
        return None


def _extract_tipo_and_cnj_from_subject(subject: str) -> Tuple[Optional[str], Optional[str]]:
    s = _norm_space(subject)
    if not s:
        return (None, None)

    mcnj = CNJ_RE.search(s)
    cnj = mcnj.group(1) if mcnj else None

    tipo = None
    if "–" in s:
        tipo = _norm_space(s.split("–", 1)[0])
    elif cnj:
        idx = s.find(cnj)
        if idx > 0:
            tipo = _norm_space(s[:idx].replace("-", " ").strip())

    return (tipo or None, cnj)


def _extract_from_pje_csv(csv_bytes: bytes) -> List[Dict[str, Any]]:
    text = _decode_csv_bytes(csv_bytes)
    if not text.strip():
        return []

    try:
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=";,")
        delim = dialect.delimiter
    except Exception:
        delim = ","

    reader = csv.DictReader(text.splitlines(), delimiter=delim)
    items: List[Dict[str, Any]] = []

    for row in reader:
        subj = _norm_space(row.get("Subject") or "")
        if not subj:
            continue
        if subj.lower() == "subject":
            continue

        tipo, cnj = _extract_tipo_and_cnj_from_subject(subj)
        if not cnj:
            continue

        dt = _parse_dt_from_csv(row.get("Start Date") or "", row.get("Start Time") or "")
        if not dt:
            continue

        location = _norm_space(row.get("Location") or "")
        desc = _norm_space(row.get("Description") or "")

        modalidade = tipo or "PJe"

        items.append(
            _build_item(
                process_number=cnj,
                starts_at=dt,
                modalidade=modalidade,
                promovente="",
                promovido="",
                extension_code=location or None,
                notes=desc or None,
            )
        )

    uniq: Dict[Tuple[str, datetime], Dict[str, Any]] = {}
    for it in items:
        pn = str(it.get("process_number") or "")
        st = it.get("starts_at")
        if pn and isinstance(st, datetime):
            uniq[(pn, st)] = it
    return list(uniq.values())


# =========================
# ✅ EXTRAÇÃO (TRT5 - HTML pauta usuários externos)
# =========================
def _looks_like_trt5_pauta(html_text: str) -> bool:
    h = (html_text or "").lower()
    return ("pje.trt5.jus.br" in h and "pauta-usuarios-externos" in h) or ("pje-tipo-audiencia" in h)


def _parse_trt5_datetime_from_aria(aria: str) -> Optional[datetime]:
    if not aria:
        return None
    m = TRT5_EN_DT_RE.search(aria)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(0), "%a %b %d %Y %H:%M:%S")
    except Exception:
        return None


def _extract_from_trt5_html(html_text: str) -> List[Dict[str, Any]]:
    html_text = (html_text or "").replace("\xa0", " ")
    items: List[Dict[str, Any]] = []

    if BeautifulSoup is not None:
        soup = BeautifulSoup(html_text, "html.parser")

        trs = soup.find_all("tr")
        for tr in trs:
            tr_text = tr.get_text(" ", strip=True)
            mcnj = CNJ_RE.search(tr_text)
            if not mcnj:
                continue
            cnj = mcnj.group(1)

            a = tr.find("a", class_=re.compile(r"\bprocesso\b", re.I))
            promovente = ""
            promovido = ""
            if a and a.get("aria-label"):
                al = _norm_space(a.get("aria-label", ""))
                if cnj in al:
                    tail = _norm_space(al.split(cnj, 1)[1])
                    if " x " in tail:
                        p1, p2 = tail.split(" x ", 1)
                        promovente = _norm_space(p1)
                        promovido = _norm_space(p2)
                    else:
                        promovente = _norm_space(tail)

            starts_at = None
            dt_span = tr.find(attrs={"aria-label": re.compile(r"Data e hor", re.I)})
            if dt_span and dt_span.get("aria-label"):
                starts_at = _parse_trt5_datetime_from_aria(dt_span.get("aria-label", ""))

            if not starts_at:
                mtime = re.search(r"\b\d{1,2}:\d{2}\b", tr_text)
                mdate = re.search(r"\b\d{2}/\d{2}/\d{2,4}\b", tr_text)
                if mdate and mtime:
                    starts_at = _parse_dt(f"{mdate.group(0)} {mtime.group(0)}")

            if not starts_at:
                continue

            tipo = ""
            tipo_el = tr.find("pje-tipo-audiencia")
            if tipo_el:
                tipo = _norm_space(tipo_el.get_text(" ", strip=True))

            org = ""
            org_span = tr.find(attrs={"aria-label": re.compile(r"Órgão Julgador", re.I)})
            if org_span:
                org = _norm_space(org_span.get_text(" ", strip=True))

            modalidade = tipo or "TRT5"

            items.append(
                _build_item(
                    process_number=cnj,
                    starts_at=starts_at,
                    modalidade=modalidade,
                    promovente=promovente,
                    promovido=promovido,
                    extension_code=org or None,
                )
            )

        uniq: Dict[Tuple[str, datetime], Dict[str, Any]] = {}
        for it in items:
            uniq[(it["process_number"], it["starts_at"])] = it
        return list(uniq.values())

    for m in re.finditer(r'aria-label="Abrir processo\s+([^"]+)"', html_text, flags=re.IGNORECASE):
        blob = _norm_space(m.group(1))
        mcnj = CNJ_RE.search(blob)
        if not mcnj:
            continue
        cnj = mcnj.group(1)

        tail = _norm_space(blob.split(cnj, 1)[1]) if cnj in blob else ""
        promovente = ""
        promovido = ""
        if " x " in tail:
            p1, p2 = tail.split(" x ", 1)
            promovente = _norm_space(p1)
            promovido = _norm_space(p2)
        else:
            promovente = _norm_space(tail)

        start = m.start()
        window = html_text[start:start + 6000]
        mdt = re.search(r'aria-label="Data e horário:[^"]*"', window, flags=re.IGNORECASE)
        starts_at = None
        if mdt:
            aria = mdt.group(0)
            starts_at = _parse_trt5_datetime_from_aria(aria)

        if not starts_at:
            continue

        tipo = ""
        mtipo = re.search(r'class="texto-azul">\s*([^<]{1,120})\s*<', window, flags=re.IGNORECASE)
        if mtipo:
            tipo = _norm_space(mtipo.group(1))

        modalidade = tipo or "TRT5"

        items.append(
            _build_item(
                process_number=cnj,
                starts_at=starts_at,
                modalidade=modalidade,
                promovente=promovente,
                promovido=promovido,
            )
        )

    uniq2: Dict[Tuple[str, datetime], Dict[str, Any]] = {}
    for it in items:
        uniq2[(it["process_number"], it["starts_at"])] = it
    return list(uniq2.values())


# =========================
# ✅ API PRINCIPAL
# =========================
def extract_hearings_from_file(file_bytes: bytes, filename: str | None = None) -> List[Dict[str, Any]]:
    """
    Extrai audiências de:
    - HTML do Projudi (ZIP)
    - HTML do TRT5 (ZIP "Minhas Audiências - PJE.html")
    - PDF do PJe (✅ TJBA via módulo separado)
    - CSV do PJe (export calendário)
    """
    name = (filename or "").lower().strip()

    if name.endswith(".pdf") or (file_bytes[:4] == b"%PDF"):
        return _extract_from_pje_pdf(file_bytes)

    if name.endswith(".csv"):
        return _extract_from_pje_csv(file_bytes)

    if name.endswith(".html") or name.endswith(".htm") or (b"<html" in (file_bytes or b"")[:800].lower()):
        try:
            text = file_bytes.decode("utf-8", errors="ignore")
        except Exception:
            text = file_bytes.decode("latin-1", errors="ignore")

        items = _extract_from_projudi_html(text)
        if items:
            return items

        if _looks_like_trt5_pauta(text):
            return _extract_from_trt5_html(text)

        return []

    return []


def extract_hearings_from_archive(archive_bytes: bytes, filename: str | None = None) -> List[Dict[str, Any]]:
    """
    Extrai audiências de ZIP:
    - Projudi (HTML)
    - TRT5 (HTML salvo da pauta)
    - e também PDF/CSV se existirem no ZIP.
    """
    name = (filename or "").lower().strip()
    out: List[Dict[str, Any]] = []

    if name.endswith(".zip") or archive_bytes[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(_BytesIO(archive_bytes)) as zf:
            for member in zf.namelist():
                mlow = member.lower()
                if not (mlow.endswith(".html") or mlow.endswith(".htm") or mlow.endswith(".pdf") or mlow.endswith(".csv")):
                    continue
                try:
                    b = zf.read(member)
                except Exception:
                    continue
                items = extract_hearings_from_file(b, member)
                if items:
                    out.extend(items)
        return out

    return out


# =========================
# ✅ util interno
# =========================
class _BytesIO:
    def __init__(self, data: bytes):
        self._bio = BytesIO(data)

    def __getattr__(self, name: str):
        return getattr(self._bio, name)