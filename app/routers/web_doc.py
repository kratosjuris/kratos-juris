import os
import re
from io import BytesIO
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from docx import Document

from app.core.database import get_db
from app.models.client import Client

router = APIRouter()

TEMPLATES_DIR = os.path.join("app", "templates", "templates_word")

DOCS = {
    "procuracao": ("Procuracao", "procuracao.docx"),
    "procuracao-a-rogo": ("Procuracao a rogo", "procuracao_a_rogo.docx"),
    "hipossuficiencia": ("Declaracao Hipossuficiencia", "declaracao_hipossuficiencia.docx"),
    "residencia": ("Declaracao Residencia", "declaracao_residencia.docx"),
}


def _br_date(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def _safe(v) -> str:
    return (v or "").strip()


def _sanitize_filename(name: str) -> str:
    """
    Evita caracteres problemáticos no Windows e remove múltiplos espaços.
    """
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]+', "-", name)
    name = re.sub(r"\s+", " ", name)
    return name


# =========================================================
# Font helpers (Arial Narrow)
# =========================================================
def _apply_font(run, name: str = "Arial Narrow", size_pt: int | None = None) -> None:
    """
    Força fonte Arial Narrow no run (preserva bold/italic já definidos).
    size_pt: se None, não altera tamanho.
    """
    try:
        run.font.name = name
        # também seta rFonts para garantir no Word
        rpr = run._element.get_or_add_rPr()
        rfonts = rpr.get_or_add_rFonts()
        rfonts.set(qn("w:ascii"), name)
        rfonts.set(qn("w:hAnsi"), name)
        rfonts.set(qn("w:cs"), name)
        rfonts.set(qn("w:eastAsia"), name)
    except Exception:
        # se falhar por alguma razão, ao menos tenta o básico
        try:
            run.font.name = name
        except Exception:
            pass

    if size_pt is not None:
        try:
            from docx.shared import Pt
            run.font.size = Pt(size_pt)
        except Exception:
            pass


def _ensure_paragraph_font(paragraph, font_name: str = "Arial Narrow") -> None:
    """
    Aplica Arial Narrow em todos os runs existentes no parágrafo.
    """
    for r in paragraph.runs:
        _apply_font(r, font_name)


# =========================================================
# 1) REPLACE PARA PLACEHOLDERS {{...}} (texto corrido)
#    - Resolve "runs" do Word
#    - Faz {{nome}} em NEGRITO (somente o nome)
#    - Força fonte Arial Narrow em todos os runs gerados
# =========================================================
def _replace_placeholders_in_paragraph(paragraph, mapping: dict[str, str], font_name: str = "Arial Narrow") -> None:
    if not paragraph.runs:
        return

    full = "".join(run.text for run in paragraph.runs)
    if not full:
        return

    # Se não tem nenhum placeholder, só garante fonte e sai
    if "{{" not in full or "}}" not in full:
        _ensure_paragraph_font(paragraph, font_name)
        return

    nome_value = mapping.get("{{nome}}", "")

    # Marcador interno para separar o nome e aplicar negrito
    has_nome = "{{nome}}" in full
    working = full.replace("{{nome}}", "__KJ_NOME__") if has_nome else full

    # Substitui os demais placeholders normalmente
    for k, v in mapping.items():
        if k == "{{nome}}":
            continue
        if k in working:
            working = working.replace(k, v or "")

    # Se nada mudou e não tinha nome, só garante fonte e sai
    if (working == full) and (not has_nome):
        _ensure_paragraph_font(paragraph, font_name)
        return

    # Limpa os runs (vamos reescrever controlando o negrito)
    for r in paragraph.runs:
        r.text = ""

    # Se não tinha {{nome}}, só escreve tudo em um run normal
    if "__KJ_NOME__" not in working:
        paragraph.runs[0].text = working
        _apply_font(paragraph.runs[0], font_name)
        return

    # Se tinha {{nome}}, escreve: antes (normal) + nome (negrito) + depois (normal)
    before, after = working.split("__KJ_NOME__", 1)

    # Antes (normal) no primeiro run existente
    paragraph.runs[0].text = before
    _apply_font(paragraph.runs[0], font_name)

    # Nome em negrito (novo run)
    run_nome = paragraph.add_run(nome_value or "")
    run_nome.bold = True
    _apply_font(run_nome, font_name)

    # Depois (normal) (novo run)
    if after:
        run_after = paragraph.add_run(after)
        _apply_font(run_after, font_name)


def _replace_placeholders_everywhere(doc: Document, mapping: dict[str, str], font_name: str = "Arial Narrow") -> None:
    # parágrafos
    for p in doc.paragraphs:
        _replace_placeholders_in_paragraph(p, mapping, font_name)

    # tabelas
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    _replace_placeholders_in_paragraph(p, mapping, font_name)

    # header/footer
    for section in doc.sections:
        for p in section.header.paragraphs:
            _replace_placeholders_in_paragraph(p, mapping, font_name)
        for p in section.footer.paragraphs:
            _replace_placeholders_in_paragraph(p, mapping, font_name)


# =========================================================
# 2) FILL POR RÓTULO (compatibilidade com docs antigos)
#    Ex.: "Nome: ____" -> "Nome: JOÃO"
#    + Força Arial Narrow nos runs
# =========================================================
def _should_fill_label(full_text: str, label: str) -> bool:
    pos = full_text.find(label)
    if pos < 0:
        return False

    after = full_text[pos + len(label):]
    after_slice = after[:200]
    s = after_slice.strip()

    if not s:
        return True

    if re.fullmatch(r"[_\-\.\s]+", s):
        return True

    return False


def _replace_label_once(paragraph, label: str, value: str, font_name: str = "Arial Narrow") -> None:
    if not paragraph.runs:
        return

    full = "".join(run.text for run in paragraph.runs)
    if label not in full:
        # só garante fonte
        _ensure_paragraph_font(paragraph, font_name)
        return

    if not _should_fill_label(full, label):
        _ensure_paragraph_font(paragraph, font_name)
        return

    pattern = re.escape(label) + r"\s*[_\-\.\s]*"
    replacement = f"{label} {value}".rstrip() if value else label
    full_final = re.sub(pattern, replacement + " ", full, count=1).rstrip()

    paragraph.runs[0].text = full_final
    _apply_font(paragraph.runs[0], font_name)

    for r in paragraph.runs[1:]:
        r.text = ""
        _apply_font(r, font_name)


def _fill_labels_everywhere(doc: Document, mapping_labels: dict[str, str], font_name: str = "Arial Narrow") -> None:
    for p in doc.paragraphs:
        for label, value in mapping_labels.items():
            _replace_label_once(p, label, value, font_name)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for label, value in mapping_labels.items():
                        _replace_label_once(p, label, value, font_name)

    for section in doc.sections:
        for p in section.header.paragraphs:
            for label, value in mapping_labels.items():
                _replace_label_once(p, label, value, font_name)

        for p in section.footer.paragraphs:
            for label, value in mapping_labels.items():
                _replace_label_once(p, label, value, font_name)


# =========================================================
# 3) MAPPINGS
# =========================================================
def _build_mapping_placeholders(c: Client) -> dict[str, str]:
    nome = _safe(c.nome)
    cpf = _safe(c.cpf_cnpj)
    rg = _safe(getattr(c, "rg", None))
    ssp_uf = _safe(getattr(c, "ssp_uf", None))
    est_civil = _safe(getattr(c, "estado_civil", None))
    profissao = _safe(getattr(c, "profissao", None))
    endereco = _safe(c.endereco)
    telefone = _safe(c.telefone)
    email = _safe(c.email)
    nasc = _br_date(c.nascimento)

    nacionalidade = _safe(getattr(c, "nacionalidade", None))

    return {
        "{{nome}}": nome,
        "{{nacionalidade}}": nacionalidade,
        "{{estado_civil}}": est_civil,
        "{{profissao}}": profissao,
        "{{rg}}": rg,
        "{{cpf}}": cpf,
        "{{ssp_uf}}": ssp_uf,
        "{{endereco}}": endereco,
        "{{telefone}}": telefone,
        "{{email}}": email,
        "{{nascimento}}": nasc,
    }


def _build_mapping_labels(c: Client) -> dict[str, str]:
    nome = _safe(c.nome)
    cpf = _safe(c.cpf_cnpj)
    rg = _safe(getattr(c, "rg", None))
    ssp_uf = _safe(getattr(c, "ssp_uf", None))
    est_civil = _safe(getattr(c, "estado_civil", None))
    profissao = _safe(getattr(c, "profissao", None))
    endereco = _safe(c.endereco)
    telefone = _safe(c.telefone)
    email = _safe(c.email)
    nasc = _br_date(c.nascimento)

    return {
        "Nome:": nome,
        "NOME:": nome,

        "CPF:": cpf,
        "CPF/CNPJ:": cpf,

        "RG N°:": rg,
        "RG Nº:": rg,
        "RG:": rg,

        "Órgão:": ssp_uf,
        "Orgao:": ssp_uf,
        "SSP-UF:": ssp_uf,

        "Estado Civil:": est_civil,
        "ESTADO CIVIL:": est_civil,

        "Profissão:": profissao,
        "Profissao:": profissao,

        "Data Nasc.:": nasc,
        "Data de Nascimento:": nasc,

        "Endereço Residencial:": endereco,
        "Endereco Residencial:": endereco,
        "Endereço:": endereco,

        "Telefone:": telefone,

        "Endereço eletrônico:": email,
        "Endereco eletronico:": email,
        "E-mail:": email,
        "Email:": email,
    }


@router.get("/docs/{doc_key}/{client_id}")
def gerar_documento(doc_key: str, client_id: int, db: Session = Depends(get_db)):
    if doc_key not in DOCS:
        raise HTTPException(status_code=404, detail="Documento inválido")

    titulo, filename = DOCS[doc_key]
    template_path = os.path.join(TEMPLATES_DIR, filename)

    if not os.path.exists(template_path):
        raise HTTPException(status_code=500, detail=f"Template não encontrado: {template_path}")

    cliente = db.query(Client).filter(Client.id == client_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    doc = Document(template_path)

    # Fonte padrão exigida
    FONT_NAME = "Arial Narrow"

    # 1) Placeholders {{...}} (texto corrido) + NOME em NEGRITO + Arial Narrow
    _replace_placeholders_everywhere(doc, _build_mapping_placeholders(cliente), FONT_NAME)

    # 2) Compatibilidade: rótulos "Nome:" + ______ + Arial Narrow
    _fill_labels_everywhere(doc, _build_mapping_labels(cliente), FONT_NAME)

    bio = BytesIO()
    doc.save(bio)
    bio.seek(0)

    nome_arquivo = _sanitize_filename(f"{titulo} - {cliente.nome}.docx")
    headers = {"Content-Disposition": f'attachment; filename="{nome_arquivo}"'}

    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )