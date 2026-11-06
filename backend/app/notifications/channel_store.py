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


LIMITS_KEY = "limits"  # limites definidos pelo administrador na tela de gateways (ADR-025 M2)


def rate_override(config: dict[str, Any] | None) -> float | None:
    """Envios por segundo definidos pelo administrador para o canal, se houver."""
    value = ((config or {}).get(LIMITS_KEY) or {}).get("rate_per_second")
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


async def save_channel(
    session: AsyncSession, channel: str, enabled: bool, config: dict[str, Any], secrets: dict[str, Any]
) -> None:
    """Grava a configuração (não faz commit).

    Os limites (`config['limits']`) pertencem à tela de gateways: quem grava a configuração do canal sem mencioná-los
    (as abas de cada canal montam o `config` do zero) os mantém.
    """
    row = (await session.execute(select(ChannelConfig).where(ChannelConfig.channel == channel))).scalar_one_or_none()
    if row is not None and LIMITS_KEY not in config and LIMITS_KEY in (row.config or {}):
        config = {**config, LIMITS_KEY: row.config[LIMITS_KEY]}
    encrypted = encrypt_json(secrets) if secrets else None
    if row is None:
        session.add(ChannelConfig(channel=channel, enabled=enabled, config=config, secrets_encrypted=encrypted))
    else:
        row.enabled = enabled
        row.config = config
        row.secrets_encrypted = encrypted
    await session.flush()
