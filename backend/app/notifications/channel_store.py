"""Leitura e gravação de `channel_configs` (segredos cifrados com Fernet)."""
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_json, encrypt_json
from app.notifications.models import ChannelConfig


@dataclass
class StoredChannel:
    channel: str
    enabled: bool = False
    config: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, Any] = field(default_factory=dict)


async def load_channel(session: AsyncSession, channel: str) -> StoredChannel | None:
    row = (await session.execute(select(ChannelConfig).where(ChannelConfig.channel == channel))).scalar_one_or_none()
    if row is None:
        return None
    secrets = decrypt_json(row.secrets_encrypted) if row.secrets_encrypted else {}
    return StoredChannel(channel=channel, enabled=row.enabled, config=dict(row.config or {}), secrets=secrets)


async def save_channel(
    session: AsyncSession, channel: str, enabled: bool, config: dict[str, Any], secrets: dict[str, Any]
) -> None:
    """Grava a configuração (não faz commit)."""
    row = (await session.execute(select(ChannelConfig).where(ChannelConfig.channel == channel))).scalar_one_or_none()
    encrypted = encrypt_json(secrets) if secrets else None
    if row is None:
        session.add(ChannelConfig(channel=channel, enabled=enabled, config=config, secrets_encrypted=encrypted))
    else:
        row.enabled = enabled
        row.config = config
        row.secrets_encrypted = encrypted
    await session.flush()
