"""Automações proativas (ADR-013, Fase F): estoque abaixo do mínimo e garantia a vencer."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assets.models import Asset
from app.notifications.automations import (
    check_stock_low,
    check_warranties,
    job_stock_low_check,
    job_warranty_check,
    purge_old_marks,
)
from app.notifications.fanout import plan_event
from app.notifications.jobs import DEFAULT_JOBS, JOBS
from app.notifications.models import AutomationMark, DomainEvent, NotificationRule
from app.notifications.rules_seed import seed_notification_rules
from app.notifications.templates import render
from app.stock.models import StockItem
from tests.factories import make_asset, make_asset_category, make_org, make_stock_item, make_user

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 10, 19)


async def events(db: AsyncSession, event_type: str) -> list[DomainEvent]:
    rows = await db.execute(select(DomainEvent).where(DomainEvent.event_type == event_type).order_by(DomainEvent.created_at))
    return list(rows.scalars())


async def _stock(db: AsyncSession, org, quantity: int, minimum: int, name: str | None = None) -> StockItem:
    item = await make_stock_item(db, org.unit, quantity=quantity)
    item.min_quantity = minimum
    if name:
        item.name = name
    await db.commit()
    return item


# --- Estoque --------------------------------------------------------------------------------------


async def test_low_stock_is_announced_once_in_a_single_digest(db_session: AsyncSession):
    org = await make_org(db_session)
    await _stock(db_session, org, 2, 5, "Toner")
    await _stock(db_session, org, 5, 5, "Cabo")  # no limite: a tela de estoque já chama de "Estoque Baixo"
    await _stock(db_session, org, 9, 5, "Mouse")  # acima do mínimo
    await _stock(db_session, org, 0, 0, "Sem mínimo configurado")

    assert await check_stock_low(db_session) == 2
    [event] = await events(db_session, "stock.below_minimum")
    assert event.priority == "high" and event.payload["total"] == 2
    assert [i["name"] for i in event.payload["items"]] == ["Toner", "Cabo"]  # mais crítico primeiro

    assert await check_stock_low(db_session) == 0  # segunda execução não repete
    assert len(await events(db_session, "stock.below_minimum")) == 1


async def test_restocking_rearms_the_alert(db_session: AsyncSession):
    org = await make_org(db_session)
    item = await _stock(db_session, org, 1, 5, "Toner")
    await check_stock_low(db_session)

    item.quantity = 20
    await db_session.commit()
    assert await check_stock_low(db_session) == 0
    assert (await db_session.execute(select(func.count()).select_from(AutomationMark))).scalar_one() == 0

    item.quantity = 3
    await db_session.commit()
    assert await check_stock_low(db_session) == 1
    assert len(await events(db_session, "stock.below_minimum")) == 2


async def test_new_low_item_is_announced_without_repeating_the_old_one(db_session: AsyncSession):
    org = await make_org(db_session)
    await _stock(db_session, org, 1, 5, "Toner")
    await check_stock_low(db_session)
    await _stock(db_session, org, 0, 2, "Pilha")
    assert await check_stock_low(db_session) == 1
    last = (await events(db_session, "stock.below_minimum"))[-1]
    assert [i["name"] for i in last.payload["items"]] == ["Pilha"]


async def test_digest_caps_the_listed_items_but_reports_the_total(db_session: AsyncSession):
    org = await make_org(db_session)
    for n in range(14):
        await _stock(db_session, org, 0, 1, f"Item {n:02d}")
    await check_stock_low(db_session)
    [event] = await events(db_session, "stock.below_minimum")
    assert event.payload["total"] == 14 and len(event.payload["items"]) == 10
    message = render("stock.below_minimum", event.payload, "high")
    assert message.title == "14 itens com estoque baixo" and "e mais 4" in message.body_text and message.link == "/stock"


# --- Garantia -------------------------------------------------------------------------------------


async def _asset(db: AsyncSession, org, category, expires: date | None, **kw) -> Asset:
    asset = await make_asset(db, org, category, **kw)
    asset.warranty_expires = expires
    await db.commit()
    return asset


async def test_warranty_bands_30_and_7_each_announce_once(db_session: AsyncSession):
    org, category = await make_org(db_session), await make_asset_category(db_session)
    asset = await _asset(db_session, org, category, TODAY + timedelta(days=25))

    assert await check_warranties(db_session, TODAY) == 1
    assert await check_warranties(db_session, TODAY + timedelta(days=3)) == 0  # ainda na faixa de 30, já avisada
    assert await check_warranties(db_session, TODAY + timedelta(days=19)) == 1  # a 6 dias entra na faixa de 7
    assert await check_warranties(db_session, TODAY + timedelta(days=20)) == 0
    first, second = await events(db_session, "asset.warranty_expiring")
    assert first.priority == "normal" and second.priority == "high"
    assert second.payload["items"][0]["id"] == str(asset.id)


async def test_asset_registered_close_to_expiry_gets_one_notice_not_two(db_session: AsyncSession):
    org, category = await make_org(db_session), await make_asset_category(db_session)
    await _asset(db_session, org, category, TODAY + timedelta(days=5))
    assert await check_warranties(db_session, TODAY) == 1
    assert await check_warranties(db_session, TODAY + timedelta(days=1)) == 0
    assert len(await events(db_session, "asset.warranty_expiring")) == 1


async def test_renewing_the_warranty_rearms_the_notice(db_session: AsyncSession):
    org, category = await make_org(db_session), await make_asset_category(db_session)
    asset = await _asset(db_session, org, category, TODAY + timedelta(days=10))
    await check_warranties(db_session, TODAY)
    asset.warranty_expires = TODAY + timedelta(days=365)
    await db_session.commit()
    assert await check_warranties(db_session, TODAY) == 0
    asset.warranty_expires = TODAY + timedelta(days=20)
    await db_session.commit()
    assert await check_warranties(db_session, TODAY) == 1


async def test_only_relevant_assets_are_considered(db_session: AsyncSession):
    org, category = await make_org(db_session), await make_asset_category(db_session)
    await _asset(db_session, org, category, TODAY + timedelta(days=60))  # longe
    await _asset(db_session, org, category, TODAY - timedelta(days=1))  # já venceu
    await _asset(db_session, org, category, None)
    await _asset(db_session, org, category, TODAY + timedelta(days=5), status="DECOMMISSIONED")
    inactive = await _asset(db_session, org, category, TODAY + timedelta(days=5))
    inactive.is_active = False
    await db_session.commit()
    assert await check_warranties(db_session, TODAY) == 0
    assert await events(db_session, "asset.warranty_expiring") == []


async def test_warranty_message_wording():
    payload = {
        "total": 3,
        "items": [
            {"id": "1", "tag": "PAT-1", "name": "Notebook", "days_left": 0},
            {"id": "2", "tag": "PAT-2", "name": "Switch", "days_left": 1},
            {"id": "3", "tag": "PAT-3", "name": "Monitor", "days_left": 12},
        ],
    }
    message = render("asset.warranty_expiring", payload, "normal")
    assert message.title == "3 garantias perto de vencer"
    assert "vence hoje" in message.body_text and "vence amanhã" in message.body_text and "vence em 12 dias" in message.body_text
    assert message.link == "/assets"


async def test_old_warranty_marks_are_purged_but_stock_marks_stay(db_session: AsyncSession):
    old = datetime.now(timezone.utc) - timedelta(days=500)
    db_session.add_all([AutomationMark(key="warranty:x:2025-01-01:30", created_at=old), AutomationMark(key="stock.low:y", created_at=old)])
    await db_session.commit()
    await purge_old_marks(db_session)
    await db_session.commit()
    keys = set((await db_session.execute(select(AutomationMark.key))).scalars())
    assert keys == {"stock.low:y"}


# --- Integração com o hub -------------------------------------------------------------------------


async def test_jobs_are_registered_and_scheduled_by_default():
    assert DEFAULT_JOBS["stock.low_check"] == "every:30" and DEFAULT_JOBS["assets.warranty_check"] == "daily:08:00"
    assert JOBS["stock.low_check"] is job_stock_low_check and JOBS["assets.warranty_check"] is job_warranty_check


async def test_job_functions_commit_through_a_session_factory(db_session: AsyncSession):
    factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    org = await make_org(db_session)
    await _stock(db_session, org, 0, 3, "Toner")
    await job_stock_low_check(factory)
    await job_warranty_check(factory)
    assert len(await events(db_session, "stock.below_minimum")) == 1


async def test_default_rules_send_the_digest_to_admins_and_management(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr("app.notifications.fanout.quiet_until", lambda *a, **k: None)
    org = await make_org(db_session)
    admin = await make_user(db_session, is_admin=True)
    await seed_notification_rules(db_session)
    await _stock(db_session, org, 0, 3, "Toner")
    await check_stock_low(db_session)
    await db_session.commit()

    [event] = await events(db_session, "stock.below_minimum")
    rules = list((await db_session.execute(select(NotificationRule).where(NotificationRule.event_type == event.event_type))).scalars())
    assert len(rules) == 1 and rules[0].audience == ["admins", "role:Gestão"]
    plans = await plan_event(db_session, event, rules, {"in_app", "email"}, datetime.now(timezone.utc))
    assert {(p.user_id, p.channel) for p in plans} == {(admin.id, "in_app"), (admin.id, "email")}
    assert all(p.message["title"] == "1 item com estoque baixo" for p in plans)
