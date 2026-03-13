# app/services/whatsapp.py
from __future__ import annotations

from datetime import datetime
import urllib.parse
from typing import Optional


def _only_digits(s: str | None) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _normalize_phone_br(phone: str | None) -> str | None:
    """
    Normaliza telefone para wa.me:
    - remove não-numéricos
    - adiciona DDI 55 se faltar
    """
    digits = _only_digits(phone)
    if not digits:
        return None
    if digits.startswith("55"):
        return digits
    return "55" + digits


def _safe_text(s: str | None) -> str:
    """
    Remove caracteres inválidos e garante string segura.
    Observação: isso NÃO corrige problema de encoding do arquivo/ambiente;
    apenas remove o caractere U+FFFD (�) se ele já tiver aparecido.
    """
    if s is None:
        return ""
    s = s.replace("\ufffd", "")
    s = "".join(ch for ch in s if (ch == "\n" or ch == "\t" or ord(ch) >= 32))
    return s


def _fmt_date(dt: Optional[datetime]) -> str:
    if not dt:
        return "Não informada"
    return dt.strftime("%d/%m/%Y")


def _fmt_time(dt: Optional[datetime]) -> str:
    if not dt:
        return "Não informado"
    return dt.strftime("%H:%M")


def _fmt_field(v: str | None, fallback: str = "Não informado") -> str:
    v = (v or "").strip()
    return v if v else fallback


def build_client_message(
    client_name: str,
    process_number: str,
    promovido: str,
    starts_at: Optional[datetime],
    modalidade: str,
    extension_code: Optional[str],
    public_base_url: str,
) -> str:

    nome = _fmt_field(client_name, "Cliente").upper()
    proc = _fmt_field(process_number, "Não informado")
    reu = _fmt_field(promovido, "Não informado")
    data = _fmt_date(starts_at)
    hora = _fmt_time(starts_at)
    mod = _fmt_field(modalidade, "Não informada")
    code = _fmt_field(extension_code, "Não informado")

    sep = "━━━━━━━━━━━━━━━━━━━━"

    msg = (
        f"{sep}\n"
        f"*INTIMAÇÃO PARA AUDIÊNCIA*\n"
        f"{sep}\n\n"

        f"Prezado(a) Sr.(a) *{nome}*,\n\n"

        f"O escritório *Clementino & Silva Lopes* vem, por meio desta, "
        f"INTIMÁ-LO(A) para comparecimento em audiência referente ao processo nº *{proc}*, "
        f"movido em face de *{reu}*.\n\n"

        f"*Data:* {data}\n"
        f"*Horário:* {hora}\n"
        f"*Modalidade:* {mod}\n\n"

        f"{sep}\n"
        f"*LINK DE ACESSO*\n"
        f"{sep}\n\n"

        f"*{code}*\n\n"

        f"{sep}\n"
        f"*PASSO A PASSO*\n"
        f"{sep}\n\n"

        f"1) Informe *nome e sobrenome*.\n\n"
        f"2) Não é necessário preencher e-mail.\n\n"
        f"3) Marque *“Li e Concordo com os Termos de Serviço”*.\n\n"
        f"4) Clique em *“ENTRAR NA REUNIÃO”* e aguarde o redirecionamento automático.\n\n"

        f"{sep}\n"
        f"*ORIENTAÇÕES IMPORTANTES*\n"
        f"{sep}\n\n"

        f"• Pontualidade obrigatória.\n"
        f"• Acesse com 10 minutos de antecedência.\n"
        f"• Tenha documento oficial com foto.\n"
        f"• Ausência injustificada pode gerar condenação em custas.\n\n"

        f"Dica: programe um alarme para evitar atrasos.\n\n"

        f"Em caso de impossibilidade de comparecimento, entre em contato com urgência.\n\n"

        f"Atenciosamente,\n"
        f"*Equipe Clementino & Silva Lopes – Advocacia*"
    )

    return _safe_text(msg)


def build_wa_me_link(phone: str, message: str) -> str:
    """
    Gera link completo wa.me com encoding correto (UTF-8).
    """
    normalized = _normalize_phone_br(phone) or _only_digits(phone)

    if not normalized:
        raise ValueError("Telefone inválido para WhatsApp")

    safe_message = _safe_text(message)

    # ✅ AQUI É O PONTO-CHAVE:
    # força encoding UTF-8 para o texto (inclui emojis como 📌, etc.)
    encoded_message = urllib.parse.quote(safe_message, safe="", encoding="utf-8")

    return f"https://wa.me/{normalized}?text={encoded_message}"