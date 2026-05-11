# app/services/hearing_import_pje_tjba.py
from __future__ import annotations

import re
from typing import List, Dict, Optional
from io import BytesIO

import pdfplumber


# =========================================================
# PJe TJBA (PDF) — parser específico para o layout do TJBA
# Extrai SOMENTE:
#   - data_hora (dd/mm/yyyy HH:MM)
#   - processo (CNJ)
#   - promovente
#   - promovido
#   - modalidade
# =========================================================

# Cabeçalho típico (tabela):
# 12/03/2026 10:40 8002315-54.2025.8.05.0265 ...
# OU ano com 2 dígitos:
# 12/03/26 10:40 8002315- ...
HEAD_RE = re.compile(
    r"\b(?P<date>\d{2}/\d{2}/\d{2,4})\s+(?P<time>\d{2}:\d{2})\s+(?P<prefix>\d{7}-)",
    re.IGNORECASE,
)

# Sufixo CNJ (sem o prefixo 0000000-)
CNJ_SUFFIX_RE = re.compile(r"\b(?P<suf>\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})\b")

# Nome antes de CPF / CNPJ (no TJBA costuma existir CPF/CNPJ no texto)
CPF_MARK_RE = re.compile(r"\bCPF:\b", re.IGNORECASE)
CNPJ_MARK_RE = re.compile(r"\bCNPJ:\b", re.IGNORECASE)

# Captura o "nome bruto" imediatamente antes de "- CPF:" / "- CNPJ:"
# (deixa bem permissivo porque às vezes vem com texto/coluna junto)
NAME_BEFORE_CPF_RE = re.compile(
    r"(?P<name>[A-ZÀ-Ü0-9][A-ZÀ-Ü0-9\s\.\-'/&]{3,260}?)\s*-\s*CPF:",
    re.IGNORECASE,
)
NAME_BEFORE_CNPJ_RE = re.compile(
    r"(?P<name>[A-ZÀ-Ü0-9][A-ZÀ-Ü0-9\s\.\-'/&]{3,260}?)\s*-\s*CNPJ:",
    re.IGNORECASE,
)

# Modalidade (no TJBA geralmente aparece como "Conciliação" etc.)
MODALIDADE_RE = re.compile(
    r"\b(Concilia[cç][aã]o|Instru[cç][aã]o|Audi[eê]ncia\s+Una|Una|Julgamento|Media[cç][aã]o|Saneamento)\b",
    re.IGNORECASE,
)

_BAD_TERMS = {
    "VARA", "JUIZADO", "FEITOS", "REL", "CONS", "CIV", "CIVIL", "CÍVEL",
    "COMERCIAIS", "UBATÃ", "UBATA", "COMARCA", "FORO", "UNIDADE",
}


def _clean_text(s: str) -> str:
    s = (s or "")
    s = s.replace("\ufffd", "")  # remove "�"
    s = s.replace("\xa0", " ")
    return s


def _norm_space(s: str) -> str:
    return " ".join((s or "").replace("\xa0", " ").strip().split())


def _normalize_date_ddmmyyyy(date_str: str) -> str:
    """
    Aceita dd/mm/yy ou dd/mm/yyyy e normaliza para dd/mm/yyyy.
    """
    d = _norm_space(date_str)
    m = re.match(r"^(\d{2})/(\d{2})/(\d{2,4})$", d)
    if not m:
        return d
    dd, mm, yy = m.group(1), m.group(2), m.group(3)
    if len(yy) == 2:
        yy = str(2000 + int(yy))
    return f"{dd}/{mm}/{yy}"


def _strip_leading_bad_terms(name: str) -> str:
    """
    No PDF do TJBA, às vezes o "nome" vem colado com termos do órgão/vara.
    A gente corta tudo até o ÚLTIMO termo ruim e fica com o restante.
    """
    n = _norm_space(name).upper()
    if not n:
        return ""

    words = n.split()
    last_bad = -1
    for i, w in enumerate(words):
        if w in _BAD_TERMS:
            last_bad = i

    if last_bad >= 0 and last_bad + 1 < len(words):
        words = words[last_bad + 1 :]

    return _norm_space(" ".join(words))


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    parts: List[str] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            txt = _clean_text(txt)
            if txt.strip():
                parts.append(txt)
    return "\n".join(parts).strip()


def _find_cnj_suffix_near(text: str, start_idx: int, max_lookahead: int = 600) -> Optional[str]:
    """
    Procura o sufixo do CNJ depois do prefixo (0000000-),
    mesmo que exista texto/linhas no meio.
    """
    window = text[start_idx : start_idx + max_lookahead]
    m = CNJ_SUFFIX_RE.search(window)
    return m.group("suf") if m else None


def _pick_modalidade(block: str) -> str:
    m = MODALIDADE_RE.search(block or "")
    if not m:
        return ""
    val = _norm_space(m.group(1))
    # normaliza alguns casos
    if re.search(r"una", val, re.IGNORECASE):
        return "Audiência Una" if "audi" not in val.lower() else val
    # mantém acentuação quando veio certo; senão, capitaliza
    return val[:1].upper() + val[1:]


def extract_hearings_pje_tjba_from_pdf(pdf_bytes: bytes) -> List[Dict[str, str]]:
    """
    Retorna List[Dict[str,str]] com:
      - data_hora (dd/mm/yyyy HH:MM)
      - processo
      - promovente
      - promovido
      - modalidade
    """
    full_text = _extract_pdf_text(pdf_bytes)
    if not full_text:
        return []

    results: List[Dict[str, str]] = []
    seen = set()

    for mh in HEAD_RE.finditer(full_text):
        date_raw = mh.group("date")
        time_raw = mh.group("time")
        prefix = mh.group("prefix")

        date_norm = _normalize_date_ddmmyyyy(date_raw)
        data_hora = f"{date_norm} {time_raw}"

        # acha sufixo do CNJ logo após o prefixo
        suf = _find_cnj_suffix_near(full_text, mh.end(), max_lookahead=900)
        if not suf:
            continue

        processo = (prefix + suf).replace(" ", "")
        # bloco de contexto para pegar partes / modalidade
        block = full_text[mh.start() : mh.start() + 2500]

        # Promovente: nome antes de CPF:
        promovente = ""
        mcpf = NAME_BEFORE_CPF_RE.search(block)
        if mcpf:
            promovente = _strip_leading_bad_terms(mcpf.group("name"))

        # Promovido: nome antes de CNPJ:
        promovido = ""
        mcnpj = NAME_BEFORE_CNPJ_RE.search(block)
        if mcnpj:
            promovido = _strip_leading_bad_terms(mcnpj.group("name"))

        modalidade = _pick_modalidade(block)

        item = {
            "data_hora": data_hora,
            "processo": processo,
            "promovente": promovente or "",
            "promovido": promovido or "",
            "modalidade": modalidade or "",
        }

        key = (item["processo"], item["data_hora"], item["promovente"], item["promovido"], item["modalidade"])
        if key in seen:
            continue
        seen.add(key)

        results.append(item)

    return results