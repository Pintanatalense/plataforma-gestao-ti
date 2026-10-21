"""
Contratos de dados para a importação de ativos a partir de inventários XML do
GLPI Agent (FusionInventory). Segue a mesma convenção de
`app.data_transfer.schemas` (Analyze/Execute/Result), mas dedicado a este fluxo
pois o formato de entrada (XML, múltiplos arquivos) e as regras de casamento
(por número de série) são bem diferentes do wizard de CSV.
"""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

GlpiRowStatus = Literal["MATCHED", "NEW", "ERROR"]
GlpiRowAction = Literal["update", "create", "skip"]
GlpiRowOutcome = Literal["created", "updated", "skipped", "error"]


class GlpiImportRow(BaseModel):
    """Resultado da análise de um arquivo XML enviado."""

    filename: str
    status: GlpiRowStatus
    parsed: dict[str, Any] | None = None
    serial_number: str | None = None
    suggested_name: str | None = None
    matched_asset_id: uuid.UUID | None = None
    matched_asset_tag: str | None = None
    matched_asset_name: str | None = None
    error_message: str | None = None


class GlpiImportAnalyzeResponse(BaseModel):
    rows: list[GlpiImportRow]


class GlpiImportExecuteRowRequest(BaseModel):
    """Decisão do usuário para um dos arquivos enviados no /execute."""

    filename: str
    action: GlpiRowAction
    # obrigatório quando action == "update"
    asset_id: uuid.UUID | None = None
    # obrigatórios quando action == "create"
    tag: str | None = Field(None, max_length=50)
    name: str | None = Field(None, max_length=255)
    category_id: uuid.UUID | None = None
    unit_id: uuid.UUID | None = None


class GlpiImportExecuteResult(BaseModel):
    filename: str
    outcome: GlpiRowOutcome
    asset_id: uuid.UUID | None = None
    error_message: str | None = None


class GlpiImportExecuteResponse(BaseModel):
    results: list[GlpiImportExecuteResult]
    created_count: int
    updated_count: int
    skipped_count: int
    error_count: int
