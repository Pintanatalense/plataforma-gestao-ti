"""
Canal "Navegador" (Web Push): inscrição do aparelho da própria pessoa. Só opera sobre o usuário autenticado.
"""
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user_id
from app.core.exceptions import BusinessRuleException
from app.database import get_db
from app.identity.models import UserAccount
from app.notifications.channels.webpush import WEBPUSH_CHANNEL, address_for, endpoint_allowed, ensure_vapid
from app.notifications.direct import enqueue_direct_message
from app.notifications.models import PushSubscription, UserChannelAddress

router = APIRouter(prefix="/notifications/push", tags=["Notificações — Navegador"])

DB = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[uuid.UUID, Depends(get_current_user_id)]
MAX_DEVICES_PER_USER = 10


class Keys(BaseModel):
    p256dh: str = Field(..., min_length=20, max_length=200)
    auth: str = Field(..., min_length=8, max_length=100)


class SubscribeIn(BaseModel):
    endpoint: str = Field(..., min_length=20, max_length=600)
    keys: Keys


class UnsubscribeIn(BaseModel):
    endpoint: str = Field(..., min_length=20, max_length=600)


async def _vapid_subject(db: AsyncSession) -> str:
    """A claim `sub` do VAPID identifica quem opera o servidor: usa o e-mail do primeiro administrador."""
    email = (
        await db.execute(select(UserAccount.email).where(UserAccount.is_admin.is_(True)).order_by(UserAccount.created_at).limit(1))
    ).scalar_one_or_none()
    return f"mailto:{email}" if email else "mailto:admin@localhost"


async def _count(db: AsyncSession, user_id: uuid.UUID) -> int:
    return (await db.execute(select(func.count()).select_from(PushSubscription).where(PushSubscription.user_id == user_id))).scalar_one()


@router.get("/public-key")
async def public_key(db: DB, _user: CurrentUser):
    """Chave pública VAPID que o navegador usa para assinar a inscrição. Gera o par na primeira chamada."""
    stored = await ensure_vapid(db, await _vapid_subject(db))
    await db.commit()
    return {"public_key": stored.config["public_key"]}


@router.get("/status")
async def status(db: DB, user_id: CurrentUser):
    return {"devices": await _count(db, user_id)}


@router.post("/subscribe", status_code=201)
async def subscribe(
    body: SubscribeIn, db: DB, user_id: CurrentUser, user_agent: Annotated[str | None, Header()] = None
):
    if not endpoint_allowed(body.endpoint):
        raise BusinessRuleException("Este navegador usa um serviço de notificação não suportado.")

    existing = (await db.execute(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))).scalar_one_or_none()
    if existing is None and await _count(db, user_id) >= MAX_DEVICES_PER_USER:
        raise BusinessRuleException(f"Limite de {MAX_DEVICES_PER_USER} navegadores por conta. Desative algum antes.")

    previous_owner = existing.user_id if existing else None
    if existing is None:
        db.add(PushSubscription(user_id=user_id, endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth, user_agent=(user_agent or "")[:300] or None))
    else:  # o aparelho mudou de dono (outra conta no mesmo navegador) ou renovou as chaves
        existing.user_id, existing.p256dh, existing.auth = user_id, body.keys.p256dh, body.keys.auth
        existing.user_agent = (user_agent or "")[:300] or existing.user_agent
    await db.flush()

    # Endereço único por usuário no hub: existe enquanto houver ao menos um aparelho.
    address = (
        await db.execute(select(UserChannelAddress).where(UserChannelAddress.user_id == user_id, UserChannelAddress.channel == WEBPUSH_CHANNEL))
    ).scalar_one_or_none()
    if address is None:
        db.add(UserChannelAddress(user_id=user_id, channel=WEBPUSH_CHANNEL, address=address_for(user_id), verified_at=datetime.now(timezone.utc)))
    if previous_owner and previous_owner != user_id and not await _count(db, previous_owner):
        await db.execute(delete(UserChannelAddress).where(UserChannelAddress.user_id == previous_owner, UserChannelAddress.channel == WEBPUSH_CHANNEL))
    await db.commit()
    return {"devices": await _count(db, user_id)}


@router.post("/unsubscribe")
async def unsubscribe(body: UnsubscribeIn, db: DB, user_id: CurrentUser):
    await db.execute(delete(PushSubscription).where(PushSubscription.endpoint == body.endpoint, PushSubscription.user_id == user_id))
    remaining = await _count(db, user_id)
    if remaining == 0:
        await db.execute(delete(UserChannelAddress).where(UserChannelAddress.user_id == user_id, UserChannelAddress.channel == WEBPUSH_CHANNEL))
    await db.commit()
    return {"devices": remaining}


@router.post("/test", status_code=202)
async def send_test(db: DB, user_id: CurrentUser):
    """Enfileira um pop-up de teste para os navegadores da própria pessoa (passa pelo worker, como qualquer entrega)."""
    if not await _count(db, user_id):
        raise BusinessRuleException("Ative as notificações neste navegador antes de testar.")
    await enqueue_direct_message(
        db, WEBPUSH_CHANNEL, address_for(user_id), user_id,
        "Se você está vendo isto, o pop-up do navegador está funcionando.", actor_user_id=user_id,
        entity_type="push_test", entity_id=None,
    )
    await db.commit()
    return {"queued": True}
