"""
Papéis de banco separados (ADR-022; Plano de Evolução, Fase 0 PR 10; S3).

Roda no serviço ``db-init`` do Compose, o ÚNICO que recebe a senha do superusuário do PostgreSQL, antes das
migrations, e de novo depois delas (a tabela ``alembic_version`` só existe depois da primeira):

    python -m app.db_roles && alembic upgrade head && python -m app.db_roles      (DATABASE_URL = papel dono)

Papéis:

* **dono** (``DB_OWNER_USER``): dono das tabelas do schema ``public``; só ele roda migrations (DDL).
* **aplicação** (``DB_APP_USER``): backend e worker. SELECT/INSERT/UPDATE/DELETE nas tabelas, sem DDL, sem
  TRUNCATE, só leitura em ``alembic_version`` e leitura no schema da Evolution (para o backup pela tela).
* **Evolution** (``DB_EVOLUTION_USER``): dono do schema ``evolution_api`` e de nada mais.

Idempotente: cria ou atualiza os papéis (senha e atributos), transfere para o dono certo o que ainda pertence a
outro papel (instalação antiga, tudo do superusuário, ou backup antigo restaurado) e reaplica as permissões.

Volta para o superusuário (rollback): no ``.env``, use o superusuário em ``DB_*_USER`` (e a senha dele em
``DB_*_PASSWORD``). Papel igual ao superusuário é ignorado aqui; nada nos dados muda.

Não importa ``app.config`` de propósito: só precisa das variáveis de ambiente do banco.
"""

import asyncio
import os
import re
import sys
from dataclasses import dataclass

import asyncpg

EVOLUTION_SCHEMA = "evolution_api"
APP_SCHEMA = "public"

_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
# Vai dentro de URLs de conexão (DATABASE_URL): só caracteres que não precisam de escape.
_PASSWORD = re.compile(r"^[A-Za-z0-9._~-]{16,128}$")
_LOCK_KEY = 0x6774695F726F6C  # "gti_rol": serializa execuções simultâneas do db-init

_RELKIND_KEYWORD = {"r": "TABLE", "p": "TABLE", "v": "VIEW", "m": "MATERIALIZED VIEW", "f": "FOREIGN TABLE", "S": "SEQUENCE"}


class RolesConfigError(ValueError):
    """Configuração dos papéis inválida (nome, senha ou conexão sem superusuário)."""


@dataclass(frozen=True)
class Role:
    name: str
    password: str


@dataclass(frozen=True)
class RolesSpec:
    database: str
    owner: Role
    app: Role
    evolution: Role


def validate(spec: RolesSpec, superuser: str) -> None:
    separate = [r for r in (spec.owner, spec.app, spec.evolution) if r.name != superuser]
    for label, role in (("dono", spec.owner), ("aplicação", spec.app), ("Evolution", spec.evolution)):
        if not _NAME.match(role.name):
            raise RolesConfigError(f"Nome do papel {label} inválido: {role.name!r} (use minúsculas, números e _).")
        if role.name != superuser and not _PASSWORD.match(role.password):
            raise RolesConfigError(
                f"Senha do papel {label} ({role.name}) ausente ou fraca: 16 a 128 caracteres, só letras, números e . _ ~ - "
                "(gere com: openssl rand -hex 16)."
            )
    if len({r.name for r in separate}) != len(separate):
        raise RolesConfigError("Os papéis dono, aplicação e Evolution precisam ter nomes diferentes.")


async def _exec_formatted(conn: asyncpg.Connection, template: str, *args: str) -> None:
    """Monta o comando no servidor com ``format()`` (%I = identificador, %L = literal) e o executa."""
    placeholders = ", ".join(f"${i}::text" for i in range(1, len(args) + 1))
    statement = await conn.fetchval(f"SELECT format('{template}', {placeholders})", *args)
    await conn.execute(statement)


async def _ensure_role(conn: asyncpg.Connection, role: Role) -> str:
    exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role.name)
    verb = "ALTER ROLE %I WITH" if exists else "CREATE ROLE %I WITH"
    await _exec_formatted(
        conn,
        verb + " LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L",
        role.name,
        role.password,
    )
    return "atualizado" if exists else "criado"


async def _transfer_ownership(conn: asyncpg.Connection, schema: str, owner: str) -> int:
    """Passa para ``owner`` as relações, tipos e funções do schema que pertencem a outro papel."""
    moved = 0
    relations = await conn.fetch(
        """
        SELECT c.relname, c.relkind::text AS relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = $1 AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
          AND pg_get_userbyid(c.relowner) <> $2
          AND NOT EXISTS (  -- sequência de coluna (serial/identity) segue a tabela; objeto de extensão fica
            SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid
              AND (d.deptype = 'e' OR (c.relkind = 'S' AND d.deptype IN ('a', 'i'))))
        ORDER BY c.relkind DESC, c.relname
        """,
        schema,
        owner,
    )
    for rel in relations:
        await _exec_formatted(conn, f"ALTER {_RELKIND_KEYWORD[rel['relkind']]} %I.%I OWNER TO %I", schema, rel["relname"], owner)
        moved += 1
    types = await conn.fetch(
        """
        SELECT t.typname, t.typtype::text AS typtype FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = $1 AND t.typtype IN ('e', 'd') AND pg_get_userbyid(t.typowner) <> $2
          AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e')
        """,
        schema,
        owner,
    )
    for typ in types:
        keyword = "DOMAIN" if typ["typtype"] == "d" else "TYPE"
        await _exec_formatted(conn, f"ALTER {keyword} %I.%I OWNER TO %I", schema, typ["typname"], owner)
        moved += 1
    functions = await conn.fetch(
        """
        SELECT p.oid::regprocedure::text AS signature, p.prokind::text AS prokind FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = $1 AND p.prokind IN ('f', 'p') AND pg_get_userbyid(p.proowner) <> $2
          AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')
        """,
        schema,
        owner,
    )
    for fn in functions:
        keyword = "PROCEDURE" if fn["prokind"] == "p" else "FUNCTION"
        # regprocedure já vem qualificado e com aspas quando precisa
        await _exec_formatted(conn, f"ALTER {keyword} %s OWNER TO %I", fn["signature"], owner)
        moved += 1
    return moved


async def apply_roles(conn: asyncpg.Connection, spec: RolesSpec) -> dict:
    """Cria/atualiza os papéis e aplica posse e permissões. ``conn`` precisa ser de um superusuário."""
    superuser = await conn.fetchval("SELECT current_user")
    if not await conn.fetchval("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"):
        raise RolesConfigError(f"O db-init precisa do superusuário do PostgreSQL; {superuser!r} não é.")
    validate(spec, superuser)
    owner, app, evolution = spec.owner.name, spec.app.name, spec.evolution.name
    summary: dict = {"roles": {}, "transferred": 0}

    async with conn.transaction():
        await conn.execute("SET LOCAL log_statement = 'none'")  # o CREATE/ALTER ROLE leva a senha
        await conn.execute(f"SELECT pg_advisory_xact_lock({_LOCK_KEY})")
        for role in (spec.owner, spec.app, spec.evolution):
            if role.name == superuser:
                summary["roles"][role.name] = "superusuário (ignorado)"
                continue
            summary["roles"][role.name] = await _ensure_role(conn, role)
            await _exec_formatted(conn, "GRANT CONNECT ON DATABASE %I TO %I", spec.database, role.name)

        # --- schema public: só o dono cria objetos ---------------------------------------------------------
        await _exec_formatted(conn, "REVOKE CREATE ON SCHEMA %I FROM PUBLIC", APP_SCHEMA)
        await _exec_formatted(conn, "GRANT USAGE, CREATE ON SCHEMA %I TO %I", APP_SCHEMA, owner)
        if owner != superuser:
            summary["transferred"] += await _transfer_ownership(conn, APP_SCHEMA, owner)

        # --- schema da Evolution: dela e de mais ninguém ------------------------------------------------------
        if evolution != superuser:
            await _exec_formatted(conn, "CREATE SCHEMA IF NOT EXISTS %I AUTHORIZATION %I", EVOLUTION_SCHEMA, evolution)
            await _exec_formatted(conn, "ALTER SCHEMA %I OWNER TO %I", EVOLUTION_SCHEMA, evolution)
            summary["transferred"] += await _transfer_ownership(conn, EVOLUTION_SCHEMA, evolution)
            await _exec_formatted(conn, "REVOKE CREATE ON SCHEMA %I FROM %I", APP_SCHEMA, evolution)
            await _exec_formatted(conn, "REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM %I", APP_SCHEMA, evolution)
            await _exec_formatted(conn, "REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM %I", APP_SCHEMA, evolution)

        # --- aplicação: dados sim, estrutura não ---------------------------------------------------------------
        if app != superuser:
            await _exec_formatted(conn, "GRANT USAGE ON SCHEMA %I TO %I", APP_SCHEMA, app)
            await _exec_formatted(conn, "REVOKE CREATE ON SCHEMA %I FROM %I", APP_SCHEMA, app)
            await _exec_formatted(conn, "REVOKE TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA %I FROM %I", APP_SCHEMA, app)
            await _exec_formatted(conn, "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO %I", APP_SCHEMA, app)
            await _exec_formatted(conn, "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA %I TO %I", APP_SCHEMA, app)
            # tabelas que as próximas migrations criarem (o dono as cria) já nascem com as mesmas permissões
            await _exec_formatted(
                conn,
                "ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I",
                owner, APP_SCHEMA, app,
            )
            await _exec_formatted(
                conn,
                "ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I",
                owner, APP_SCHEMA, app,
            )
            if await conn.fetchval("SELECT to_regclass('public.alembic_version') IS NOT NULL"):
                await _exec_formatted(conn, "REVOKE INSERT, UPDATE, DELETE ON %I.alembic_version FROM %I", APP_SCHEMA, app)

            # leitura do schema da Evolution: o backup pela tela (pg_dump com o papel da aplicação) continua completo
            if await conn.fetchval("SELECT 1 FROM pg_namespace WHERE nspname = $1", EVOLUTION_SCHEMA):
                await _exec_formatted(conn, "GRANT USAGE ON SCHEMA %I TO %I", EVOLUTION_SCHEMA, app)
                await _exec_formatted(conn, "GRANT SELECT ON ALL TABLES IN SCHEMA %I TO %I", EVOLUTION_SCHEMA, app)
                await _exec_formatted(conn, "GRANT SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I", EVOLUTION_SCHEMA, app)
                await _exec_formatted(
                    conn,
                    "ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT ON TABLES TO %I",
                    evolution, EVOLUTION_SCHEMA, app,
                )
                await _exec_formatted(
                    conn,
                    "ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT ON SEQUENCES TO %I",
                    evolution, EVOLUTION_SCHEMA, app,
                )
    return summary


def spec_from_env(env: dict[str, str]) -> RolesSpec:
    return RolesSpec(
        database=env.get("POSTGRES_DB", "gestao_ti"),
        owner=Role(env.get("DB_OWNER_USER", "gestao_owner"), env.get("DB_OWNER_PASSWORD", "")),
        app=Role(env.get("DB_APP_USER", "gestao_app"), env.get("DB_APP_PASSWORD", "")),
        evolution=Role(env.get("DB_EVOLUTION_USER", "gestao_evolution"), env.get("DB_EVOLUTION_PASSWORD", "")),
    )


async def main() -> int:
    env = dict(os.environ)
    spec = spec_from_env(env)
    try:
        conn = await asyncpg.connect(
            host=env.get("POSTGRES_HOST", "postgres"),
            port=int(env.get("POSTGRES_PORT", "5432")),
            user=env.get("POSTGRES_USER", "postgres"),
            password=env.get("POSTGRES_PASSWORD", ""),
            database=spec.database,
        )
    except (OSError, asyncpg.PostgresError) as exc:
        print(f"!! db-init: não consegui conectar ao PostgreSQL com o superusuário: {exc}", file=sys.stderr)
        return 1
    try:
        summary = await apply_roles(conn, spec)
    except RolesConfigError as exc:
        print(f"!! db-init: {exc}", file=sys.stderr)
        return 1
    finally:
        await conn.close()
    roles = ", ".join(f"{name} ({state})" for name, state in summary["roles"].items())
    print(f"==> Papéis de banco: {roles}; objetos com dono corrigido: {summary['transferred']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
