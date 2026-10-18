"""
Vínculo de identidade com canais externos por código de uso único (ADR-013 §7.3).

O usuário autenticado gera o código no sistema e o envia pelo canal; só então o endereço do canal
(chat id) passa a pertencer à conta. Nada de vínculo por matrícula/telefone digitado no chat.
"""
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import BusinessRuleException
from app.notifications.models import ChannelLinkCode, UserChannelAddress

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O/1/I: o código é digitado/lido por pessoas
CODE_LENGTH = 6
CODE_TTL = timedelta(minutes=10)
MAX_CODES_PER_HOUR = 5


def normalize_code(raw: str) -> str:
    return "".join(ch for ch in raw.upper() if ch.isalnum())


def hash_code(channel: str, code: str) -> str:
    """HMAC com a SECRET_KEY: o espaço de códigos é pequeno e um hash simples cairia em força bruta se o banco vazasse."""
    key = get_settings().SECRET_KEY.encode()
    return hmac.new(key, f"{channel}:{normalize_code(code)}".encode(), hashlib.sha256).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def create_link_code(session: AsyncSession, user_id: uuid.UUID, channel: str) -> tuple[str, datetime]:
    """Gera um código novo (invalida os anteriores ainda não usados). O commit fica com o chamador."""
    now = datetime.now(timezone.utc)
    recent = (
        await session.execute(
            select(func.count()).select_from(ChannelLinkCode).where(
                ChannelLinkCode.user_id == user_id,
                ChannelLinkCode.channel == channel,
                ChannelLinkCode.created_at >= now - timedelta(hours=1),
            )
        )
    ).scalar_one()
    if recent >= MAX_CODES_PER_HOUR:
        raise BusinessRuleException("Muitos códigos gerados na última hora. Aguarde e tente novamente.")

    await session.execute(
        update(ChannelLinkCode)
        .where(ChannelLinkCode.user_id == user_id, ChannelLinkCode.channel == channel, ChannelLinkCode.used_at.is_(None))
        .values(used_at=now)
    )
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    expires_at = now + CODE_TTL
    session.add(
        ChannelLinkCode(user_id=user_id, channel=channel, code_hash=hash_code(channel, code), expires_at=expires_at)
    )
    await session.flush()
    return code, expires_at


class LinkResult:
    OK = "ok"
    INVALID = "invalid"
    ALREADY_LINKED_ELSEWHERE = "taken"


async def redeem_link_code(
    session: AsyncSession, channel: str, address: str, raw_code: str
) -> tuple[str, uuid.UUID | None]:
    """Consome o código e grava o endereço. Retorna (resultado, user_id). O commit fica com o chamador."""
    now = datetime.now(timezone.utc)
    code_row = (
        await session.execute(
            select(ChannelLinkCode).where(
                ChannelLinkCode.channel == channel,
                ChannelLinkCode.code_hash == hash_code(channel, raw_code),
                ChannelLinkCode.used_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if code_row is None or _aware(code_row.expires_at) <= now:
        return LinkResult.INVALID, None

    owner = (
        await session.execute(
            select(UserChannelAddress).where(UserChannelAddress.channel == channel, UserChannelAddress.address == address)
        )
    ).scalar_one_or_none()
    if owner is not None and owner.user_id != code_row.user_id:
        return LinkResult.ALREADY_LINKED_ELSEWHERE, None

    code_row.used_at = now
    existing = (
        await session.execute(
            select(UserChannelAddress).where(
                UserChannelAddress.user_id == code_row.user_id, UserChannelAddress.channel == channel
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            UserChannelAddress(user_id=code_row.user_id, channel=channel, address=address, verified_at=now)
        )
    else:  # troca de telefone/chat: o novo endereço substitui o antigo, sempre com novo código
        existing.address = address
        existing.verified_at = now
    await session.flush()
    return LinkResult.OK, code_row.user_id


async def unlink(session: AsyncSession, user_id: uuid.UUID, channel: str) -> bool:
    row = (
        await session.execute(
            select(UserChannelAddress).where(UserChannelAddress.user_id == user_id, UserChannelAddress.channel == channel)
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def load_addresses(session: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, dict[str, str]]:
    """Endereços VERIFICADOS por usuário e canal. Endereço sem verified_at nunca recebe mensagem."""
    if not user_ids:
        return {}
    rows = (
        await session.execute(
            select(UserChannelAddress).where(
                UserChannelAddress.user_id.in_(user_ids), UserChannelAddress.verified_at.is_not(None)
            )
        )
    ).scalars()
    result: dict[uuid.UUID, dict[str, str]] = {}
    for row in rows:
        result.setdefault(row.user_id, {})[row.channel] = row.address
    return result
