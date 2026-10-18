"""
MOD-11 — Canais externos: vínculo da conta (usuário) e configuração do Telegram (administração).

Vínculo: o usuário autenticado gera um código, envia ao bot e só então o chat passa a ser dele
(ADR-013 §7.3). Configuração: token do bot cifrado em `channel_configs`; nunca volta pela API.
"""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.repository import AuditRepository
from app.core.dependencies import get_current_user_id, require_permission
from app.core.exceptions import BusinessRuleException
from app.database import get_db
from app.notifications.channel_store import load_channel, save_channel
from app.notifications.channels.telegram import TELEGRAM_CHANNEL, api_call
from app.notifications.linking import create_link_code, unlink
from app.notifications.models import UserChannelAddress

router = APIRouter(prefix="/notifications", tags=["Notificações — Canais"])

DB = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[uuid.UUID, Depends(get_current_user_id)]
Manage = Depends(require_permission("notifications.manage"))
MASKED = "********"


# --- Vínculo (usuário) ----------------------------------------------------------------------------


class LinkCodeResponse(BaseModel):
    code: str
    expires_at: datetime
    command: str
    deep_link: str | None = None


@router.get("/channels")
async def my_channels(db: DB, user_id: CurrentUser):
    """Canais externos disponíveis e se a conta está vinculada a cada um."""
    stored = await load_channel(db, TELEGRAM_CHANNEL)
    address = (
        await db.execute(
            select(UserChannelAddress).where(
                UserChannelAddress.user_id == user_id, UserChannelAddress.channel == TELEGRAM_CHANNEL
            )
        )
    ).scalar_one_or_none()
    available = bool(stored and stored.enabled and stored.secrets.get("bot_token"))
    return {
        "channels": [
            {
                "channel": TELEGRAM_CHANNEL,
                "label": "Telegram",
                "available": available,
                "bot_username": (stored.config.get("bot_username") if stored else None),
                "linked": bool(address and address.verified_at),
                "linked_at": address.verified_at if address else None,
            }
        ]
    }


@router.post("/channels/{channel}/link-code", response_model=LinkCodeResponse)
async def new_link_code(channel: str, db: DB, user_id: CurrentUser):
    if channel != TELEGRAM_CHANNEL:
        raise BusinessRuleException("Canal sem suporte a vínculo.")
    stored = await load_channel(db, channel)
    if not (stored and stored.enabled and stored.secrets.get("bot_token")):
        raise BusinessRuleException("O Telegram ainda não foi habilitado pela administração.")
    code, expires_at = await create_link_code(db, user_id, channel)
    await db.commit()
    username = stored.config.get("bot_username")
    return LinkCodeResponse(
        code=code,
        expires_at=expires_at,
        command=f"/vincular {code}",
        deep_link=f"https://t.me/{username}?start={code}" if username else None,
    )


@router.delete("/channels/{channel}", status_code=204)
async def unlink_channel(channel: str, db: DB, user_id: CurrentUser):
    if await unlink(db, user_id, channel):
        await AuditRepository(db).create(
            event_type="notifications.channel_unlinked", entity_type="notification", entity_id=user_id,
            data={"channel": channel}, user_id=user_id,
        )
    await db.commit()


# --- Configuração do Telegram (administração) -----------------------------------------------------


class TelegramConfigIn(BaseModel):
    enabled: bool = False
    bot_token: str = Field("", max_length=200)  # vazio ou mascarado = manter o atual
    app_base_url: str = Field("", max_length=255)


class TelegramConfigOut(BaseModel):
    enabled: bool
    bot_token: str
    bot_username: str | None
    app_base_url: str


def _out(stored) -> TelegramConfigOut:
    if stored is None:
        return TelegramConfigOut(enabled=False, bot_token="", bot_username=None, app_base_url="")
    return TelegramConfigOut(
        enabled=stored.enabled,
        bot_token=MASKED if stored.secrets.get("bot_token") else "",
        bot_username=stored.config.get("bot_username"),
        app_base_url=stored.config.get("app_base_url", ""),
    )


@router.get("/telegram/config", response_model=TelegramConfigOut, dependencies=[Manage])
async def get_telegram_config(db: DB):
    return _out(await load_channel(db, TELEGRAM_CHANNEL))


@router.put("/telegram/config", response_model=TelegramConfigOut, dependencies=[Manage])
async def update_telegram_config(body: TelegramConfigIn, db: DB, user_id: CurrentUser):
    current = await load_channel(db, TELEGRAM_CHANNEL)
    token = body.bot_token.strip()
    if not token or token == MASKED:
        token = (current.secrets.get("bot_token") if current else "") or ""
    if body.enabled and not token:
        raise BusinessRuleException("Informe o token do bot para habilitar o Telegram.")

    username = current.config.get("bot_username") if current else None
    if token and (not current or token != current.secrets.get("bot_token")):
        # Token novo: valida na API antes de gravar e descobre o @ do bot (usado no link de vínculo).
        status, resp = await api_call(token, "getMe")
        if status != 200 or not resp.get("ok"):
            raise BusinessRuleException(f"O Telegram recusou o token: {resp.get('description', 'sem resposta')}")
        username = resp["result"].get("username")

    await save_channel(
        db, TELEGRAM_CHANNEL, body.enabled,
        {"bot_username": username, "app_base_url": body.app_base_url.strip()},
        {"bot_token": token} if token else {},
    )
    await AuditRepository(db).create(
        event_type="notifications.telegram_configured", entity_type="notification",
        entity_id=uuid.uuid5(uuid.NAMESPACE_OID, "channel:telegram"), data={"enabled": body.enabled}, user_id=user_id,
    )
    await db.commit()
    return _out(await load_channel(db, TELEGRAM_CHANNEL))
