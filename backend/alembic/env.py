"""
Alembic environment configuration for async SQLAlchemy.

Importa automaticamente todos os models dos módulos para que
o autogenerate do Alembic detecte alterações.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.database import Base

# Importar todos os models aqui para que Alembic os detecte.
# Descomente à medida que os módulos forem implementados:
from app.organization import models as organization_models  # noqa: F401
from app.identity import models as identity_models  # noqa: F401
from app.service_desk import models as service_desk_models  # noqa: F401
from app.assets import models as assets_models  # noqa: F401
from app.movements import models as movements_models  # noqa: F401
from app.stock import models as stock_models  # noqa: F401
from app.inventory_audit import models as inventory_models  # noqa: F401
# from app.access_control import models as access_control_models  # noqa: F401
from app.attachments import models as attachments_models  # noqa: F401
from app.notifications import models as notifications_models  # noqa: F401
from app.audit import models as audit_models  # noqa: F401
from app.backup import models as backup_models  # noqa: F401
from app.sla import models as sla_models  # noqa: F401
from app.whatsapp import models as whatsapp_models  # noqa: F401
from app.core import settings_model  # noqa: F401  (tabela system_settings)


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — gera SQL sem conexão ativa."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """Executa migrações com conexão ativa."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode — com engine async."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entrypoint para migrações online."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
