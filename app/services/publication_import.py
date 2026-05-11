import re
import pdfplumber


def parse_publicacoes_pdf(file):
    registros = []

    with pdfplumber.open(file) as pdf:
        texto = ""
        for page in pdf.pages:
            texto += page.extract_text() + "\n"

    # separa blocos
    blocos = re.split(r"(PUBLICAÇÃO:\s*\d+|Sequencial:\s*\d+)", texto)

    buffer = ""
    for parte in blocos:
        if "PUBLICAÇÃO:" in parte or "Sequencial:" in parte:
            if buffer:
                item = _parse_bloco(buffer)
                if item:
                    registros.append(item)
            buffer = ""
        buffer += parte

    if buffer:
        item = _parse_bloco(buffer)
        if item:
            registros.append(item)

    return registros


def _parse_bloco(txt):
    try:
        data_disp = _match(txt, r"Data Disponibilização:\s*(\d{2}/\d{2}/\d{4})")
        data_pub = _match(txt, r"Data publicação:\s*(\d{2}/\d{2}/\d{4})")
        processo = _match(txt, r"Processo:\s*([\d\.-]+)")
        vara = _match(txt, r"Vara:\s*(.+)")

        # Nome cliente (2 padrões)
        cliente = (
                _match(txt, r"POLO ATIVO:\s*([A-Z\s\.]+)")
                or _match(txt, r"PARTE:\s*([A-Z\s\.]+)")
        )

        if not processo:
            return None

        return {
            "data_disponibilizacao": data_disp,
            "data_publicacao": data_pub,
            "processo": processo,
            "vara": vara.strip() if vara else None,
            "cliente": cliente.strip() if cliente else None,
        }

    except Exception:
        return None


def _match(txt, pattern):
    m = re.search(pattern, txt)
    return m.group(1).strip() if m else None