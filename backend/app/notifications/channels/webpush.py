"""
Canal "Navegador" (Web Push, RFC 8030/8291 + VAPID): pop-up do sistema operacional mesmo com a aba fechada,
enquanto o navegador estiver em execução. Sem conta em serviço de terceiros: as chaves VAPID são geradas aqui e
ficam cifradas em `channel_configs['webpush']`; a entrega passa pelo serviço de push do próprio navegador.

Uma pessoa pode ter vários aparelhos (`push_subscriptions`); o endereço do hub é um só por usuário
(`webpush:<user_id>`), válido enquanto houver ao menos um aparelho.
"""
import asyncio
import base64
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import ClassVar
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.channel_store import StoredChannel, load_channel, save_channel
from app.notifications.channels.base import (
    AdapterContext,
    Capabilities,
    ChannelHealth,
    DeliveryResult,
    Message,
    Recipient,
)
from app.notifications.models import PushSubscription, UserChannelAddress

logger = logging.getLogger(__name__)

WEBPUSH_CHANNEL = "webpush"
MAX_BODY = 180
TTL_SECONDS = 12 * 3600  # aparelho desligado: a mensagem vence em 12 h em vez de chegar velha

# O servidor faz POST no endpoint informado pelo navegador: só aceita os serviços de push conhecidos
# (evita que alguém cadastre uma URL interna e use o servidor como proxy, SSRF).
PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    "push.services.mozilla.com",
    "notify.windows.com",
    "push.apple.com",
)


def endpoint_allowed(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        return False
    return any(host == s or host.endswith("." + s) for s in PUSH_HOST_SUFFIXES)


def address_for(user_id: uuid.UUID | str) -> str:
    return f"{WEBPUSH_CHANNEL}:{user_id}"


def generate_vapid() -> tuple[str, str]:
    """(chave privada PEM, chave pública no formato que o navegador espera: base64url do ponto não comprimido)."""
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    point = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return pem, base64.urlsafe_b64encode(point).rstrip(b"=").decode()


async def ensure_vapid(session: AsyncSession, subject: str) -> StoredChannel:
    """Garante o canal provisionado (gera as chaves na primeira vez). Sem commit."""
    stored = await load_channel(session, WEBPUSH_CHANNEL)
    if stored and stored.secrets.get("private_key") and stored.config.get("public_key"):
        return stored
    private_pem, public_key = generate_vapid()
    await save_channel(session, WEBPUSH_CHANNEL, True, {"public_key": public_key, "subject": subject}, {"private_key": private_pem})
    return await load_channel(session, WEBPUSH_CHANNEL)  # type: ignore[return-value]


def send_push(subscription: dict, payload: dict, private_pem: str, subject: str, urgency: str) -> tuple[int, str]:
    """Envio síncrono de UM aparelho (roda em thread). Devolve (status HTTP, detalhe); status 0 = falha de rede."""
    from py_vapid import Vapid02
    from pywebpush import WebPushException, webpush

    try:
        response = webpush(
            subscription_info=subscription,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=Vapid02.from_pem(private_pem.encode()),
            vapid_claims={"sub": subject},
            ttl=TTL_SECONDS,
            headers={"Urgency": urgency},
            timeout=15,
        )
        return getattr(response, "status_code", 201), ""
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", 0) or 0
        return status, str(exc)[:200]
    except Exception as exc:  # rede, DNS, TLS...
        return 0, f"{type(exc).__name__}: {exc}"[:200]


def build_payload(message: Message) -> dict:
    body = message.body_text.replace("\n", " ").strip()
    if len(body) > MAX_BODY:
        body = body[: MAX_BODY - 1] + "…"
    return {"title": message.title or "Plataforma de Gestão de TI", "body": body, "url": message.link or "/", "priority": message.priority}


class WebPushAdapter:
    channel: ClassVar[str] = WEBPUSH_CHANNEL
    capabilities: ClassVar[Capabilities] = Capabilities(inbound=False, max_len=MAX_BODY, rate_per_second=20.0)

    def __init__(self, ctx: AdapterContext) -> None:
        self._session_factory = ctx.session_factory

    async def send(self, recipient: Recipient, message: Message) -> DeliveryResult:
        async with self._session_factory() as session:
            stored = await load_channel(session, WEBPUSH_CHANNEL)
            if stored is None or not stored.enabled or not stored.secrets.get("private_key"):
                return DeliveryResult("permanent", error="Canal Navegador desabilitado ou sem chaves.")
            if not recipient.user_id:
                return DeliveryResult("permanent", error="Entrega sem usuário.")
            user_id = uuid.UUID(recipient.user_id)
            subs = list((await session.execute(select(PushSubscription).where(PushSubscription.user_id == user_id))).scalars())
            if not subs:
                return DeliveryResult("permanent", error="Nenhum navegador ativado para este usuário.")

            payload = build_payload(message)
            urgency = "high" if message.priority in ("high", "critical") else "normal"
            subject = stored.config.get("subject") or "mailto:admin@localhost"
            outcomes = await asyncio.gather(
                *(
                    asyncio.to_thread(
                        send_push,
                        {"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}},
                        payload, stored.secrets["private_key"], subject, urgency,
                    )
                    for s in subs
                )
            )

            delivered, transient, errors = 0, False, []
            for sub, (status, detail) in zip(subs, outcomes, strict=True):
                if 200 <= status < 300:
                    delivered += 1
                    sub.last_used_at = datetime.now(timezone.utc)
                elif status in (404, 410):  # inscrição expirada ou revogada pelo navegador
                    await session.delete(sub)
                else:
                    errors.append(f"{status or 'rede'} {detail}".strip())
                    if status in (0, 429) or status >= 500:
                        transient = True
            await session.flush()
            if not (await session.execute(select(PushSubscription.id).where(PushSubscription.user_id == user_id).limit(1))).first():
                await session.execute(delete(UserChannelAddress).where(
                    UserChannelAddress.user_id == user_id, UserChannelAddress.channel == WEBPUSH_CHANNEL))
            await session.commit()

        if delivered:
            return DeliveryResult("ok")
        if transient:
            return DeliveryResult("retryable", error="; ".join(errors) or "falha temporária")
        return DeliveryResult("permanent", error="; ".join(errors) or "inscrições expiradas")

    async def health(self) -> ChannelHealth:
        async with self._session_factory() as session:
            stored = await load_channel(session, WEBPUSH_CHANNEL)
        if stored is None or not stored.enabled:
            return ChannelHealth(ok=False, detail="Ninguém ativou ainda.")
        return ChannelHealth(ok=bool(stored.secrets.get("private_key")), detail="Chaves VAPID prontas.")
