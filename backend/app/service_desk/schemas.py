"""
MOD-04 — Service Desk (Schemas)
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ==============================================================================
# TicketCategory
# ==============================================================================

class TicketCategoryBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: str | None = Field(None, max_length=255)
    is_active: bool = True
    default_sector_id: uuid.UUID | None = None
    form_schema: list[dict] = Field(default_factory=list)

class TicketCategoryCreate(TicketCategoryBase):
    pass

class TicketCategoryUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=255)
    is_active: bool | None = None
    default_sector_id: uuid.UUID | None = None
    form_schema: list[dict] | None = None

class TicketCategoryResponse(TicketCategoryBase):
    id: uuid.UUID
    
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# TicketInteraction
# ==============================================================================

class TicketInteractionBase(BaseModel):
    message: str
    is_internal: bool = False

class TicketInteractionCreate(TicketInteractionBase):
    pass

class TicketInteractionResponse(TicketInteractionBase):
    id: uuid.UUID
    ticket_id: uuid.UUID
    author_id: uuid.UUID
    author_name: str | None = None
    author_email: str | None = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# TicketMaterial
# ==============================================================================

class TicketMaterialBase(BaseModel):
    stock_item_id: uuid.UUID
    quantity: int = Field(gt=0)

class TicketMaterialCreate(TicketMaterialBase):
    pass

class TicketMaterialResponse(TicketMaterialBase):
    id: uuid.UUID
    ticket_id: uuid.UUID
    author_id: uuid.UUID
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Ticket
# ==============================================================================

class TicketBase(BaseModel):
    title: str = Field(..., max_length=255)
    description: str
    priority: str = Field("LOW", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    category_id: uuid.UUID | None = None
    custom_fields: dict = Field(default_factory=dict)

class TicketCreate(TicketBase):
    asset_ids: list[uuid.UUID] = Field(default_factory=list)
    responsible_sector_id: uuid.UUID | None = None

class TicketUpdate(BaseModel):
    status: str | None = Field(None, pattern="^(OPENED|IN_PROGRESS|PENDING|RESOLVED|CLOSED)$")
    priority: str | None = Field(None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    category_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None
    responsible_sector_id: uuid.UUID | None = None
    asset_ids: list[uuid.UUID] | None = None
    custom_fields: dict | None = None
    notes: str | None = None

class TicketResponse(TicketBase):
    id: uuid.UUID
    status: str
    requester_id: uuid.UUID
    requester_name: str | None = None
    assignee_id: uuid.UUID | None
    assignee_name: str | None = None
    origin_unit_id: uuid.UUID
    origin_sector_id: uuid.UUID
    responsible_sector_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    
    category: TicketCategoryResponse | None = None
    interactions: list[TicketInteractionResponse] = []
    materials: list[TicketMaterialResponse] = []
    
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# TicketHistory
# ==============================================================================

class TicketHistoryItem(BaseModel):
    id: uuid.UUID
    event_type: str
    action: str
    description: str
    user_name: str | None = None
    user_email: str | None = None
    data: dict = Field(default_factory=dict)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

