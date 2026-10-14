"""
MOD-15 — WhatsApp Integration (Router)

Endpoints REST para webhook do bot, configuração administrativa e testes de conectividade.
"""

from typing import Annotated
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import require_permission
from app.whatsapp.schemas import (
    WhatsAppWebhookPayload,
    WhatsAppConfigResponse,
    WhatsAppConfigUpdate,
    WhatsAppTestMessageRequest,
)
from app.whatsapp.conversation_service import WhatsAppConversationService
from app.whatsapp.adapter import get_whatsapp_adapter

router = APIRouter(prefix="/integrations/whatsapp", tags=["Integração WhatsApp"])


@router.post(
    "/webhook",
    summary="Webhook para recepção e processamento de mensagens do WhatsApp",
)
async def whatsapp_webhook(
    payload: WhatsAppWebhookPayload,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    phone = payload.phone
    message_text = payload.message

    # Parser para payloads do Evolution API (ex: key.remoteJid e message.conversation)
    if not phone and payload.data:
        data = payload.data
        # Evolution API v1/v2 payload structure
        key = data.get("key", {})
        remote_jid = key.get("remoteJid", "")
        if "@" in remote_jid:
            phone = remote_jid.split("@")[0]

        msg_obj = data.get("message", {})
        message_text = msg_obj.get("conversation") or msg_obj.get("extendedTextMessage", {}).get("text")

    if not phone or not message_text:
        return {"status": "ignored", "reason": "No valid phone or message content identified"}

    service = WhatsAppConversationService(session)
    reply = await service.process_incoming_message(from_phone=phone, text=message_text)
    return {"status": "processed", "reply": reply}


@router.get(
    "/config",
    response_model=WhatsAppConfigResponse,
    summary="Recupera as configurações e status da integração com WhatsApp",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def get_whatsapp_config(
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = WhatsAppConversationService(session)
    config = await service.get_config()
    return WhatsAppConfigResponse.model_validate(config)


@router.patch(
    "/config",
    response_model=WhatsAppConfigResponse,
    summary="Atualiza provedor, tokens e parâmetros do WhatsApp",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def update_whatsapp_config(
    body: WhatsAppConfigUpdate,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = WhatsAppConversationService(session)
    config = await service.get_config()

    if body.provider is not None:
        config.provider = body.provider
    if body.is_enabled is not None:
        config.is_enabled = body.is_enabled
    if body.api_url is not None:
        config.api_url = body.api_url
    if body.api_key is not None:
        config.api_key = body.api_key
    if body.instance_name is not None:
        config.instance_name = body.instance_name
    if body.webhook_secret is not None:
        config.webhook_secret = body.webhook_secret
    if body.welcome_message is not None:
        config.welcome_message = body.welcome_message

    await session.commit()
    return WhatsAppConfigResponse.model_validate(config)


@router.post(
    "/test-send",
    summary="Dispara mensagem de teste para validação de conectividade com o provedor",
    dependencies=[Depends(require_permission("integrations.whatsapp.manage"))]
)
async def test_send_message(
    body: WhatsAppTestMessageRequest,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = WhatsAppConversationService(session)
    config = await service.get_config()
    adapter = get_whatsapp_adapter(config)

    success = await adapter.send_message(body.to_phone, body.message)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível enviar a mensagem através do provedor configurado."
        )

    return {"message": "Mensagem de teste enviada com sucesso!", "to_phone": body.to_phone}
