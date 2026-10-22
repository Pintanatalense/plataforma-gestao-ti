"""
Guarda contra drift: depois de `alembic upgrade head` o banco tem que ser igual ao que os models declaram
(equivale a `alembic check`). Roda só com PostgreSQL de teste (marcador `migrations`, TEST_DATABASE_URL).
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = [pytest.mark.asyncio, pytest.mark.migrations]


async def test_database_after_upgrade_head_matches_the_models():
    url = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))

    backend = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    os.environ["DATABASE_URL"] = url

    # `command.upgrade` usa asyncio.run no env.py: precisa rodar fora do loop de eventos do teste.
    import asyncio

    await asyncio.get_running_loop().run_in_executor(None, command.upgrade, cfg, "head")

    # mesmos models que o env.py do Alembic enxerga
    import alembic.config  # noqa: F401
    from app.database import Base

    async with engine.connect() as conn:
        diffs = await conn.run_sync(lambda sync_conn: compare_metadata(MigrationContext.configure(sync_conn), Base.metadata))
    await engine.dispose()

    assert diffs == [], "Drift entre models e migrations:\n" + "\n".join(str(d) for d in diffs)
