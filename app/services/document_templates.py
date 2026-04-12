import json
import os
import re
from datetime import datetime
from io import BytesIO

from docx import Document


DOC_TEMPLATE_SPECS = {
    "procuracao": {
        "title": "Procuração",
        "allowed_placeholders": [
            "{{nome}}",
            "{{nacionalidade}}",
            "{{estado_civil}}",
            "{{profissao}}",
            "{{rg}}",
            "{{cpf}}",
            "{{ssp_uf}}",
            "{{endereco}}",
            "{{telefone}}",
            "{{email}}",
            "{{nascimento}}",
        ],
    },
    "procuracao-a-rogo": {
        "title": "Procuração a rogo",
        "allowed_placeholders": [
            "{{nome}}",
            "{{nacionalidade}}",
            "{{estado_civil}}",
            "{{profissao}}",
            "{{rg}}",
            "{{cpf}}",
            "{{ssp_uf}}",
            "{{endereco}}",
            "{{telefone}}",
            "{{email}}",
            "{{nascimento}}",
        ],
    },
    "hipossuficiencia": {
        "title": "Declaração de Hipossuficiência",
        "allowed_placeholders": [
            "{{nome}}",
            "{{nacionalidade}}",
            "{{estado_civil}}",
            "{{profissao}}",
            "{{rg}}",
            "{{cpf}}",
            "{{ssp_uf}}",
            "{{endereco}}",
            "{{telefone}}",
            "{{email}}",
            "{{nascimento}}",
        ],
    },
    "residencia": {
        "title": "Declaração de Residência",
        "allowed_placeholders": [
            "{{nome}}",
            "{{nacionalidade}}",
            "{{estado_civil}}",
            "{{profissao}}",
            "{{rg}}",
            "{{cpf}}",
            "{{ssp_uf}}",
            "{{endereco}}",
            "{{telefone}}",
            "{{email}}",
            "{{nascimento}}",
        ],
    },
}


DOC_TEMPLATES_STORAGE_DIR = os.getenv(
    "DOC_TEMPLATES_STORAGE_DIR",
    os.path.join("storage", "offices"),
)

DOC_TEMPLATES_MAX_MB = int(os.getenv("DOC_TEMPLATES_MAX_MB", "5"))
DOC_TEMPLATES_MAX_BYTES = DOC_TEMPLATES_MAX_MB * 1024 * 1024

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def get_all_doc_specs() -> dict:
    return DOC_TEMPLATE_SPECS


def get_doc_spec(doc_key: str) -> dict | None:
    return DOC_TEMPLATE_SPECS.get(doc_key)


def get_doc_title(doc_key: str) -> str:
    spec = get_doc_spec(doc_key)
    return spec["title"] if spec else doc_key


def get_allowed_placeholders(doc_key: str) -> list[str]:
    spec = get_doc_spec(doc_key)
    if not spec:
        return []
    return spec["allowed_placeholders"]


def sanitize_filename(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]+', "-", name)
    name = re.sub(r"\s+", "_", name)
    return name


def ensure_storage_dir(office_id: int, doc_key: str) -> str:
    path = os.path.join(
        DOC_TEMPLATES_STORAGE_DIR,
        str(office_id),
        "doc_templates",
        doc_key,
    )
    os.makedirs(path, exist_ok=True)
    return path


def build_storage_path(
    office_id: int,
    doc_key: str,
    version: int,
    original_filename: str,
) -> str:
    base_dir = ensure_storage_dir(office_id, doc_key)
    safe_name = sanitize_filename(original_filename or f"{doc_key}.docx")
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    final_name = f"v{version}_{timestamp}_{safe_name}"
    return os.path.join(base_dir, final_name)


def write_template_bytes(file_bytes: bytes, destination_path: str) -> None:
    os.makedirs(os.path.dirname(destination_path), exist_ok=True)
    with open(destination_path, "wb") as f:
        f.write(file_bytes)


def remove_file_silently(path: str | None) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _iter_doc_texts(doc: Document):
    for p in doc.paragraphs:
        yield p.text or ""

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    yield p.text or ""

    for section in doc.sections:
        for p in section.header.paragraphs:
            yield p.text or ""
        for p in section.footer.paragraphs:
            yield p.text or ""


def normalize_placeholder_name(name: str) -> str:
    return "{{" + (name or "").strip().lower() + "}}"


def extract_placeholders_from_docx_bytes(file_bytes: bytes) -> list[str]:
    doc = Document(BytesIO(file_bytes))
    placeholders = set()

    for text in _iter_doc_texts(doc):
        for match in _PLACEHOLDER_RE.finditer(text or ""):
            placeholders.add(normalize_placeholder_name(match.group(1)))

    return sorted(placeholders)


def validate_docx_placeholders(doc_key: str, file_bytes: bytes) -> dict:
    detected = extract_placeholders_from_docx_bytes(file_bytes)
    allowed = set(get_allowed_placeholders(doc_key))

    invalid = sorted([p for p in detected if p not in allowed])

    return {
        "doc_key": doc_key,
        "detected_placeholders": detected,
        "invalid_placeholders": invalid,
        "is_valid": len(invalid) == 0,
    }


def detected_placeholders_to_json(placeholders: list[str]) -> str:
    return json.dumps(placeholders, ensure_ascii=False)