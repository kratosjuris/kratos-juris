# app/core/permission_seed.py
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.permission import Permission

KRATOS_PERMISSIONS: list[tuple[str, str, str]] = [
    # =========================
    # Dashboard
    # =========================
    ("dashboard", "Visualizar dashboard", "dashboard.view"),

    # =========================
    # Usuários
    # =========================
    ("usuarios", "Visualizar usuários", "usuarios.view"),
    ("usuarios", "Criar usuários", "usuarios.create"),
    ("usuarios", "Editar usuários", "usuarios.edit"),
    ("usuarios", "Inativar usuários", "usuarios.delete"),
    ("usuarios", "Gerenciar permissões", "usuarios.permissions"),
    ("usuarios", "Redefinir senha", "usuarios.reset_password"),

    # =========================
    # Clientes
    # =========================
    ("clientes", "Visualizar clientes", "clientes.view"),
    ("clientes", "Criar clientes", "clientes.create"),
    ("clientes", "Editar clientes", "clientes.edit"),
    ("clientes", "Excluir clientes", "clientes.delete"),
    ("clientes", "Exportar clientes", "clientes.export"),

    # =========================
    # Processos
    # =========================
    ("processos", "Visualizar processos", "processos.view"),
    ("processos", "Criar processos", "processos.create"),
    ("processos", "Editar processos", "processos.edit"),
    ("processos", "Excluir processos", "processos.delete"),
    ("processos", "Exportar processos", "processos.export"),

    # =========================
    # Audiências
    # =========================
    ("audiencias", "Visualizar audiências", "audiencias.view"),
    ("audiencias", "Criar audiências", "audiencias.create"),
    ("audiencias", "Editar audiências", "audiencias.edit"),
    ("audiencias", "Excluir audiências", "audiencias.delete"),
    ("audiencias", "Importar audiências", "audiencias.import"),
    ("audiencias", "Gerar orientações PDF", "audiencias.pdf"),
    ("audiencias", "Enviar WhatsApp de audiência", "audiencias.whatsapp"),

    # =========================
    # Prazos / Migrações
    # =========================
    ("migracoes", "Visualizar migrações", "migracoes.view"),
    ("migracoes", "Criar migrações", "migracoes.create"),
    ("migracoes", "Editar migrações", "migracoes.edit"),
    ("migracoes", "Excluir migrações", "migracoes.delete"),
    ("migracoes", "Importar planilhas", "migracoes.import"),
    ("migracoes", "Processar migrações", "migracoes.process"),

    # =========================
    # Financeiro
    # =========================
    ("financeiro", "Visualizar financeiro", "financeiro.view"),
    ("financeiro", "Lançar contas a pagar", "financeiro.payables.create"),
    ("financeiro", "Editar contas a pagar", "financeiro.payables.edit"),
    ("financeiro", "Excluir contas a pagar", "financeiro.payables.delete"),
    ("financeiro", "Lançar contas a receber", "financeiro.receivables.create"),
    ("financeiro", "Editar contas a receber", "financeiro.receivables.edit"),
    ("financeiro", "Excluir contas a receber", "financeiro.receivables.delete"),
    ("financeiro", "Relatórios financeiros", "financeiro.reports"),
    ("financeiro", "Exportar financeiro", "financeiro.export"),

    # =========================
    # Perícias / Diligências
    # =========================
    ("pericias", "Visualizar perícias e diligências", "pericias.view"),
    ("pericias", "Criar perícias e diligências", "pericias.create"),
    ("pericias", "Editar perícias e diligências", "pericias.edit"),
    ("pericias", "Excluir perícias e diligências", "pericias.delete"),

    # =========================
    # Aniversários
    # =========================
    ("aniversarios", "Visualizar aniversários", "aniversarios.view"),
    ("aniversarios", "Criar aniversários", "aniversarios.create"),
    ("aniversarios", "Editar aniversários", "aniversarios.edit"),
    ("aniversarios", "Excluir aniversários", "aniversarios.delete"),

    # =========================
    # Documentos / Modelos
    # =========================
    ("documentos", "Visualizar documentos e modelos", "documentos.view"),
    ("documentos", "Criar documentos e modelos", "documentos.create"),
    ("documentos", "Editar documentos e modelos", "documentos.edit"),
    ("documentos", "Excluir documentos e modelos", "documentos.delete"),
    ("documentos", "Gerar documentos", "documentos.generate"),

    # =========================
    # IA Jurídica / Assistente
    # =========================
    ("ia", "Acessar IA jurídica", "ia.view"),
    ("ia", "Gerar conteúdo com IA", "ia.generate"),
    ("ia", "Gerenciar prompts e bases", "ia.manage"),

    # =========================
    # Relatórios
    # =========================
    ("relatorios", "Visualizar relatórios", "relatorios.view"),
    ("relatorios", "Exportar relatórios", "relatorios.export"),

    # =========================
    # Auditoria / Logs
    # =========================
    ("auditoria", "Visualizar logs de auditoria", "auditoria.view"),

    # =========================
    # Configurações
    # =========================
    ("configuracoes", "Visualizar configurações", "configuracoes.view"),
    ("configuracoes", "Editar configurações", "configuracoes.edit"),
]


def seed_permissions(db: Session) -> tuple[int, int]:
    """
    Cria permissões que ainda não existirem.
    Retorna: (criadas, existentes)
    """
    created = 0
    existing = 0

    existing_codes = {
        row[0]
        for row in db.query(Permission.code).all()
    }

    for module, name, code in KRATOS_PERMISSIONS:
        if code in existing_codes:
            existing += 1
            continue

        db.add(
            Permission(
                module=module,
                name=name,
                code=code,
            )
        )
        created += 1

    if created:
        db.commit()

    return created, existing