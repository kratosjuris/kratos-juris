from __future__ import annotations

from datetime import datetime
import urllib.parse
from typing import Optional, Any

from sqlalchemy.orm import Session

from app.models.whatsapp_template import WhatsAppTemplate
from app.services.whatsapp_templates import (
    build_context,
    ensure_default_whatsapp_templates,
    get_active_template,
    render_whatsapp_template,
)


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


def build_whatsapp_context(
    client_name: str,
    process_number: str,
    promovido: str,
    starts_at: Optional[datetime],
    modalidade: str,
    extension_code: Optional[str],
    office_name: str | None = None,
) -> dict[str, str]:
    """
    Monta o contexto padrão para renderização dos modelos de WhatsApp.
    """
    return build_context(
        client_name=client_name,
        process_number=process_number,
        promovido=promovido,
        data_audiencia=_fmt_date(starts_at),
        hora_audiencia=_fmt_time(starts_at),
        modalidade=_fmt_field(modalidade, "Não informada"),
        codigo_acesso=_fmt_field(extension_code, "Não informado"),
        nome_escritorio=(office_name or "Escritório").strip(),
    )


def build_client_message_from_template_text(
    template_text: str,
    client_name: str,
    process_number: str,
    promovido: str,
    starts_at: Optional[datetime],
    modalidade: str,
    extension_code: Optional[str],
    office_name: str | None = None,
) -> str:
    """
    Renderiza uma mensagem a partir de um texto de template com placeholders.
    """
    context = build_whatsapp_context(
        client_name=client_name,
        process_number=process_number,
        promovido=promovido,
        starts_at=starts_at,
        modalidade=modalidade,
        extension_code=extension_code,
        office_name=office_name,
    )
    return render_whatsapp_template(template_text, context)


def build_client_message_from_template(
    db: Session,
    office_id: int,
    tipo: str,
    client_name: str,
    process_number: str,
    promovido: str,
    starts_at: Optional[datetime],
    modalidade: str,
    extension_code: Optional[str],
    office_name: str | None = None,
    user_id: int | None = None,
) -> str:
    """
    Busca o template ativo do escritório para o tipo informado e renderiza a mensagem.
    Caso não exista, garante os modelos padrão e tenta novamente.
    """
    ensure_default_whatsapp_templates(db, office_id=office_id, user_id=user_id)

    tpl: WhatsAppTemplate | None = get_active_template(db, office_id=office_id, tipo=tipo)

    if not tpl:
        # fallback de segurança: usa a mensagem antiga de intimação
        return build_client_message(
            client_name=client_name,
            process_number=process_number,
            promovido=promovido,
            starts_at=starts_at,
            modalidade=modalidade,
            extension_code=extension_code,
            public_base_url="",
            office_name=office_name,
        )

    return build_client_message_from_template_text(
        template_text=tpl.conteudo,
        client_name=client_name,
        process_number=process_number,
        promovido=promovido,
        starts_at=starts_at,
        modalidade=modalidade,
        extension_code=extension_code,
        office_name=office_name,
    )


def build_client_message(
    client_name: str,
    process_number: str,
    promovido: str,
    starts_at: Optional[datetime],
    modalidade: str,
    extension_code: Optional[str],
    public_base_url: str,
    office_name: str | None = None,
) -> str:
    """
    Mantido por compatibilidade com o sistema atual.
    Esse método continua funcionando mesmo se algum ponto do sistema ainda
    estiver chamando a versão antiga hardcoded.

    Observação:
    - public_base_url foi mantido na assinatura por compatibilidade
    - office_name agora pode ser informado dinamicamente
    """
    nome = _fmt_field(client_name, "Cliente").upper()
    proc = _fmt_field(process_number, "Não informado")
    reu = _fmt_field(promovido, "Não informado")
    data = _fmt_date(starts_at)
    hora = _fmt_time(starts_at)
    mod = _fmt_field(modalidade, "Não informada")
    code = _fmt_field(extension_code, "Não informado")
    escritorio = _fmt_field(office_name, "Escritório")

    sep = "━━━━━━━━━━━━━━━━━━━━"

    msg = (
        f"{sep}\n"
        f"*INTIMAÇÃO PARA AUDIÊNCIA*\n"
        f"{sep}\n\n"

        f"Prezado(a) Sr.(a) *{nome}*,\n\n"

        f"O escritório *{escritorio}* vem, por meio desta, "
        f"INTIMÁ-LO(A) para comparecimento em audiência referente ao processo nº *{proc}*, "
        f"movido em face de *{reu}*.\n\n"

        f"*Data:* {data}\n"
        f"*Horário:* {hora}\n"
        f"*Modalidade:* {mod}\n\n"

        f"{sep}\n"
        f"*LINK / CÓDIGO DE ACESSO*\n"
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
        f"*Equipe {escritorio}*"
    )

    return _safe_text(msg)


def build_message_by_tipo(
    db: Session,
    office_id: int,
    tipo: str,
    client_name: str,
    process_number: str,
    promovido: str,
    starts_at: Optional[datetime],
    modalidade: str,
    extension_code: Optional[str],
    office_name: str | None = None,
    user_id: int | None = None,
) -> str:
    """
    Helper genérico para qualquer tipo de mensagem de audiência.

    Exemplos de tipo:
    - audiencia_intimacao
    - audiencia_cadastrada
    - audiencia_lembrete
    """
    return build_client_message_from_template(
        db=db,
        office_id=office_id,
        tipo=tipo,
        client_name=client_name,
        process_number=process_number,
        promovido=promovido,
        starts_at=starts_at,
        modalidade=modalidade,
        extension_code=extension_code,
        office_name=office_name,
        user_id=user_id,
    )


def build_wa_me_link(phone: str, message: str) -> str:
    """
    Gera link completo wa.me com encoding correto (UTF-8).
    """
    normalized = _normalize_phone_br(phone) or _only_digits(phone)

    if not normalized:
        raise ValueError("Telefone inválido para WhatsApp")

    safe_message = _safe_text(message)

    encoded_message = urllib.parse.quote(safe_message, safe="", encoding="utf-8")

    return f"https://wa.me/{normalized}?text={encoded_message}"