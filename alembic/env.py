from logging.config import fileConfig
import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

# Garante que o Python encontre o pacote "app"
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Alembic Config
config = context.config

# Logging do Alembic
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Importa Base e os models (para o Alembic "enxergar" as tabelas)
from app.core.database import Base  # noqa

# ✅ Importe aqui seus models (pelo menos os que serão afetados)
from app.models.migration import MigrationBatch, MigrationRow  # noqa
from app.models.process_item import ProcessItem  # noqa
from app.models.client import Client  # noqa  (opcional, mas ok)

target_metadata = Base.metadata


def get_database_url() -> str:
    """
    Prioridade:
    1) variável de ambiente DATABASE_URL (se você define no .bat)
    2) sqlalchemy.url do alembic.ini
    """
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    return config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
