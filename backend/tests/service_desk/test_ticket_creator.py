"""
Chamados vinculados, PR 1: quem abriu (criador) separado do solicitante e abertura em nome de outra pessoa.
O direcionamento por categoria (mudança de comportamento) tem testes próprios em `test_ticket_routing.py`.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.service_desk.models import Ticket
from tests.factories import (
    headers_for,
    make_employee,
    make_org,
    make_sector,
    make_ticket_category,
    make_user,
)

pytestmark = pytest.mark.asyncio

API = "/api/v1/tickets"
ON_BEHALF = "service_desk.tickets.create_on_behalf"


async def _world(db: AsyncSession):
    org = await make_org(db)
    other_sector = await make_sector(db, org.unit)
    opener_emp = await make_employee(db, org)
    beneficiary_emp = await make_employee(db, org)
    beneficiary_emp.sector_id = other_sector.id
    await db.commit()
    opener = await make_user(db, opener_emp)
    beneficiary = await make_user(db, beneficiary_emp)
    stranger = await make_user(db, await make_employee(db, org))
    cat = await make_ticket_category(db, org.sector)
    return org, other_sector, opener, opener_emp, beneficiary, beneficiary_emp, stranger, cat


def _body(cat, **extra) -> dict:
    return {"title": "Pedido", "description": "d", "category_id": str(cat.id), **extra}


# --- Criador -------------------------------------------------------------------------------------------------


async def test_own_ticket_records_creator_and_requester(client: AsyncClient, db_session: AsyncSession):
    _, _, opener, opener_emp, *_, cat = await _world(db_session)
    resp = await client.post(API, json=_body(cat), headers=headers_for(opener))
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["requester_id"] == str(opener_emp.id)
    assert data["created_by_user_id"] == str(opener.id)
    assert data["created_by_name"] == opener_emp.name

    audit = (await db_session.execute(
        select(AuditLog).where(AuditLog.entity_id == uuid.UUID(data["id"]), AuditLog.event_type == "ticket.created")
    )).scalar_one()
    assert audit.user_id == opener.id
    assert audit.data["requester_id"] == str(opener_emp.id)


async def test_service_refuses_ticket_without_creator(db_session: AsyncSession):
    from app.core.exceptions import ValidationException
    from app.service_desk.schemas import TicketCreate
    from app.service_desk.services import ServiceDeskService

    org, *_ , cat = await _world(db_session)
    emp = await make_employee(db_session, org)
    with pytest.raises(ValidationException):
        await ServiceDeskService(db_session).create_ticket(
            TicketCreate(title="x", description="d", category_id=cat.id),
            requester_id=emp.id, origin_unit_id=org.unit.id, origin_sector_id=org.sector.id, user_id=None,
        )


# --- Em nome de outra pessoa ---------------------------------------------------------------------------------


async def test_on_behalf_requires_permission(client: AsyncClient, db_session: AsyncSession):
    _, _, opener, _, _, beneficiary_emp, _, cat = await _world(db_session)
    resp = await client.post(API, json=_body(cat, requester_id=str(beneficiary_emp.id)), headers=headers_for(opener))
    assert resp.status_code == 403


async def test_requester_omitted_or_self_is_the_opener(client: AsyncClient, db_session: AsyncSession):
    _, _, opener, opener_emp, *_, cat = await _world(db_session)
    for extra in ({}, {"requester_id": str(opener_emp.id)}):
        resp = await client.post(API, json=_body(cat, **extra), headers=headers_for(opener))
        assert resp.status_code == 201, resp.text
        assert resp.json()["requester_id"] == str(opener_emp.id)


async def test_on_behalf_with_permission_creator_and_requester_both_follow(
    client: AsyncClient, db_session: AsyncSession
):
    _, other_sector, opener, _, beneficiary, beneficiary_emp, stranger, cat = await _world(db_session)
    resp = await client.post(
        API, json=_body(cat, requester_id=str(beneficiary_emp.id)), headers=headers_for(opener, ON_BEHALF)
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    ticket_id = data["id"]
    assert data["requester_id"] == str(beneficiary_emp.id)
    assert data["created_by_user_id"] == str(opener.id)
    # Origem é a do solicitante (para quem é o pedido), não a de quem abriu.
    assert data["origin_sector_id"] == str(other_sector.id)

    for user in (opener, beneficiary):
        h = headers_for(user)
        assert (await client.get(f"{API}/{ticket_id}", headers=h)).status_code == 200
        assert any(t["id"] == ticket_id for t in (await client.get(API, headers=h)).json())
        assert (await client.get(f"{API}/{ticket_id}/history", headers=h)).status_code == 200
        public = await client.post(f"{API}/{ticket_id}/interactions", json={"message": "oi"}, headers=h)
        assert public.status_code == 201, public.text
        internal = await client.post(
            f"{API}/{ticket_id}/interactions", json={"message": "nota", "is_internal": True}, headers=h
        )
        assert internal.status_code == 403
    # Quem abriu não altera prioridade (só finaliza, como o solicitante)
    assert (await client.patch(f"{API}/{ticket_id}", json={"priority": "HIGH"}, headers=headers_for(opener))).status_code == 403

    hs = headers_for(stranger)
    assert (await client.get(f"{API}/{ticket_id}", headers=hs)).status_code == 403
    assert all(t["id"] != ticket_id for t in (await client.get(API, headers=hs)).json())


async def test_on_behalf_rejects_unknown_or_inactive_employee(client: AsyncClient, db_session: AsyncSession):
    org, _, opener, *_, cat = await _world(db_session)
    h = headers_for(opener, ON_BEHALF)
    assert (await client.post(API, json=_body(cat, requester_id=str(uuid.uuid4())), headers=h)).status_code == 400
    gone = await make_employee(db_session, org)
    gone.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()
    assert (await client.post(API, json=_body(cat, requester_id=str(gone.id)), headers=h)).status_code == 400



# --- Migration: preenchimento do criador ---------------------------------------------------------------------


@pytest.mark.migrations
async def test_migration_backfills_creator_and_marks_only_unidentified_rows():
    import asyncio
    import os
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

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
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, command.upgrade, cfg, "a5b6c7d8e9f0a")

    ids = {k: uuid.uuid4() for k in (
        "company", "unit", "sector", "emp", "user", "t_audited", "t_orphan", "t_gone_user",
    )}
    ghost_user = uuid.uuid4()  # ator da trilha cuja conta já não existe
    async with engine.begin() as conn:
        x = conn.execute
        await x(text("INSERT INTO companies (id, name, is_demo, is_active, created_at, updated_at) "
                     "VALUES (:i, 'Empresa', false, true, now(), now())"), {"i": ids["company"]})
        await x(text("INSERT INTO units (id, company_id, name, code, type, is_demo, is_active, created_at, updated_at) "
                     "VALUES (:i, :c, 'U', 'U1', 'MATRIZ', false, true, now(), now())"), {"i": ids["unit"], "c": ids["company"]})
        await x(text("INSERT INTO sectors (id, unit_id, name, code, is_demo, is_active, created_at, updated_at) "
                     "VALUES (:i, :u, 'S', 'S1', false, true, now(), now())"), {"i": ids["sector"], "u": ids["unit"]})
        await x(text("INSERT INTO employees (id, unit_id, sector_id, name, registration_number, status, is_demo, is_active, "
                     "created_at, updated_at) VALUES (:i, :u, :s, 'E', 'M1', 'ATIVO', false, true, now(), now())"),
                {"i": ids["emp"], "u": ids["unit"], "s": ids["sector"]})
        await x(text("INSERT INTO user_accounts (id, email, hashed_password, is_admin, is_active, must_change_password, is_demo, "
                     "token_version, failed_login_count, employee_id, created_at, updated_at) "
                     "VALUES (:i, 'u@test.local', 'x', false, true, false, false, 0, 0, :e, now(), now())"),
                {"i": ids["user"], "e": ids["emp"]})
        for key in ("t_audited", "t_orphan", "t_gone_user"):
            await x(text("INSERT INTO sd_ticket (id, title, description, priority, status, custom_fields, requester_id, "
                         "origin_unit_id, origin_sector_id, responsible_sector_id, is_demo, created_at, updated_at) "
                         "VALUES (:i, 't', 'd', 'LOW', 'OPENED', '{}', :e, :u, :s, :s, false, now(), now())"),
                    {"i": ids[key], "e": ids["emp"], "u": ids["unit"], "s": ids["sector"]})
        for ticket, actor in (("t_audited", ids["user"]), ("t_gone_user", ghost_user)):
            await x(text("INSERT INTO audit_logs (id, event_type, entity_type, entity_id, data, user_id, actor_kind, category, "
                         "created_at, updated_at) VALUES (gen_random_uuid(), 'ticket.created', 'ticket', :t, '{}', :a, "
                         "'human', 'operational', now(), now())"), {"t": ids[ticket], "a": actor})

    await loop.run_in_executor(None, command.upgrade, cfg, "e5f6a7b8c9d0e")

    async with engine.connect() as conn:
        rows = dict(
            ((r.id, (r.created_by_user_id, r.creator_unknown)) for r in
             (await conn.execute(text("SELECT id, created_by_user_id, creator_unknown FROM sd_ticket"))).all())
        )
        assert rows[ids["t_audited"]] == (ids["user"], False)
        assert rows[ids["t_orphan"]] == (None, True)
        assert rows[ids["t_gone_user"]] == (None, True)  # conta do ator não existe mais: não inventa criador

        on_behalf = await conn.execute(text("SELECT count(*) FROM role_permissions rp JOIN permissions p "
                                            "ON p.id = rp.permission_id WHERE p.code = :c"), {"c": ON_BEHALF})
        assert on_behalf.scalar() == 0  # sem concessão automática

    # As linhas antigas marcadas continuam válidas (podem ser alteradas); um chamado novo sem criador não entra.
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE sd_ticket SET title = 'ok' WHERE id = :i"), {"i": ids["t_orphan"]})
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError):
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO sd_ticket (id, title, description, priority, status, custom_fields, "
                                    "requester_id, origin_unit_id, origin_sector_id, responsible_sector_id, is_demo, "
                                    "creator_unknown, created_at, updated_at) VALUES (gen_random_uuid(), 't', 'd', 'LOW', "
                                    "'OPENED', '{}', :e, :u, :s, :s, false, true, now() - interval '5 years', now())"),
                               {"e": ids["emp"], "u": ids["unit"], "s": ids["sector"]})

    await loop.run_in_executor(None, command.downgrade, cfg, "a5b6c7d8e9f0a")
    async with engine.connect() as conn:
        left = await conn.execute(text("SELECT count(*) FROM permissions WHERE code = :c"), {"c": ON_BEHALF})
        assert left.scalar() == 0
        assert (await conn.execute(text("SELECT count(*) FROM sd_ticket"))).scalar() == 3
    await loop.run_in_executor(None, command.upgrade, cfg, "head")
    await engine.dispose()


# --- Guarda do criador no banco (PostgreSQL) ----------------------------------------------------------------


@pytest.mark.pg
async def test_creator_guard_in_postgres():
    import os

    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, IntegrityError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import Base

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as db:
            org = await make_org(db)
            emp = await make_employee(db, org)
            user = await make_user(db, emp)

        def _ticket(**extra) -> Ticket:
            return Ticket(
                title="t", description="d", requester_id=emp.id, origin_unit_id=org.unit.id,
                origin_sector_id=org.sector.id, responsible_sector_id=org.sector.id, **extra,
            )

        async def _refused(**extra) -> None:
            async with maker() as db:
                db.add(_ticket(**extra))
                with pytest.raises((IntegrityError, DBAPIError)):
                    await db.commit()
                await db.rollback()

        # Sem criador falha, inclusive com data retroativa; a marca de antigo não vale para registro novo.
        await _refused()
        await _refused(created_at=datetime.now(timezone.utc) - timedelta(days=3650))
        await _refused(creator_unknown=True)
        await _refused(creator_unknown=True, created_at=datetime.now(timezone.utc) - timedelta(days=3650))

        async with maker() as db:
            ok = _ticket(created_by_user_id=user.id)
            db.add(ok)
            await db.commit()
            ok_id = ok.id  # o rollback expira o objeto; ler o id depois faria IO fora do await
            # Não dá para "envelhecer" um chamado com criador: ligar a marca é recusado...
            with pytest.raises(DBAPIError):
                await db.execute(text("UPDATE sd_ticket SET creator_unknown = true WHERE id = :i"), {"i": ok_id})
            await db.rollback()
            # ...e apagar o criador viola a CHECK.
            with pytest.raises(DBAPIError):
                await db.execute(text("UPDATE sd_ticket SET created_by_user_id = NULL WHERE id = :i"), {"i": ok_id})
            await db.rollback()

        # Linha antiga marcada pela migration (simulada com o gatilho desligado) continua válida, e a marca pode
        # ser desligada quando alguém preenche o criador.
        async with maker() as db:
            legacy = _ticket(created_by_user_id=user.id)
            db.add(legacy)
            await db.commit()
            legacy_id, user_id = legacy.id, user.id
            await db.execute(text("ALTER TABLE sd_ticket DISABLE TRIGGER sd_ticket_creator_guard"))
            await db.execute(
                text("UPDATE sd_ticket SET created_by_user_id = NULL, creator_unknown = true WHERE id = :i"),
                {"i": legacy_id},
            )
            await db.execute(text("ALTER TABLE sd_ticket ENABLE TRIGGER sd_ticket_creator_guard"))
            await db.commit()
            await db.execute(text("UPDATE sd_ticket SET title = 'ainda válido' WHERE id = :i"), {"i": legacy_id})
            await db.execute(
                text("UPDATE sd_ticket SET created_by_user_id = :u, creator_unknown = false WHERE id = :i"),
                {"u": user_id, "i": legacy_id},
            )
            await db.commit()
    finally:
        await engine.dispose()
