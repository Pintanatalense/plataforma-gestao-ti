"""
MOD-15 — WhatsApp (Schemas): templates de resposta rápida e envio a partir do chamado.
"""

from datetime import datetime
import uuid
from pydantic import BaseModel, ConfigDict, Field


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


class WhatsAppSendTicketRequest(BaseModel):
    template_id: uuid.UUID | None = Field(None, description="ID do template pré-definido a utilizar")
    custom_message: str | None = Field(None, description="Mensagem customizada ou texto adicional")
    observacao: str | None = Field(None, description="Observação para interpolação na tag {{observacao}}")
    priority: int = Field(2, ge=1, le=3, description="Prioridade: 1=Alta, 2=Normal, 3=Baixa")
