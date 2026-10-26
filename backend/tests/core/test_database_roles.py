"""Papéis de banco separados (ADR-022; Plano de Evolução, Fase 0 PR 10; S3).

Cada teste usa um banco descartável próprio (``gti_roles_<id>_test``) e papéis com sufixo aleatório no mesmo
PostgreSQL de teste; tudo é apagado no final. O banco principal dos testes não é tocado.
"""

import asyncio
import os
import uuid
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.db_roles import EVOLUTION_SCHEMA, Role, RolesConfigError, RolesSpec, apply_roles, validate
from tests._guard import assert_safe_test_url

pytestmark = [pytest.mark.asyncio, pytest.mark.migrations]

BACKEND = Path(__file__).resolve().parents[2]


class Cluster:
    """Banco e papéis descartáveis no PostgreSQL de teste."""

    def __init__(self):
        self.url = make_url(assert_safe_test_url(os.environ["TEST_DATABASE_URL"]))
        suffix = uuid.uuid4().hex[:8]
        self.database = f"gti_roles_{suffix}_test"
        assert_safe_test_url(self.url.set(database=self.database).render_as_string())
        self.spec = RolesSpec(
            database=self.database,
            owner=Role(f"t_owner_{suffix}", uuid.uuid4().hex),
            app=Role(f"t_app_{suffix}", uuid.uuid4().hex),
            evolution=Role(f"t_evo_{suffix}", uuid.uuid4().hex),
        )

    async def connect(self, role: Role | None = None, database: str | None = None) -> asyncpg.Connection:
        return await asyncpg.connect(
            host=self.url.host, port=self.url.port or 5432, database=database or self.database,
            user=role.name if role else self.url.username, password=role.password if role else self.url.password,
        )

    def sqlalchemy_url(self, role: Role | None = None) -> str:
        url = self.url.set(database=self.database)
        if role:
            url = url.set(username=role.name, password=role.password)
        return url.render_as_string(hide_password=False)

    async def create(self) -> None:
        admin = await self.connect(database=self.url.database)
        await admin.execute(f'CREATE DATABASE "{self.database}"')
        await admin.close()

    async def drop(self) -> None:
        admin = await self.connect(database=self.url.database)
        await admin.execute(f'DROP DATABASE IF EXISTS "{self.database}" WITH (FORCE)')
        for role in {self.spec.owner.name, self.spec.app.name, self.spec.evolution.name} - {self.url.username}:
            await admin.execute(f'DROP ROLE IF EXISTS "{role}"')
        await admin.close()

    async def apply(self) -> dict:
        conn = await self.connect()
        try:
            return await apply_roles(conn, self.spec)
        finally:
            await conn.close()


@pytest.fixture
async def cluster():
    c = Cluster()
    await c.create()
    try:
        yield c
    finally:
        await c.drop()


async def _alembic(monkeypatch, url: str, *steps: tuple[str, str]) -> None:
    """Roda ``alembic upgrade/downgrade`` com a URL indicada (o env.py lê ``get_settings().DATABASE_URL``)."""
    monkeypatch.setattr(get_settings(), "DATABASE_URL", url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    loop = asyncio.get_running_loop()
    for action, revision in steps:
        await loop.run_in_executor(None, getattr(command, action), cfg, revision)


async def _denied(conn: asyncpg.Connection, sql: str) -> bool:
    try:
        async with conn.transaction():
            await conn.execute(sql)
    except (asyncpg.InsufficientPrivilegeError, asyncpg.exceptions.InvalidSchemaNameError):
        return True
    return False


async def _foreign_owned(conn: asyncpg.Connection, schema: str, owner: str) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT c.relname AS name FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = $1 AND c.relkind IN ('r','p','v','m','S') AND pg_get_userbyid(c.relowner) <> $2
        UNION ALL
        SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
         WHERE n.nspname = $1 AND t.typtype IN ('e','d') AND pg_get_userbyid(t.typowner) <> $2
        UNION ALL
        SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = $1 AND pg_get_userbyid(p.proowner) <> $2
        """,
        schema, owner,
    )
    return [r["name"] for r in rows]


async def _insert_user(conn: asyncpg.Connection) -> uuid.UUID:
    uid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO user_accounts (id, email, hashed_password, is_admin, is_active, must_change_password, is_demo, "
        "token_version, failed_login_count, created_at, updated_at) "
        "VALUES ($1, $2, 'x', false, true, false, false, 0, 0, now(), now())",
        uid, f"{uid.hex[:8]}@roles.test",
    )
    return uid


async def test_fresh_install_owner_migrates_and_app_only_touches_data(cluster: Cluster, monkeypatch):
    spec = cluster.spec
    first = await cluster.apply()
    assert set(first["roles"].values()) == {"criado"}
    await _alembic(monkeypatch, cluster.sqlalchemy_url(spec.owner), ("upgrade", "head"))
    await cluster.apply()  # como o db-init: de novo depois das migrations (alembic_version nasceu agora)

    admin = await cluster.connect()
    assert await _foreign_owned(admin, "public", spec.owner.name) == []
    for role in (spec.owner, spec.app, spec.evolution):
        attrs = await admin.fetchrow("SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = $1", role.name)
        assert tuple(attrs) == (False, False, False)
    tables = [r["tablename"] for r in await admin.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]
    assert "audit_logs" in tables and "alembic_version" in tables
    for table in tables:
        privileges = {p: await admin.fetchval("SELECT has_table_privilege($1, $2, $3)", spec.app.name, f"public.{table}", p)
                      for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")}
        expected_write = table != "alembic_version"
        assert privileges == {"SELECT": True, "INSERT": expected_write, "UPDATE": expected_write,
                              "DELETE": expected_write, "TRUNCATE": False}, table
    await admin.close()

    app = await cluster.connect(spec.app)
    uid = await _insert_user(app)
    await app.execute("UPDATE user_accounts SET token_version = 1 WHERE id = $1", uid)
    await app.execute("DELETE FROM user_accounts WHERE id = $1", uid)
    assert await app.fetchval("SELECT count(*) FROM alembic_version") == 1
    for ddl in ("CREATE TABLE public.intruder (id int)", "ALTER TABLE user_accounts ADD COLUMN intruder int",
                "DROP TABLE audit_logs", "TRUNCATE audit_logs", "UPDATE alembic_version SET version_num = version_num",
                f"CREATE TABLE {EVOLUTION_SCHEMA}.intruder (id int)"):
        assert await _denied(app, ddl), ddl
    with pytest.raises(RolesConfigError):  # o db-init recusa conexão que não seja de superusuário
        await apply_roles(app, spec)

    evo = await cluster.connect(spec.evolution)
    await evo.execute(f'CREATE TABLE {EVOLUTION_SCHEMA}."Instance" (id text PRIMARY KEY, token text)')
    await evo.execute(f"INSERT INTO {EVOLUTION_SCHEMA}.\"Instance\" VALUES ('gti', 'segredo')")
    for sql in ("SELECT * FROM public.user_accounts", "DELETE FROM public.audit_logs", "CREATE TABLE public.intruder (id int)"):
        assert await _denied(evo, sql), sql
    # leitura (backup pela tela) sim, escrita não
    assert await app.fetchval(f'SELECT count(*) FROM {EVOLUTION_SCHEMA}."Instance"') == 1
    assert await _denied(app, f"DELETE FROM {EVOLUTION_SCHEMA}.\"Instance\"")

    # tabela criada por uma migration futura (pelo dono) já nasce com as permissões da aplicação
    owner = await cluster.connect(spec.owner)
    await owner.execute("CREATE TABLE public.future_feature (id int)")
    await app.execute("INSERT INTO public.future_feature VALUES (1)")
    for conn in (app, evo, owner):
        await conn.close()

    again = await cluster.apply()  # idempotente: só atualiza
    assert set(again["roles"].values()) == {"atualizado"} and again["transferred"] == 0


async def test_existing_install_is_taken_over_and_owner_keeps_migrating(cluster: Cluster, monkeypatch):
    """Instalação antiga: tudo do superusuário, inclusive o schema da Evolution."""
    spec = cluster.spec
    await _alembic(monkeypatch, cluster.sqlalchemy_url(), ("upgrade", "head"))
    admin = await cluster.connect()
    await admin.execute(
        f"""
        CREATE SCHEMA {EVOLUTION_SCHEMA};
        CREATE TYPE {EVOLUTION_SCHEMA}."InstanceConnectionStatus" AS ENUM ('open', 'close');
        CREATE TABLE {EVOLUTION_SCHEMA}."Instance" (id serial PRIMARY KEY, status {EVOLUTION_SCHEMA}."InstanceConnectionStatus");
        CREATE TYPE public.legacy_kind AS ENUM ('a');
        CREATE TABLE public.legacy_serial (id serial PRIMARY KEY, kind public.legacy_kind);
        CREATE VIEW public.legacy_view AS SELECT 1 AS x;
        CREATE FUNCTION public.legacy_fn() RETURNS int LANGUAGE sql AS 'SELECT 1';
        """
    )

    summary = await cluster.apply()
    assert summary["transferred"] > 0
    assert await _foreign_owned(admin, "public", spec.owner.name) == []
    assert await _foreign_owned(admin, EVOLUTION_SCHEMA, spec.evolution.name) == []
    assert await admin.fetchval("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = $1",
                                EVOLUTION_SCHEMA) == spec.evolution.name
    await admin.close()

    app = await cluster.connect(spec.app)
    await _insert_user(app)
    await app.execute("INSERT INTO public.legacy_serial (kind) VALUES ('a')")  # sequência da coluna liberada
    await app.close()

    # o dono altera e desfaz a estrutura que era do superusuário
    await _alembic(monkeypatch, cluster.sqlalchemy_url(spec.owner), ("downgrade", "-1"), ("upgrade", "head"))


async def test_rollback_to_the_superuser_changes_nothing(cluster: Cluster):
    su = cluster.url.username
    cluster.spec = RolesSpec(cluster.database, Role(su, ""), Role(su, ""), Role(su, ""))
    summary = await cluster.apply()
    assert set(summary["roles"]) == {su} and summary["transferred"] == 0
    admin = await cluster.connect()
    assert await admin.fetchval("SELECT 1 FROM pg_namespace WHERE nspname = $1", EVOLUTION_SCHEMA) is None
    await admin.close()


async def test_invalid_configuration_is_refused():
    ok = uuid.uuid4().hex
    with pytest.raises(RolesConfigError, match="Senha"):
        validate(RolesSpec("gti", Role("gestao_owner", "curta"), Role("gestao_app", ok), Role("gestao_evolution", ok)), "postgres")
    with pytest.raises(RolesConfigError, match="Senha"):
        validate(RolesSpec("gti", Role("gestao_owner", "x" * 15 + "@"), Role("gestao_app", ok), Role("gestao_evolution", ok)),
                 "postgres")
    with pytest.raises(RolesConfigError, match="diferentes"):
        validate(RolesSpec("gti", Role("gestao_app", ok), Role("gestao_app", ok), Role("gestao_evolution", ok)), "postgres")
    with pytest.raises(RolesConfigError, match="inválido"):
        validate(RolesSpec("gti", Role('x"; DROP', ok), Role("gestao_app", ok), Role("gestao_evolution", ok)), "postgres")
