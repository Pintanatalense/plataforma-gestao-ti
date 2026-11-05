"""
MOD-04 — Service Desk (Schemas)
"""

import uuid
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field

from app.sla.schemas import SlaInfo, SlaReport


# ==============================================================================
# TicketCategory
# ==============================================================================

class TicketCategoryBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: str | None = Field(None, max_length=255)
    is_active: bool = True
    default_sector_id: uuid.UUID | None = None
    form_schema: list[dict] = Field(default_factory=list)
    # Nulo = "Não se aplica" (ADR-017). Trocar exige service_desk.sla.manage.
    sla_policy_id: uuid.UUID | None = None

class TicketCategoryCreate(TicketCategoryBase):
    pass

class TicketCategoryUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=255)
    is_active: bool | None = None
    default_sector_id: uuid.UUID | None = None
    form_schema: list[dict] | None = None
    sla_policy_id: uuid.UUID | None = None  # enviar null volta para "Não se aplica"

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

class ChildTicketSpec(BaseModel):
    """Um subchamado (ADR-026). Passa pelas mesmas regras de um chamado comum: direcionamento, formulário e SLA."""

    category_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    # Omitido: o setor padrão da categoria. Outro setor exige service_desk.tickets.route_any_sector.
    responsible_sector_id: uuid.UUID | None = None
    custom_fields: dict = Field(default_factory=dict)
    is_required: bool = True
    # Omitida: a prioridade do principal.
    priority: str | None = Field(None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")


MAX_CHILDREN_PER_REQUEST = 20


class TicketCreate(TicketBase):
    asset_ids: list[uuid.UUID] = Field(default_factory=list)
    # Omitido: vai para o setor padrão da categoria. Outro setor exige service_desk.tickets.route_any_sector.
    responsible_sector_id: uuid.UUID | None = None
    # Omitido: o solicitante é quem abre. Outro colaborador exige service_desk.tickets.create_on_behalf.
    requester_id: uuid.UUID | None = None
    # Subchamados criados junto com o principal, na mesma transação (ADR-026).
    children: list[ChildTicketSpec] = Field(default_factory=list, max_length=MAX_CHILDREN_PER_REQUEST)


class ChildrenAdd(BaseModel):
    children: list[ChildTicketSpec] = Field(..., min_length=1, max_length=MAX_CHILDREN_PER_REQUEST)


class TicketCancel(BaseModel):
    reason: str = Field(..., min_length=10, max_length=2000)


class TicketReplace(BaseModel):
    reason: str = Field(..., min_length=10, max_length=2000)
    child: ChildTicketSpec


class TicketRequirementUpdate(BaseModel):
    is_required: bool
    reason: str = Field(..., min_length=10, max_length=2000)

class TicketUpdate(BaseModel):
    status: str | None = Field(None, pattern="^(OPENED|IN_PROGRESS|PENDING|RESOLVED|CLOSED)$")
    priority: str | None = Field(None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    category_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None
    responsible_sector_id: uuid.UUID | None = None
    asset_ids: list[uuid.UUID] | None = None
    custom_fields: dict | None = None
    notes: str | None = None

class TicketAssetBrief(BaseModel):
    id: uuid.UUID
    tag: str
    name: str
    status: str
    unit_id: uuid.UUID
    employee_id: uuid.UUID | None = None

    model_config = ConfigDict(from_attributes=True)


class TicketResponse(TicketBase):
    id: uuid.UUID
    status: str
    requester_id: uuid.UUID
    requester_name: str | None = None
    requester_phone: str | None = None
    assignee_id: uuid.UUID | None

    assignee_name: str | None = None
    # Quem abriu; nulo só em chamados antigos sem esse registro (a tela mostra "não registrado").
    created_by_user_id: uuid.UUID | None = None
    created_by_name: str | None = None
    origin_unit_id: uuid.UUID
    origin_sector_id: uuid.UUID
    responsible_sector_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    
    category: TicketCategoryResponse | None = None
    interactions: list[TicketInteractionResponse] = []
    materials: list[TicketMaterialResponse] = []
    assets: list[TicketAssetBrief] = []
    # Preenchido pelo roteador (`SlaService.attach`); NOT_APPLICABLE quando a categoria não tem política ativa.
    sla: SlaInfo | None = None
    # Chamados vinculados (ADR-026). `parent_ticket_id` só aparece para quem pode ver o principal (o roteador limpa).
    parent_ticket_id: uuid.UUID | None = None
    is_required: bool = True
    replaces_ticket_id: uuid.UUID | None = None
    # Só no principal (preenchido pelo roteador).
    children_progress: "ChildrenProgress | None" = None

    model_config = ConfigDict(from_attributes=True)


class ChildrenProgress(BaseModel):
    """`done`: filhos resolvidos ou encerrados. `required_pending`: obrigatórios ainda não concluídos, cancelados inclusive."""

    total: int = 0
    done: int = 0
    canceled: int = 0
    required_pending: int = 0
    overdue: int = 0
    # Dois sinais separados (ADR-026): etapas obrigatórias atrasadas e o SLA do próprio principal vencido.
    steps_overdue: int = 0
    process_overdue: bool = False


class ChildTicketSummary(BaseModel):
    """Resumo de acompanhamento de um subchamado (nível `track`): sem descrição, interações nem anexos."""

    id: uuid.UUID
    title: str
    status: str
    is_required: bool
    responsible_sector_id: uuid.UUID
    responsible_sector_name: str | None = None
    category_id: uuid.UUID | None = None
    category_name: str | None = None
    assignee_name: str | None = None
    created_at: datetime
    replaces_ticket_id: uuid.UUID | None = None
    replaced_by_ticket_id: uuid.UUID | None = None
    resolution_due_at: datetime | None = None
    overdue: bool = False
    at_risk: bool = False


class ChildrenOverview(BaseModel):
    progress: ChildrenProgress
    children: list[ChildTicketSummary]


TicketResponse.model_rebuild()


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



class TicketAssetActionRequest(BaseModel):
    """Corpo das ações de reserva/entrega/devolução de ativo a partir do chamado."""

    notes: str | None = Field(default=None, max_length=1000)
    employee_id: uuid.UUID | None = None


class TicketAssetInspectRequest(BaseModel):
    approved: bool = True
    notes: str | None = Field(default=None, max_length=1000)
    send_to_maintenance: bool = False


# ==============================================================================
# Relatório gerencial (ADR-017 P4-S5)
# ==============================================================================

class CategoryCount(BaseModel):
    category: str
    count: int


class TicketsReport(BaseModel):
    """Contagens dos chamados CRIADOS no período; `sla` usa os ciclos ENCERRADOS no período (ver `app.sla.report`)."""

    start: date | None = None
    end: date | None = None
    total_tickets: int
    resolution_rate_percent: float
    by_status: dict[str, int]
    by_priority: dict[str, int]
    by_category: list[CategoryCount]
    sla: SlaReport
