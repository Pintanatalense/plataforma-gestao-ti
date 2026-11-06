"""
Entrada de mensagens da Evolution (ADR-019, C4). A Evolution chama este endereço pela REDE INTERNA do Compose
(`EVOLUTION_WEBHOOK_URL`); o Nginx bloqueia o caminho para a internet (`location` com 404) e, mesmo que alguém o
alcance, só vale corpo com o segredo no cabeçalho `X-Webhook-Secret` (comparado em tempo constante).

A resposta do bot NUNCA volta aqui: vira entrega, como no webhook da Meta.
"""
import hmac
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import client_ip
from app.database import get_db
from app.notifications.channel_store import load_channel
from app.notifications.channels import whatsapp_evolution as evolution
from app.notifications.channels.whatsapp import PROVIDER_EVOLUTION, WHATSAPP_CHANNEL, provider_of
from app.notifications.conversation.inbound import process_inbound
from app.notifications.receipts import apply_receipts
from app.notifications.telegram_poller import SenderRateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/whatsapp/evolution", tags=["WhatsApp"])

_limiter = SenderRateLimiter()  # por remetente, por processo da API


@router.post("/webhook", include_in_schema=False)
async def receive_evolution_webhook(request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    stored = await load_channel(db, WHATSAPP_CHANNEL)
    if stored is None or not stored.enabled or provider_of(stored) != PROVIDER_EVOLUTION:
        return Response(status_code=404)
    expected = stored.secrets.get("webhook_secret")
    given = request.headers.get(evolution.WEBHOOK_SECRET_HEADER)
    if not expected or not given or not hmac.compare_digest(expected, given):
        logger.warning("Webhook da Evolution sem segredo válido, de %s", client_ip(request))
        return Response(status_code=401)
    try:
        payload = json.loads(await request.body())
    except ValueError:
        return Response(status_code=400)

    instance = stored.config.get("instance_name") or evolution.DEFAULT_INSTANCE
    for message_id, phone, text in evolution.parse_inbound(payload, instance):
        if not _limiter.allow(phone):
            logger.warning("WhatsApp: remetente %s acima do limite; mensagem descartada.", phone)
            continue
        await process_inbound(db, WHATSAPP_CHANNEL, message_id, phone, text)
        await db.commit()
    receipts = evolution.parse_receipts(payload, instance)
    if receipts:
        await apply_receipts(db, WHATSAPP_CHANNEL, receipts)
        await db.commit()
    return {"status": "ok"}
