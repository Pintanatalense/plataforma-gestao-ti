"""
Webhook público da Events API do Slack.

- Toda requisição (inclusive o `url_verification`) só é aceita com assinatura válida:
  `X-Slack-Signature` = `v0=` + HMAC-SHA256(signing_secret, "v0:{timestamp}:{corpo bruto}").
- `X-Slack-Request-Timestamp` fora de 5 min = 401 (replay).
- Só mensagens diretas de pessoas (não de bots) viram conversa. A resposta nunca volta aqui: vira entrega.
- O Slack reenvia se não receber 2xx em 3 s; a deduplicação por canal+`ts` torna a reentrega inofensiva.
"""
import hashlib
import hmac
import json
import logging
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.notifications.channel_store import load_channel
from app.notifications.channels.slack import SLACK_CHANNEL
from app.notifications.conversation.inbound import process_inbound
from app.notifications.telegram_poller import SenderRateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/slack", tags=["Slack"])

REPLAY_WINDOW_SECONDS = 300
_limiter = SenderRateLimiter()  # por processo da API


def signature_valid(signing_secret: str | None, timestamp: str | None, signature: str | None, raw_body: bytes, now: float | None = None) -> bool:
    if not signing_secret or not timestamp or not signature or not signature.startswith("v0="):
        return False
    try:
        age = abs((now if now is not None else time.time()) - int(timestamp))
    except ValueError:
        return False
    if age > REPLAY_WINDOW_SECONDS:
        return False
    base = b"v0:" + timestamp.encode() + b":" + raw_body
    expected = hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("v0="))


def extract_direct_message(payload: dict[str, Any]) -> tuple[str, str, str] | None:
    """(id da mensagem, id do usuário, texto) de uma mensagem direta de pessoa; None para o resto."""
    if payload.get("type") != "event_callback":
        return None
    event = payload.get("event") or {}
    if event.get("type") != "message" or event.get("channel_type") != "im":
        return None
    if event.get("subtype") or event.get("bot_id"):  # edição, remoção, mensagens do próprio app...
        return None
    user, text, ts, channel = event.get("user"), event.get("text"), event.get("ts"), event.get("channel")
    if not (isinstance(user, str) and isinstance(text, str) and ts and channel):
        return None
    return f"{channel}:{ts}", user, text


@router.post("/events", include_in_schema=False)
async def receive_event(request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    raw = await request.body()  # a assinatura é sobre os bytes exatos
    stored = await load_channel(db, SLACK_CHANNEL)
    if stored is None or not stored.enabled:
        return Response(status_code=404)
    if not signature_valid(
        stored.secrets.get("signing_secret"),
        request.headers.get("X-Slack-Request-Timestamp"),
        request.headers.get("X-Slack-Signature"),
        raw,
    ):
        logger.warning("Slack webhook com assinatura inválida ou expirada de %s", request.client.host if request.client else "?")
        return Response(status_code=401)

    try:
        payload = json.loads(raw)
    except ValueError:
        return Response(status_code=400)

    if payload.get("type") == "url_verification":
        return PlainTextResponse(str(payload.get("challenge", "")))

    message = extract_direct_message(payload)
    if message is not None:
        message_id, user, text = message
        if _limiter.allow(user):
            await process_inbound(db, SLACK_CHANNEL, message_id, user, text)
            await db.commit()
        else:
            logger.warning("Slack: remetente %s acima do limite; mensagem descartada.", user)
    return {"status": "ok"}
