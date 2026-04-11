from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.whatsapp_template import WhatsAppTemplate


TIPO_LABELS: dict[str, str] = {
    "audiencia_intimacao": "Intimação de Audiência",
    "audiencia_cadastrada": "Audiência Cadastrada/Designada",
    "audiencia_lembrete": "Lembrete de Audiência",
    "aniversario_cliente": "Feliz Aniversário",

}


AVAILABLE_PLACEHOLDERS: list[str] = [
    "{{cliente_nome}}",
    "{{cliente_nome_maiusculo}}",
    "{{numero_processo}}",
    "{{promovido}}",
    "{{data_audiencia}}",
    "{{hora_audiencia}}",
    "{{modalidade}}",
    "{{codigo_acesso}}",
    "{{nome_escritorio}}",
]


def get_tipo_label(tipo: str) -> str:
    return TIPO_LABELS.get(tipo, tipo)


def list_tipo_choices() -> list[tuple[str, str]]:
    return [(k, v) for k, v in TIPO_LABELS.items()]


def _default_template_audiencia_intimacao() -> str:
    return (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*INTIMAÇÃO PARA AUDIÊNCIA*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Prezado(a) Sr.(a) *{{cliente_nome_maiusculo}}*,\n\n"
        "O escritório *{{nome_escritorio}}* vem, por meio desta, "
        "INTIMÁ-LO(A) para comparecimento em audiência referente ao processo nº "
        "*{{numero_processo}}*, movido em face de *{{promovido}}*.\n\n"
        "*Data:* {{data_audiencia}}\n"
        "*Horário:* {{hora_audiencia}}\n"
        "*Modalidade:* {{modalidade}}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*LINK / CÓDIGO DE ACESSO*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "*{{codigo_acesso}}*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*PASSO A PASSO*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "1) Informe *nome e sobrenome*.\n\n"
        "2) Não é necessário preencher e-mail.\n\n"
        "3) Marque *“Li e Concordo com os Termos de Serviço”*.\n\n"
        "4) Clique em *“ENTRAR NA REUNIÃO”* e aguarde o redirecionamento automático.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*ORIENTAÇÕES IMPORTANTES*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "• Pontualidade obrigatória.\n"
        "• Acesse com 10 minutos de antecedência.\n"
        "• Tenha documento oficial com foto.\n"
        "• Ausência injustificada pode gerar condenação em custas.\n\n"
        "Dica: programe um alarme para evitar atrasos.\n\n"
        "Em caso de impossibilidade de comparecimento, entre em contato com urgência.\n\n"
        "Atenciosamente,\n"
        "*Equipe {{nome_escritorio}}*"
    )


def _default_template_audiencia_cadastrada() -> str:
    return (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*COMUNICADO DE AUDIÊNCIA*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Prezado(a) Sr.(a) *{{cliente_nome_maiusculo}}*,\n\n"
        "Informamos que foi cadastrada/designada audiência referente ao processo nº "
        "*{{numero_processo}}*, movido em face de *{{promovido}}*.\n\n"
        "*Data:* {{data_audiencia}}\n"
        "*Horário:* {{hora_audiencia}}\n"
        "*Modalidade:* {{modalidade}}\n\n"
        "{% if codigo_acesso %}*Código de acesso:* {{codigo_acesso}}\n\n{% endif %}"
        "Caso haja necessidade, encaminharemos novas orientações oportunamente.\n\n"
        "Atenciosamente,\n"
        "*Equipe {{nome_escritorio}}*"
    )


def _default_template_audiencia_lembrete() -> str:
    return (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*LEMBRETE DE AUDIÊNCIA*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Prezado(a) Sr.(a) *{{cliente_nome_maiusculo}}*,\n\n"
        "Lembramos que a audiência do processo nº *{{numero_processo}}*, "
        "em face de *{{promovido}}*, ocorrerá em:\n\n"
        "*Data:* {{data_audiencia}}\n"
        "*Horário:* {{hora_audiencia}}\n"
        "*Modalidade:* {{modalidade}}\n\n"
        "{% if codigo_acesso %}*Código de acesso:* {{codigo_acesso}}\n\n{% endif %}"
        "Recomendamos acesso com antecedência mínima de 10 minutos.\n\n"
        "Atenciosamente,\n"
        "*Equipe {{nome_escritorio}}*"
    )
def _default_template_aniversario_cliente() -> str:
    return (
        "Olá, {{cliente_nome}}! 🎉\n\n"
        "A equipe do {{nome_escritorio}} lhe deseja um Feliz Aniversário!\n\n"
        "Que este novo ano de vida seja repleto de saúde, conquistas e tranquilidade. "
        "Reafirmamos nosso compromisso de estarmos sempre à sua disposição, "
        "lado a lado, para auxiliá-lo(a) em todas as demandas jurídicas que se fizerem necessárias.\n\n"
        "Conte sempre conosco.\n"
        "Atenciosamente,\n"
        "{{nome_escritorio}}"
    )

def get_default_template_content(tipo: str) -> str:
    if tipo == "audiencia_intimacao":
        return _default_template_audiencia_intimacao()
    if tipo == "audiencia_cadastrada":
        return _default_template_audiencia_cadastrada()
    if tipo == "audiencia_lembrete":
        return _default_template_audiencia_lembrete()
    if tipo == "aniversario_cliente":
        return _default_template_aniversario_cliente()
    return ""


def get_default_template_title(tipo: str) -> str:
    if tipo == "audiencia_intimacao":
        return "Modelo padrão - Intimação de Audiência"
    if tipo == "audiencia_cadastrada":
        return "Modelo padrão - Audiência Cadastrada"
    if tipo == "audiencia_lembrete":
        return "Modelo padrão - Lembrete de Audiência"
    if tipo == "aniversario_cliente":
        return "Modelo padrão - Feliz Aniversário"
    return f"Modelo padrão - {tipo}"

def ensure_default_whatsapp_templates(
    db: Session,
    office_id: int,
    user_id: int | None = None,
) -> None:
    tipos_padrao = [
        "audiencia_intimacao",
        "audiencia_cadastrada",
        "audiencia_lembrete",
        "aniversario_cliente",
    ]

    changed = False

    for tipo in tipos_padrao:
        existing = (
            db.query(WhatsAppTemplate)
            .filter(
                WhatsAppTemplate.office_id == office_id,
                WhatsAppTemplate.tipo == tipo,
            )
            .first()
        )

        if existing:
            continue

        tpl = WhatsAppTemplate(
            office_id=office_id,
            tipo=tipo,
            titulo=get_default_template_title(tipo),
            conteudo=get_default_template_content(tipo),
            is_active=True,
            is_default=True,
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
        )
        db.add(tpl)
        changed = True

    if changed:
        db.commit()


def get_active_template(
    db: Session,
    office_id: int,
    tipo: str,
) -> WhatsAppTemplate | None:
    return (
        db.query(WhatsAppTemplate)
        .filter(
            WhatsAppTemplate.office_id == office_id,
            WhatsAppTemplate.tipo == tipo,
            WhatsAppTemplate.is_active.is_(True),
        )
        .order_by(
            WhatsAppTemplate.is_default.desc(),
            WhatsAppTemplate.updated_at.desc(),
            WhatsAppTemplate.id.desc(),
        )
        .first()
    )


def get_template_by_id(
    db: Session,
    office_id: int,
    template_id: int,
) -> WhatsAppTemplate | None:
    return (
        db.query(WhatsAppTemplate)
        .filter(
            WhatsAppTemplate.id == template_id,
            WhatsAppTemplate.office_id == office_id,
        )
        .first()
    )


def activate_template(
    db: Session,
    office_id: int,
    template_id: int,
    user_id: int | None = None,
) -> bool:
    tpl = get_template_by_id(db, office_id, template_id)
    if not tpl:
        return False

    (
        db.query(WhatsAppTemplate)
        .filter(
            WhatsAppTemplate.office_id == office_id,
            WhatsAppTemplate.tipo == tpl.tipo,
        )
        .update(
            {
                WhatsAppTemplate.is_active: False,
                WhatsAppTemplate.updated_by_user_id: user_id,
            },
            synchronize_session=False,
        )
    )

    tpl.is_active = True
    tpl.updated_by_user_id = user_id
    db.add(tpl)
    db.commit()
    return True


def restore_template_to_default(
    db: Session,
    office_id: int,
    template_id: int,
    user_id: int | None = None,
) -> bool:
    tpl = get_template_by_id(db, office_id, template_id)
    if not tpl:
        return False

    tpl.titulo = get_default_template_title(tpl.tipo)
    tpl.conteudo = get_default_template_content(tpl.tipo)
    tpl.updated_by_user_id = user_id
    db.add(tpl)
    db.commit()
    return True


def build_context(
    *,
    client_name: str | None = None,
    process_number: str | None = None,
    promovido: str | None = None,
    data_audiencia: str | None = None,
    hora_audiencia: str | None = None,
    modalidade: str | None = None,
    codigo_acesso: str | None = None,
    nome_escritorio: str | None = None,
) -> dict[str, str]:
    cliente = (client_name or "").strip()
    return {
        "cliente_nome": cliente or "Cliente",
        "cliente_nome_maiusculo": (cliente or "Cliente").upper(),
        "numero_processo": (process_number or "").strip() or "Não informado",
        "promovido": (promovido or "").strip() or "Não informado",
        "data_audiencia": (data_audiencia or "").strip() or "Não informada",
        "hora_audiencia": (hora_audiencia or "").strip() or "Não informado",
        "modalidade": (modalidade or "").strip() or "Não informada",
        "codigo_acesso": (codigo_acesso or "").strip() or "Não informado",
        "nome_escritorio": (nome_escritorio or "").strip() or "Escritório",
    }


def _safe_text(s: str | None) -> str:
    if s is None:
        return ""
    s = s.replace("\ufffd", "")
    s = "".join(ch for ch in s if (ch == "\n" or ch == "\t" or ord(ch) >= 32))
    return s


def _render_simple_conditionals(text: str, context: dict[str, Any]) -> str:
    """
    Suporta apenas este formato:
    {% if chave %} ... {{chave}} ... {% endif %}

    Isso ajuda nos modelos padrão quando o usuário quer bloco opcional.
    """
    pattern = re.compile(r"{%\s*if\s+([a-zA-Z0-9_]+)\s*%}(.*?){%\s*endif\s*%}", re.DOTALL)

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        body = match.group(2)
        value = context.get(key)
        has_value = bool(str(value or "").strip()) and str(value).strip().lower() != "não informado"
        return body if has_value else ""

    return pattern.sub(repl, text)


def render_whatsapp_template(template_text: str, context: dict[str, Any]) -> str:
    text = template_text or ""
    text = _render_simple_conditionals(text, context)

    for key, value in context.items():
        text = text.replace(f"{{{{{key}}}}}", str(value or ""))

    return _safe_text(text).strip()