"""Schemas de SLA (ADR-017): o `sla` que acompanha o chamado na API e a administração de calendários e políticas."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.sla.business_time import _MAX_MINUTES as MAX_MINUTES

SlaState = Literal["NOT_APPLICABLE", "RUNNING", "PAUSED", "MET", "BREACHED", "CANCELED"]


class SlaInfo(BaseModel):
    """`NOT_APPLICABLE`: a categoria não tem política ativa; o chamado nunca é atrasado e fica fora dos indicadores."""

    state: SlaState = "NOT_APPLICABLE"
    policy_name: str | None = None
    cycle: int | None = None
    priority: str | None = None
    first_response_due_at: datetime | None = None
    resolution_due_at: datetime | None = None
    first_response_at: datetime | None = None
    resolved_at: datetime | None = None
    paused: bool = False
    # Tipos de violação já registrados neste ciclo: FIRST_RESPONSE e/ou RESOLUTION.
    breaches: list[str] = []
    # Calculados na leitura (P4-S5): prazo pendente já vencido (antes de o job registrar) ou acima do % de alerta.
    overdue: bool = False
    at_risk: bool = False


# --- Indicadores (P4-S5) ------------------------------------------------------------------------------------------


class SlaGroup(BaseModel):
    """Ciclos encerrados no período. Cumprimento = MET / (MET + BREACHED); médias em minutos úteis."""

    key: str
    label: str
    met: int = 0
    breached: int = 0
    compliance_percent: float | None = None
    avg_first_response_minutes: int | None = None
    avg_resolution_minutes: int | None = None


class SlaAttention(BaseModel):
    ticket_id: uuid.UUID
    title: str
    priority: str
    kind: str
    due_at: datetime
    overdue: bool


class SlaProcesses(BaseModel):
    """Chamados principais com subchamados (ADR-026), AGORA: abertos e os dois sinais de atraso, separados."""

    open: int = 0
    # O SLA do próprio principal venceu (só quando a categoria dele tem política).
    process_overdue: int = 0
    # Ao menos um subchamado obrigatório está atrasado.
    steps_overdue: int = 0


class SlaReport(BaseModel):
    total: SlaGroup
    by_category: list[SlaGroup] = []
    by_priority: list[SlaGroup] = []
    # Chamados vinculados (ADR-026): avulso, principal (tempo total do processo) e subchamado (cada etapa).
    by_kind: list[SlaGroup] = []
    # Subchamados por setor responsável: o tempo de atendimento de cada departamento.
    child_by_sector: list[SlaGroup] = []
    # Situação AGORA (não depende do período): chamados com relógio aberto, em risco e atrasados.
    open: int = 0
    at_risk: int = 0
    overdue: int = 0
    attention: list[SlaAttention] = []
    processes: SlaProcesses = SlaProcesses()


# --- Administração (P4-S4): calendários e políticas ---------------------------------------------------------------

Priority = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
PausableStatus = Literal["PENDING", "IN_PROGRESS"]  # OPENED nunca: o relógio não pode nascer pausado


class HolidayIn(BaseModel):
    day: date
    name: str = Field(..., min_length=1, max_length=100)


class HolidayOut(HolidayIn):
    model_config = ConfigDict(from_attributes=True)


class CalendarIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    timezone: str = Field("America/Sao_Paulo", min_length=1, max_length=64)
    # {"0": [["08:00", "18:00"]], ...}: dia da semana (0 = segunda) -> intervalos de expediente
    weekly_hours: dict[str, list[list[str]]]
    holidays: list[HolidayIn] = []


class CalendarUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    timezone: str | None = Field(None, min_length=1, max_length=64)
    weekly_hours: dict[str, list[list[str]]] | None = None
    holidays: list[HolidayIn] | None = None


class CalendarOut(BaseModel):
    id: uuid.UUID
    name: str
    timezone: str
    weekly_hours: dict
    holidays: list[HolidayOut]
    policy_names: list[str] = []


class TargetIn(BaseModel):
    priority: Priority
    first_response_minutes: int = Field(..., ge=1, le=MAX_MINUTES)
    resolution_minutes: int = Field(..., ge=1, le=MAX_MINUTES)


class TargetOut(TargetIn):
    model_config = ConfigDict(from_attributes=True)


class PolicyIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    is_active: bool = False
    calendar_id: uuid.UUID
    pause_statuses: list[PausableStatus] = ["PENDING"]
    reopen_rule: Literal["RESTART", "CONTINUE"] = "RESTART"
    alert_percent: int = Field(80, ge=0, le=99, description="0 desliga o alerta de proximidade")
    targets: list[TargetIn] = []


class PolicyUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    is_active: bool | None = None
    calendar_id: uuid.UUID | None = None
    pause_statuses: list[PausableStatus] | None = None
    reopen_rule: Literal["RESTART", "CONTINUE"] | None = None
    alert_percent: int | None = Field(None, ge=0, le=99)
    targets: list[TargetIn] | None = None


class PolicyOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    is_active: bool
    calendar_id: uuid.UUID
    calendar_name: str
    pause_statuses: list[str]
    reopen_rule: str
    alert_percent: int
    targets: list[TargetOut]
    category_names: list[str] = []
