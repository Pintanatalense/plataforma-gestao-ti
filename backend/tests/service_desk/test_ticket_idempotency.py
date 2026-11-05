"""
Idempotência da criação de chamados (ADR-026, PR 2b): ``Idempotency-Key`` em ``POST /tickets`` e
``POST /tickets/{id}/children``. Os envios simultâneos são testados no PostgreSQL, com duas sessões reais.
"""

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.service_desk.models import IdempotencyKey, Ticket
from tests.factories import headers_for, make_employee, make_org, make_sector, make_ticket_category, make_user

pytestmark = pytest.mark.asyncio

API = "/api/v1/tickets"


async def _world(db: AsyncSession):
    org = await make_org(db)
    other = await make_sector(db, org.unit)
    user = await make_user(db, await make_employee(db, org))
    return user, await make_ticket_category(db, org.sector), await make_ticket_category(db, other)


def _body(cat, **extra) -> dict:
    return {"title": "Pedido", "description": "d", "category_id": str(cat.id), **extra}


def _with_key(user, key: str) -> dict:
    return {**headers_for(user), "Idempotency-Key": key}


async def _count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count(Ticket.id)))).scalar_one()


async def test_same_key_same_body_returns_same_ticket(client: AsyncClient, db_session: AsyncSession):
    user, cat, child_cat = await _world(db_session)
    key = str(uuid.uuid4())
    body = _body(cat, children=[{"category_id": str(child_cat.id), "title": "E", "description": "d"}])
    first = await client.post(API, json=body, headers=_with_key(user, key))
    assert first.status_code == 201, first.text
    total = await _count(db_session)

    again = await client.post(API, json=body, headers=_with_key(user, key))
    assert again.status_code == 200
    assert again.headers["Idempotent-Replay"] == "true"
    assert again.json()["id"] == first.json()["id"]
    assert await _count(db_session) == total == 2


async def test_same_key_other_body_is_refused(client: AsyncClient, db_session: AsyncSession):
    user, cat, _ = await _world(db_session)
    key = str(uuid.uuid4())
    assert (await client.post(API, json=_body(cat), headers=_with_key(user, key))).status_code == 201
    resp = await client.post(API, json=_body(cat, title="Outro"), headers=_with_key(user, key))
    assert resp.status_code == 422
    assert await _count(db_session) == 1


async def test_key_is_bound_to_one_operation(client: AsyncClient, db_session: AsyncSession):
    user, cat, child_cat = await _world(db_session)
    key = str(uuid.uuid4())
    parent = (await client.post(API, json=_body(cat), headers=_with_key(user, key))).json()
    children = {"children": [{"category_id": str(child_cat.id), "title": "E", "description": "d"}]}

    # Mesma chave na outra rota: 422 e nenhum filho criado.
    resp = await client.post(f"{API}/{parent['id']}/children", json=children, headers=_with_key(user, key))
    assert resp.status_code == 422
    assert await _count(db_session) == 1

    # Mesma rota de filhos, mesma chave, outro principal: 422.
    other_parent = (await client.post(API, json=_body(cat), headers=headers_for(user))).json()
    key2 = str(uuid.uuid4())
    ok = await client.post(f"{API}/{parent['id']}/children", json=children, headers=_with_key(user, key2))
    assert ok.status_code == 201, ok.text
    replay = await client.post(f"{API}/{parent['id']}/children", json=children, headers=_with_key(user, key2))
    assert replay.status_code == 200 and [c["id"] for c in replay.json()] == [c["id"] for c in ok.json()]
    moved = await client.post(f"{API}/{other_parent['id']}/children", json=children, headers=_with_key(user, key2))
    assert moved.status_code == 422
    assert await _count(db_session) == 3


async def test_keys_are_per_user_and_must_be_uuid(client: AsyncClient, db_session: AsyncSession):
    user, cat, _ = await _world(db_session)
    other = await make_user(db_session, await make_employee(db_session, await make_org(db_session)))
    key = str(uuid.uuid4())
    assert (await client.post(API, json=_body(cat), headers=_with_key(user, key))).status_code == 201
    assert (await client.post(API, json=_body(cat), headers=_with_key(other, key))).status_code == 201
    assert (await client.post(API, json=_body(cat), headers=_with_key(user, "nao-e-uuid"))).status_code == 422


async def test_failed_request_releases_the_key(client: AsyncClient, db_session: AsyncSession):
    user, cat, _ = await _world(db_session)
    key = str(uuid.uuid4())
    inactive = await make_ticket_category(db_session, None, active=False)
    assert (await client.post(API, json=_body(inactive), headers=_with_key(user, key))).status_code == 400
    await db_session.rollback()
    assert (await db_session.execute(select(func.count(IdempotencyKey.id)))).scalar_one() == 0


async def test_without_header_nothing_changes(client: AsyncClient, db_session: AsyncSession):
    user, cat, _ = await _world(db_session)
    for _ in range(2):
        assert (await client.post(API, json=_body(cat), headers=headers_for(user))).status_code == 201
    assert await _count(db_session) == 2


async def test_retention_job_drops_old_keys(db_session: AsyncSession):
    from app.service_desk.idempotency import purge_expired

    user, *_ = await _world(db_session)
    now = datetime.now(timezone.utc)
    for age in (timedelta(hours=1), timedelta(hours=49)):
        db_session.add(IdempotencyKey(
            user_id=user.id, key=str(uuid.uuid4()), endpoint="POST /tickets", request_hash="h", response_ids=[],
            created_at=now - age,
        ))
    await db_session.commit()
    assert await purge_expired(db_session, now) == 1
    await db_session.commit()
    assert (await db_session.execute(select(func.count(IdempotencyKey.id)))).scalar_one() == 1


@pytest.mark.pg
async def test_simultaneous_requests_create_one_set():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.exceptions import AppException
    from app.database import Base
    from app.service_desk import idempotency
    from app.service_desk.schemas import TicketCreate
    from app.service_desk.services import ServiceDeskService

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
            cat = await make_ticket_category(db, org.sector)
        schema = TicketCreate(title="P", description="d", category_id=cat.id)
        key = str(uuid.uuid4())
        body_hash = idempotency.request_hash(schema.model_dump(mode="json"))

        async def send() -> tuple[str, list[str]]:
            async with maker() as db:
                try:
                    claimed = await idempotency.claim(
                        db, user_id=user.id, key=key, endpoint=idempotency.CREATE_TICKET, target_id=None,
                        body_hash=body_hash,
                    )
                    if claimed.replay_ids is not None:
                        return "replay", [str(i) for i in claimed.replay_ids]
                    ticket = await ServiceDeskService(db).create_ticket(
                        schema, requester_id=emp.id, origin_unit_id=org.unit.id, origin_sector_id=org.sector.id,
                        user_id=user.id,
                    )
                    await asyncio.sleep(0.3)  # segura a reserva para o outro envio chegar enquanto ela existe
                    await idempotency.record(db, claimed, [ticket.id])
                    await db.commit()
                    return "created", [str(ticket.id)]
                except AppException as exc:
                    await db.rollback()
                    return f"erro {exc.status_code}", []

        results = await asyncio.gather(send(), send())
        assert sorted(kind for kind, _ in results) == ["created", "replay"]
        assert results[0][1] == results[1][1]
        async with maker() as db:
            assert (await db.execute(select(func.count(Ticket.id)))).scalar_one() == 1
    finally:
        await engine.dispose()


@pytest.mark.pg
@pytest.mark.migrations
async def test_migration_creates_and_drops_the_key_table():
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
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

    async def exists() -> bool:
        async with engine.connect() as conn:
            return (await conn.execute(text("SELECT to_regclass('public.sd_idempotency_keys')"))).scalar() is not None

    try:
        await loop.run_in_executor(None, command.upgrade, cfg, "b1c2d3e4f5a6b")
        assert await exists()
        await loop.run_in_executor(None, command.downgrade, cfg, "a9b0c1d2e3f4a")
        assert not await exists()
    finally:
        await engine.dispose()
