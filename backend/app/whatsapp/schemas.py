"""
MOD-15 — WhatsApp Integration (Schemas)
"""

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class WhatsAppWebhookPayload(BaseModel):
    """Payload recebido via Webhook do Evolution API, Meta ou simulador."""
    phone: str | None = Field(None, description="Número de telefone do remetente")
    message: str | None = Field(None, description="Texto da mensagem")
    data: dict[str, Any] | None = Field(None, description="Payload raw recebido do provedor")


class WhatsAppConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    is_enabled: bool
    api_url: str
    instance_name: str
    welcome_message: str


class WhatsAppConfigUpdate(BaseModel):
    provider: str | None = None
    is_enabled: bool | None = None
    api_url: str | None = None
    api_key: str | None = None
    instance_name: str | None = None
    webhook_secret: str | None = None
    welcome_message: str | None = None


class WhatsAppTestMessageRequest(BaseModel):
    to_phone: str = Field(..., description="Número de destino para o teste")
    message: str = Field("Teste de conexão do Bot de WhatsApp da Plataforma de Gestão de TI.", description="Mensagem")
