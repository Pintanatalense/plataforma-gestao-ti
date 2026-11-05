"""Resposta de SLA que acompanha o chamado na API (ADR-017)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

SlaState = Literal["NOT_APPLICABLE", "RUNNING", "PAUSED", "MET", "BREACHED"]


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
