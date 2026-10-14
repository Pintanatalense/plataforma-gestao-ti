"""
MOD-15 — WhatsApp Integration (Schemas)
"""

from datetime import datetime
from typing import Any
import uuid
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

    # Anti-ban e proteção
    anti_ban_enabled: bool
    min_delay_seconds: int
    max_delay_seconds: int
    simulate_typing: bool
    typing_duration_seconds: int
    max_messages_per_minute: int
    cooldown_per_recipient_seconds: int
    emergency_pause: bool


class WhatsAppConfigUpdate(BaseModel):
    provider: str | None = None
    is_enabled: bool | None = None
    api_url: str | None = None
    api_key: str | None = None
    instance_name: str | None = None
    webhook_secret: str | None = None
    welcome_message: str | None = None

    # Anti-ban
    anti_ban_enabled: bool | None = None
    min_delay_seconds: int | None = None
    max_delay_seconds: int | None = None
    simulate_typing: bool | None = None
    typing_duration_seconds: int | None = None
    max_messages_per_minute: int | None = None
    cooldown_per_recipient_seconds: int | None = None
    emergency_pause: bool | None = None


class WhatsAppTestMessageRequest(BaseModel):
    to_phone: str = Field(..., description="Número de destino para o teste")
    message: str = Field("Teste de conexão do Bot de WhatsApp da Plataforma de Gestão de TI.", description="Mensagem")


# Schemas para Templates / Respostas Rápidas
class WhatsAppTemplateCreate(BaseModel):
    name: str = Field(..., max_length=100, description="Nome identificador do template")
    code: str = Field(..., max_length=50, description="Código único do template")
    category: str = Field("SERVICE_DESK", max_length=50, description="Categoria do template")
    content: str = Field(..., description="Texto com suporte a variáveis {{solicitante}}, {{protocolo}}, etc.")
    is_active: bool = Field(True, description="Indica se o template está ativo")


class WhatsAppTemplateUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    content: str | None = None
    is_active: bool | None = None


class WhatsAppTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    category: str
    content: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WhatsAppPreviewTemplateRequest(BaseModel):
    ticket_id: uuid.UUID | None = None
    template_content: str | None = None
    observacao: str | None = None


class WhatsAppPreviewTemplateResponse(BaseModel):
    rendered_message: str
    variables_detected: list[str]


# Schemas para a Fila Outbox
class WhatsAppOutboxResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    to_phone: str
    message: str
    status: str
    priority: int
    ticket_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None
    scheduled_for: datetime | None = None
    sent_at: datetime | None = None
    attempts: int
    max_attempts: int
    last_error: str | None = None
    created_at: datetime


class WhatsAppOutboxStatsResponse(BaseModel):
    pending_count: int
    sent_today_count: int
    failed_count: int
    sent_last_minute: int
    anti_ban_enabled: bool
    emergency_pause: bool
    min_delay_seconds: int
    max_delay_seconds: int
    simulate_typing: bool
    max_messages_per_minute: int
    cooldown_per_recipient_seconds: int


class WhatsAppSendTicketRequest(BaseModel):
    template_id: uuid.UUID | None = Field(None, description="ID do template pré-definido a utilizar")
    custom_message: str | None = Field(None, description="Mensagem customizada ou texto adicional")
    observacao: str | None = Field(None, description="Observação para interpolação na tag {{observacao}}")
    priority: int = Field(2, ge=1, le=3, description="Prioridade: 1=Alta, 2=Normal, 3=Baixa")
