"""
MOD-13 — Data Transfer (Schemas)

Contratos de dados para exportação e importação CSV:
- Filtros e parâmetros de exportação
- Configuração de mapeamento e pré-visualização de importação
- Resultados de processamento e relatório de inconsistências
"""

from datetime import datetime
from typing import Any
import uuid

from pydantic import BaseModel, Field


class ExportFilterParams(BaseModel):
    """Parâmetros e filtros para geração de exportação CSV."""
    entity: str = Field(..., description="Entidade a exportar: tickets, users, employees, categories, stock_items, units, sectors")
    start_date: datetime | None = Field(None, description="Data inicial de filtro")
    end_date: datetime | None = Field(None, description="Data final de filtro")
    status: str | None = Field(None, description="Filtro opcional por status")
    category_id: uuid.UUID | None = Field(None, description="Filtro opcional por categoria")
    delimiter: str = Field(";", description="Delimitador do CSV: ';' (padrão Brasil/Excel) ou ','")


class ImportAnalyzeResponse(BaseModel):
    """Resultado da análise inicial do arquivo CSV enviado."""
    filename: str
    detected_delimiter: str
    total_rows_estimate: int
    headers: list[str]
    preview_rows: list[dict[str, str]]
    suggested_mappings: dict[str, str]


class ImportExecuteRequest(BaseModel):
    """Parâmetros para execução da importação com mapeamento confirmado."""
    entity: str = Field(..., description="Entidade de destino: categories, employees, stock_items, units, sectors")
    column_mapping: dict[str, str] = Field(..., description="Mapeamento {campo_sistema: coluna_csv}")
    delimiter: str = Field(";", description="Delimitador do CSV")


class ImportErrorDetail(BaseModel):
    """Detalhe de linha rejeitada durante a importação."""
    line_number: int
    raw_data: dict[str, Any]
    error_message: str


class ImportExecuteResponse(BaseModel):
    """Resultado final do processamento da importação."""
    entity: str
    total_rows: int
    success_count: int
    error_count: int
    rejected_lines: list[ImportErrorDetail]
    summary_message: str
