"""
MOD-11 — Canais externos: vínculo da conta (usuário) e configuração de Telegram e WhatsApp (administração).

Vínculo: o usuário autenticado gera um código, envia ao bot e só então o chat/telefone passa a ser dele
(ADR-013 §7.3). Configuração: tokens cifrados em `channel_configs`; nunca voltam pela API.
"""
import secrets
import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.repository import AuditRepository
from app.core.dependencies import get_current_user_id, require_permission
from app.core.exceptions import BusinessRuleException
from app.database import get_db
from app.notifications.channel_store import StoredChannel, load_channel, save_channel
from app.notifications.channels.slack import SLACK_CHANNEL
from app.notifications.channels.slack import api_call as slack_api_call
from app.notifications.channels.telegram import TELEGRAM_CHANNEL, api_call
from app.notifications.channels.whatsapp import DEFAULT_GRAPH_VERSION, WHATSAPP_CHANNEL, error_info, graph_call
from app.notifications.linking import create_link_code, unlink
from app.notifications.models import UserChannelAddress

router = APIRouter(prefix="/notifications", tags=["Notificações — Canais"])

DB = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[uuid.UUID, Depends(get_current_user_id)]
Manage = Depends(require_permission("notifications.manage"))
MASKED = "********"

LABELS = {TELEGRAM_CHANNEL: "Telegram", WHATSAPP_CHANNEL: "WhatsApp", SLACK_CHANNEL: "Slack"}


def is_ready(channel: str, stored: StoredChannel | None) -> bool:
    """Habilitado e com tudo o que o canal precisa para enviar e receber."""
    if stored is None or not stored.enabled:
        return False
    if channel == TELEGRAM_CHANNEL:
        return bool(stored.secrets.get("bot_token"))
    if channel == SLACK_CHANNEL:
        return bool(stored.secrets.get("bot_token") and stored.secrets.get("signing_secret"))
    return bool(
        stored.secrets.get("access_token") and stored.secrets.get("app_secret") and stored.config.get("phone_number_id")
    )


# --- Vínculo (usuário) ----------------------------------------------------------------------------


class LinkCodeResponse(BaseModel):
    code: str
    expires_at: datetime
    command: str
    deep_link: str | None = None


@router.get("/channels")
async def my_channels(db: DB, user_id: CurrentUser):
    """Canais externos disponíveis e se a conta está vinculada a cada um."""
    addresses = {
        row.channel: row
        for row in (await db.execute(select(UserChannelAddress).where(UserChannelAddress.user_id == user_id))).scalars()
    }
    result = []
    for channel, label in LABELS.items():
        stored = await load_channel(db, channel)
        address = addresses.get(channel)
        result.append(
            {
                "channel": channel,
                "label": label,
                "available": is_ready(channel, stored),
                "bot_username": stored.config.get("bot_username") if stored and channel == TELEGRAM_CHANNEL else None,
                "bot_name": stored.config.get("bot_name") if stored and channel == SLACK_CHANNEL else None,
                "display_phone": stored.config.get("display_phone") if stored and channel == WHATSAPP_CHANNEL else None,
                "linked": bool(address and address.verified_at),
                "linked_at": address.verified_at if address else None,
            }
        )
    return {"channels": result}


def _deep_link(channel: str, stored: StoredChannel, code: str) -> str | None:
    if channel == TELEGRAM_CHANNEL and stored.config.get("bot_username"):
        return f"https://t.me/{stored.config['bot_username']}?start={code}"
    if channel == WHATSAPP_CHANNEL:
        digits = "".join(ch for ch in str(stored.config.get("display_phone") or "") if ch.isdigit())
        if digits:
            return f"https://wa.me/{digits}?text={quote(f'vincular {code}')}"
    return None


@router.post("/channels/{channel}/link-code", response_model=LinkCodeResponse)
async def new_link_code(channel: str, db: DB, user_id: CurrentUser):
    if channel not in LABELS:
        raise BusinessRuleException("Canal sem suporte a vínculo.")
    stored = await load_channel(db, channel)
    if not is_ready(channel, stored):
        raise BusinessRuleException(f"O {LABELS[channel]} ainda não foi habilitado pela administração.")
    code, expires_at = await create_link_code(db, user_id, channel)
    await db.commit()
    return LinkCodeResponse(
        code=code,
        expires_at=expires_at,
        command=f"/vincular {code}" if channel == TELEGRAM_CHANNEL else f"vincular {code}",
        deep_link=_deep_link(channel, stored, code),
    )


@router.delete("/channels/{channel}", status_code=204)
async def unlink_channel(channel: str, db: DB, user_id: CurrentUser):
    if await unlink(db, user_id, channel):
        await AuditRepository(db).create(
            event_type="notifications.channel_unlinked", entity_type="notification", entity_id=user_id,
            data={"channel": channel}, user_id=user_id,
        )
    await db.commit()


async def _audit_config(db: AsyncSession, channel: str, enabled: bool, user_id: uuid.UUID) -> None:
    await AuditRepository(db).create(
        event_type=f"notifications.{channel}_configured", entity_type="notification",
        entity_id=uuid.uuid5(uuid.NAMESPACE_OID, f"channel:{channel}"), data={"enabled": enabled}, user_id=user_id,
    )


# --- Telegram (administração) ---------------------------------------------------------------------


class TelegramConfigIn(BaseModel):
    enabled: bool = False
    bot_token: str = Field("", max_length=200)  # vazio ou mascarado = manter o atual
    app_base_url: str = Field("", max_length=255)


class TelegramConfigOut(BaseModel):
    enabled: bool
    bot_token: str
    bot_username: str | None
    app_base_url: str


def _telegram_out(stored: StoredChannel | None) -> TelegramConfigOut:
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
    return _telegram_out(await load_channel(db, TELEGRAM_CHANNEL))


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
    await _audit_config(db, TELEGRAM_CHANNEL, body.enabled, user_id)
    await db.commit()
    return _telegram_out(await load_channel(db, TELEGRAM_CHANNEL))


# --- WhatsApp / Meta Cloud API (administração) ----------------------------------------------------


class WhatsAppConfigIn(BaseModel):
    enabled: bool = False
    access_token: str = Field("", max_length=1000)  # vazio ou mascarado = manter o atual
    app_secret: str = Field("", max_length=200)  # idem
    phone_number_id: str = Field("", max_length=50)
    graph_version: str = Field(DEFAULT_GRAPH_VERSION, pattern=r"^v\d+\.\d+$")
    template_name: str = Field("", max_length=100, pattern=r"^[a-z0-9_]*$")
    template_language: str = Field("pt_BR", max_length=10)
    app_base_url: str = Field("", max_length=255)


class WhatsAppConfigOut(BaseModel):
    enabled: bool
    access_token: str
    app_secret: str
    phone_number_id: str
    graph_version: str
    template_name: str
    template_language: str
    app_base_url: str
    display_phone: str | None
    verified_name: str | None
    verify_token: str | None
    webhook_path: str = "/api/v1/integrations/whatsapp/webhook"


def _whatsapp_out(stored: StoredChannel | None) -> WhatsAppConfigOut:
    cfg = stored.config if stored else {}
    secrets_ = stored.secrets if stored else {}
    return WhatsAppConfigOut(
        enabled=bool(stored and stored.enabled),
        access_token=MASKED if secrets_.get("access_token") else "",
        app_secret=MASKED if secrets_.get("app_secret") else "",
        phone_number_id=cfg.get("phone_number_id", ""),
        graph_version=cfg.get("graph_version") or DEFAULT_GRAPH_VERSION,
        template_name=cfg.get("template_name", ""),
        template_language=cfg.get("template_language") or "pt_BR",
        app_base_url=cfg.get("app_base_url", ""),
        display_phone=cfg.get("display_phone"),
        verified_name=cfg.get("verified_name"),
        verify_token=secrets_.get("verify_token"),  # só handshake do webhook; a rota exige notifications.manage
    )


@router.get("/whatsapp/config", response_model=WhatsAppConfigOut, dependencies=[Manage])
async def get_whatsapp_config(db: DB):
    return _whatsapp_out(await load_channel(db, WHATSAPP_CHANNEL))


@router.put("/whatsapp/config", response_model=WhatsAppConfigOut, dependencies=[Manage])
async def update_whatsapp_config(body: WhatsAppConfigIn, db: DB, user_id: CurrentUser):
    current = await load_channel(db, WHATSAPP_CHANNEL)
    old = current.secrets if current else {}

    def keep(new: str, key: str) -> str:
        new = new.strip()
        return old.get(key, "") if (not new or new == MASKED) else new

    token, app_secret = keep(body.access_token, "access_token"), keep(body.app_secret, "app_secret")
    phone_id = body.phone_number_id.strip()
    if body.enabled and not (token and app_secret and phone_id):
        raise BusinessRuleException("Para habilitar o WhatsApp informe o token de acesso, o App Secret e o Phone Number ID.")

    cfg = dict(current.config) if current else {}
    changed = token != old.get("access_token") or phone_id != cfg.get("phone_number_id") or body.graph_version != cfg.get("graph_version")
    if token and phone_id and changed:
        # Valida o par token/número na Graph API e descobre o telefone exibido (usado no link wa.me).
        status, resp = await graph_call(
            token, "GET", phone_id, params={"fields": "display_phone_number,verified_name"}, version=body.graph_version
        )
        if status != 200:
            _, message = error_info(resp)
            raise BusinessRuleException(f"A Meta recusou o token ou o Phone Number ID: {message or status}")
        cfg["display_phone"] = resp.get("display_phone_number")
        cfg["verified_name"] = resp.get("verified_name")

    cfg.update(
        phone_number_id=phone_id, graph_version=body.graph_version, template_name=body.template_name.strip(),
        template_language=body.template_language.strip() or "pt_BR", app_base_url=body.app_base_url.strip(),
    )
    secrets_ = {k: v for k, v in {"access_token": token, "app_secret": app_secret}.items() if v}
    secrets_["verify_token"] = old.get("verify_token") or secrets.token_urlsafe(24)
    await save_channel(db, WHATSAPP_CHANNEL, body.enabled, cfg, secrets_)
    await _audit_config(db, WHATSAPP_CHANNEL, body.enabled, user_id)
    await db.commit()
    return _whatsapp_out(await load_channel(db, WHATSAPP_CHANNEL))


# --- Slack (administração) ------------------------------------------------------------------------


class SlackConfigIn(BaseModel):
    enabled: bool = False
    bot_token: str = Field("", max_length=300)  # vazio ou mascarado = manter o atual
    signing_secret: str = Field("", max_length=200)  # idem
    app_base_url: str = Field("", max_length=255)


class SlackConfigOut(BaseModel):
    enabled: bool
    bot_token: str
    signing_secret: str
    app_base_url: str
    bot_name: str | None
    team_name: str | None
    events_path: str = "/api/v1/integrations/slack/events"


def _slack_out(stored: StoredChannel | None) -> SlackConfigOut:
    cfg = stored.config if stored else {}
    secrets_ = stored.secrets if stored else {}
    return SlackConfigOut(
        enabled=bool(stored and stored.enabled),
        bot_token=MASKED if secrets_.get("bot_token") else "",
        signing_secret=MASKED if secrets_.get("signing_secret") else "",
        app_base_url=cfg.get("app_base_url", ""),
        bot_name=cfg.get("bot_name"),
        team_name=cfg.get("team_name"),
    )


@router.get("/slack/config", response_model=SlackConfigOut, dependencies=[Manage])
async def get_slack_config(db: DB):
    return _slack_out(await load_channel(db, SLACK_CHANNEL))


@router.put("/slack/config", response_model=SlackConfigOut, dependencies=[Manage])
async def update_slack_config(body: SlackConfigIn, db: DB, user_id: CurrentUser):
    current = await load_channel(db, SLACK_CHANNEL)
    old = current.secrets if current else {}

    def keep(new: str, key: str) -> str:
        new = new.strip()
        return old.get(key, "") if (not new or new == MASKED) else new

    token, signing = keep(body.bot_token, "bot_token"), keep(body.signing_secret, "signing_secret")
    if body.enabled and not (token and signing):
        raise BusinessRuleException("Para habilitar o Slack informe o token do bot e o Signing Secret.")

    cfg = dict(current.config) if current else {}
    if token and token != old.get("bot_token"):
        # Token novo: valida em auth.test antes de gravar e descobre o nome do app e do workspace.
        status, resp = await slack_api_call(token, "auth.test")
        if status != 200 or not resp.get("ok"):
            raise BusinessRuleException(f"O Slack recusou o token: {resp.get('error', 'sem resposta')}")
        cfg["bot_name"] = resp.get("user")
        cfg["team_name"] = resp.get("team")

    cfg["app_base_url"] = body.app_base_url.strip()
    secrets_ = {k: v for k, v in {"bot_token": token, "signing_secret": signing}.items() if v}
    await save_channel(db, SLACK_CHANNEL, body.enabled, cfg, secrets_)
    await _audit_config(db, SLACK_CHANNEL, body.enabled, user_id)
    await db.commit()
    return _slack_out(await load_channel(db, SLACK_CHANNEL))
