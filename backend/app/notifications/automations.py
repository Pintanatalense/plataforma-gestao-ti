"""
Automações proativas (ADR-013 §10.2, Fase F): jobs do worker que detectam um fato e emitem UM evento
(resumo) por execução. O fato só é avisado uma vez: `automation_marks` guarda "já avisei" e é rearmado
quando o fato deixa de existir (estoque reabastecido) ou muda (garantia renovada).

Fora de escopo por dependerem de dados que ainda não existem: SLA (prazos não decididos), termo de
responsabilidade e divergência de inventário.
"""
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetStatus
from app.notifications.channels.base import SessionFactory
from app.notifications.models import AutomationMark
from app.notifications.outbox import emit_event
from app.stock.models import StockItem

logger = logging.getLogger(__name__)

WARRANTY_THRESHOLDS_DAYS = (30, 7)  # do maior para o menor
MAX_ITEMS_IN_EVENT = 10
MARK_RETENTION_DAYS = 400


async def _marks(session: AsyncSession, prefix: str) -> set[str]:
    rows = await session.execute(select(AutomationMark.key).where(AutomationMark.key.like(f"{prefix}%")))
    return set(rows.scalars())


async def check_stock_low(session: AsyncSession) -> int:
    """Itens com quantidade <= mínimo (mesmo critério da tela de estoque). Retorna quantos itens novos entraram em alerta."""
    items = list(
        (await session.execute(select(StockItem).where(StockItem.min_quantity > 0, StockItem.quantity <= StockItem.min_quantity)))
        .scalars()
    )
    low_keys = {f"stock.low:{item.id}" for item in items}
    marked = await _marks(session, "stock.low:")

    # Rearma o que voltou ao normal (ou deixou de existir/ter mínimo).
    recovered = marked - low_keys
    if recovered:
        await session.execute(delete(AutomationMark).where(AutomationMark.key.in_(recovered)))

    fresh = sorted((i for i in items if f"stock.low:{i.id}" not in marked), key=lambda i: (i.quantity - i.min_quantity, i.name))
    if fresh:
        await emit_event(
            session,
            event_type="stock.below_minimum",
            entity_type="stock",
            entity_id=None,
            payload={
                "total": len(fresh),
                "items": [{"id": str(i.id), "name": i.name, "quantity": i.quantity, "min_quantity": i.min_quantity} for i in fresh[:MAX_ITEMS_IN_EVENT]],
            },
            priority="high",
        )
        session.add_all(AutomationMark(key=f"stock.low:{i.id}") for i in fresh)
    await session.flush()
    return len(fresh)


async def check_warranties(session: AsyncSession, today: date | None = None) -> int:
    """Garantias que entraram na faixa de 30 ou 7 dias. Retorna quantos ativos foram avisados."""
    today = today or datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=max(WARRANTY_THRESHOLDS_DAYS))
    assets = list(
        (
            await session.execute(
                select(Asset).where(
                    Asset.is_active.is_(True),
                    Asset.status != AssetStatus.DECOMMISSIONED.value,
                    Asset.warranty_expires.is_not(None),
                    Asset.warranty_expires >= today,
                    Asset.warranty_expires <= horizon,
                )
            )
        ).scalars()
    )
    marked = await _marks(session, "warranty:")
    fresh: list[tuple[Asset, int, list[str]]] = []
    for asset in assets:
        days_left = (asset.warranty_expires - today).days
        # Faixas já atingidas: um ativo cadastrado a 5 dias do fim recebe UM aviso (faixa de 7), não dois.
        reached = [t for t in WARRANTY_THRESHOLDS_DAYS if days_left <= t]
        keys = [f"warranty:{asset.id}:{asset.warranty_expires.isoformat()}:{t}" for t in reached]
        if keys and not (set(keys) <= marked):
            fresh.append((asset, days_left, keys))

    if fresh:
        fresh.sort(key=lambda row: row[1])
        await emit_event(
            session,
            event_type="asset.warranty_expiring",
            entity_type="asset",
            entity_id=None,
            payload={
                "total": len(fresh),
                "items": [
                    {"id": str(a.id), "tag": a.tag, "name": a.name, "days_left": days, "expires": a.warranty_expires.isoformat()}
                    for a, days, _ in fresh[:MAX_ITEMS_IN_EVENT]
                ],
            },
            priority="normal" if all(days > 7 for _, days, _ in fresh) else "high",
        )
        for _, _, keys in fresh:
            session.add_all(AutomationMark(key=key) for key in keys if key not in marked)
    await session.flush()
    return len(fresh)


async def purge_old_marks(session: AsyncSession) -> None:
    """Marcas de garantia de anos passados não rearmam nada; só ocupam espaço."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=MARK_RETENTION_DAYS)
    await session.execute(delete(AutomationMark).where(AutomationMark.key.like("warranty:%"), AutomationMark.created_at < cutoff))


async def job_stock_low_check(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        await check_stock_low(session)
        await session.commit()


async def job_warranty_check(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        await check_warranties(session)
        await purge_old_marks(session)
        await session.commit()
