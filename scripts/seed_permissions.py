# app/scripts/seed_permissions.py
from __future__ import annotations

from app.core.database import SessionLocal
from app.models.permission import Permission

PERMISSIONS = [
    ("dashboard.view", "Visualizar dashboard", "dashboard"),
    ("clientes.view", "Visualizar clientes", "clientes"),
    ("clientes.create", "Cadastrar clientes", "clientes"),
    ("clientes.edit", "Editar clientes", "clientes"),
    ("clientes.delete", "Excluir clientes", "clientes"),

    ("processos.view", "Visualizar processos", "processos"),
    ("processos.create", "Cadastrar processos", "processos"),
    ("processos.edit", "Editar processos", "processos"),
    ("processos.delete", "Excluir processos", "processos"),

    ("audiencias.view", "Visualizar audiências", "audiencias"),
    ("audiencias.create", "Cadastrar audiências", "audiencias"),
    ("audiencias.edit", "Editar audiências", "audiencias"),
    ("audiencias.delete", "Excluir audiências", "audiencias"),
    ("audiencias.import", "Importar audiências", "audiencias"),
    ("audiencias.whatsapp", "Enviar WhatsApp de audiências", "audiencias"),
    ("audiencias.pdf", "Gerar PDF de orientações", "audiencias"),

    ("migracoes.view", "Visualizar migrações", "migracoes"),
    ("migracoes.create", "Cadastrar migrações", "migracoes"),
    ("migracoes.edit", "Editar migrações", "migracoes"),
    ("migracoes.delete", "Excluir migrações", "migracoes"),
    ("migracoes.import", "Importar migrações", "migracoes"),

    ("financeiro.view", "Visualizar financeiro", "financeiro"),
    ("financeiro.create", "Cadastrar financeiro", "financeiro"),
    ("financeiro.edit", "Editar financeiro", "financeiro"),
    ("financeiro.delete", "Excluir financeiro", "financeiro"),
    ("financeiro.relatorios", "Visualizar relatórios financeiros", "financeiro"),
    ("financeiro.export", "Exportar financeiro", "financeiro"),

    ("relatorios.view", "Visualizar relatórios", "relatorios"),
    ("relatorios.export_pdf", "Exportar relatórios em PDF", "relatorios"),
    ("relatorios.export_excel", "Exportar relatórios em Excel", "relatorios"),

    ("usuarios.view", "Visualizar usuários", "usuarios"),
    ("usuarios.create", "Cadastrar usuários", "usuarios"),
    ("usuarios.edit", "Editar usuários", "usuarios"),
    ("usuarios.delete", "Inativar usuários", "usuarios"),
    ("usuarios.permissions", "Gerenciar permissões", "usuarios"),
    ("usuarios.reset_password", "Redefinir senha de usuários", "usuarios"),

    ("configuracoes.view", "Visualizar configurações", "configuracoes"),
    ("configuracoes.edit", "Editar configurações", "configuracoes"),

    ("ia.view", "Visualizar IA", "ia"),
    ("ia.use", "Utilizar IA", "ia"),
    ("ia.admin", "Administrar IA", "ia"),
]


def main():
    db = SessionLocal()
    try:
        created = 0
        for code, name, module in PERMISSIONS:
            exists = db.query(Permission).filter(Permission.code == code).first()
            if exists:
                continue
            db.add(Permission(code=code, name=name, module=module, description=name))
            created += 1
        db.commit()
        print(f"Permissões inseridas: {created}")
    finally:
        db.close()


if __name__ == "__main__":
    main()