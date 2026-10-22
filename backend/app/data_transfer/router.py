"""
MOD-13 — Data Transfer (Router)

Endpoints REST para importação e exportação de dados CSV:
- Exportação segura com sanitização de fórmulas e filtros
- Assistente de importação: análise inicial, preview e execução transacional
"""

import json
from typing import Annotated
from fastapi import APIRouter, Depends, UploadFile, File, Form, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import require_permission
from app.data_transfer.schemas import (
    ExportFilterParams,
    ImportAnalyzeResponse,
    ImportExecuteResponse,
)
from app.data_transfer.export_service import DataExportService
from app.data_transfer.import_service import DataImportService

router = APIRouter(prefix="/system", tags=["Sistema & Dados"])


@router.post(
    "/export",
    summary="Exporta dados do sistema em formato CSV com codificação UTF-8 BOM",
    dependencies=[Depends(require_permission("system.data.export"))]
)
async def export_data(
    params: ExportFilterParams,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = DataExportService(session)
    filename, csv_bytes = await service.generate_csv(params)

    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )


@router.post(
    "/import/analyze",
    response_model=ImportAnalyzeResponse,
    summary="Analisa arquivo CSV para o Wizard de importação (delimitador, colunas e preview)",
    dependencies=[Depends(require_permission("system.data.import"))]
)
async def analyze_import_file(
    file: UploadFile = File(...),
    session: Annotated[AsyncSession, Depends(get_db)] = None
):
    raw_bytes = await file.read()
    try:
        content_str = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content_str = raw_bytes.decode("latin-1")

    service = DataImportService(session)
    return service.analyze_csv(content_str, filename=file.filename or "import.csv")


@router.post(
    "/import/execute",
    response_model=ImportExecuteResponse,
    summary="Executa a importação dos registros no banco com base no mapeamento configurado",
    dependencies=[Depends(require_permission("system.data.import"))]
)
async def execute_import_data(
    file: UploadFile = File(...),
    entity: str = Form(...),
    mapping: str = Form(...),  # JSON string
    delimiter: str = Form(";"),
    session: Annotated[AsyncSession, Depends(get_db)] = None
):
    raw_bytes = await file.read()
    try:
        content_str = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content_str = raw_bytes.decode("latin-1")

    column_mapping = json.loads(mapping) if mapping else {}
    service = DataImportService(session)
    return await service.execute_import(
        content_str=content_str,
        entity=entity,
        column_mapping=column_mapping,
        delimiter=delimiter
    )
