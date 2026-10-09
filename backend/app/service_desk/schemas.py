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

class TicketCategoryCreate(TicketCategoryBase):
    pass

class TicketCategoryUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=255)
    is_active: bool | None = None
    default_sector_id: uuid.UUID | None = None

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

class TicketResponse(TicketBase):
    id: uuid.UUID
    status: str
    requester_id: uuid.UUID
    assignee_id: uuid.UUID | None
    origin_unit_id: uuid.UUID
    origin_sector_id: uuid.UUID
    responsible_sector_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    
    interactions: list[TicketInteractionResponse] = []
    materials: list[TicketMaterialResponse] = []
    
    model_config = ConfigDict(from_attributes=True)

