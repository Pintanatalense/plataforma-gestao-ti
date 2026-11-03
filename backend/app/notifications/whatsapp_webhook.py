"""
Webhook público da Meta Cloud API (WhatsApp). Substitui o webhook antigo sem autenticação.

- GET: handshake de verificação (`hub.verify_token` comparado em tempo constante).
- POST: só aceita corpo cuja assinatura `X-Hub-Signature-256` (HMAC-SHA256 do corpo BRUTO com o App Secret)
  confere; qualquer outra coisa recebe 401 sem corpo. A resposta do bot NUNCA volta aqui: vira entrega.
"""
import hashlib
import hmac
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import client_ip
from app.database import get_db
from app.notifications.channel_store import load_channel
from app.notifications.channels.whatsapp import WHATSAPP_CHANNEL
from app.notifications.conversation.inbound import process_inbound
from app.notifications.telegram_poller import SenderRateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/whatsapp", tags=["WhatsApp"])

_limiter = SenderRateLimiter()  # por processo da API; o worker único do ADR §4.5 não se aplica aqui


def signature_valid(app_secret: str | None, header: str | None, raw_body: bytes) -> bool:
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def extract_messages(payload: dict[str, Any], phone_number_id: str | None) -> list[tuple[str, str, str]]:
    """(wamid, telefone do remetente, texto) das mensagens de texto destinadas ao nosso número."""
    found: list[tuple[str, str, str]] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            if phone_number_id and (value.get("metadata") or {}).get("phone_number_id") != phone_number_id:
                continue  # evento de outro número da mesma conta
            for message in value.get("messages") or []:
                text = (message.get("text") or {}).get("body")
                if message.get("type") == "text" and isinstance(text, str) and message.get("id") and message.get("from"):
                    found.append((str(message["id"]), "".join(ch for ch in str(message["from"]) if ch.isdigit()), text))
    return found


@router.get("/webhook", include_in_schema=False)
async def verify_webhook(
    db: Annotated[AsyncSession, Depends(get_db)],
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
):
    stored = await load_channel(db, WHATSAPP_CHANNEL)
    expected = stored.secrets.get("verify_token") if stored else None
    if mode == "subscribe" and expected and token and challenge and hmac.compare_digest(expected, token):
        return PlainTextResponse(challenge)
    return Response(status_code=403)


@router.post("/webhook", include_in_schema=False)
async def receive_webhook(request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    raw = await request.body()  # a assinatura é sobre os bytes exatos, antes de qualquer parse
    stored = await load_channel(db, WHATSAPP_CHANNEL)
    if stored is None or not stored.enabled:
        return Response(status_code=404)
    if not signature_valid(stored.secrets.get("app_secret"), request.headers.get("X-Hub-Signature-256"), raw):
        logger.warning("WhatsApp webhook com assinatura inválida de %s", client_ip(request))
        return Response(status_code=401)

    try:
        payload = json.loads(raw)
    except ValueError:
        return Response(status_code=400)

    for message_id, phone, text in extract_messages(payload, stored.config.get("phone_number_id")):
        if not _limiter.allow(phone):
            logger.warning("WhatsApp: remetente %s acima do limite; mensagem descartada.", phone)
            continue
        await process_inbound(db, WHATSAPP_CHANNEL, message_id, phone, text)
        await db.commit()
    return {"status": "ok"}
