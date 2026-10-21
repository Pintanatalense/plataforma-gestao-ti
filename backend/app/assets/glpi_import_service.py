"""
Orquestra a importação de ativos a partir de inventários XML do GLPI Agent:
parse (glpi_import_parser), casamento por número de série (AssetRepository) e
persistência reaproveitando o AssetService existente (create_asset/update_asset),
para herdar suas validações e o comportamento de movimentações sem duplicar lógica.
"""

import uuid

from fastapi import UploadFile

from app.assets.glpi_import_parser import GlpiParseError, build_display_specs, parse_inventory_xml
from app.assets.glpi_import_schemas import (
    GlpiImportAnalyzeResponse,
    GlpiImportExecuteResponse,
    GlpiImportExecuteResult,
    GlpiImportExecuteRowRequest,
    GlpiImportRow,
)
from app.assets.models import AssetStatus
from app.assets.repository import AssetRepository
from app.assets.schemas import AssetCreate, AssetUpdate
from app.assets.services import AssetService
from app.core.exceptions import AppException, ValidationException

MAX_FILES_PER_REQUEST = 20
MAX_FILE_BYTES = 5 * 1024 * 1024


class GlpiAssetImportService:
    def __init__(self, repo: AssetRepository, asset_service: AssetService):
        self.repo = repo
        self.asset_service = asset_service

    async def _read_capped(self, file: UploadFile) -> bytes | None:
        """Lê no máximo MAX_FILE_BYTES + 1; retorna None se o arquivo exceder o limite."""
        content = await file.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            return None
        return content

    def _oversized_message(self) -> str:
        return f"Arquivo maior que {MAX_FILE_BYTES // (1024 * 1024)} MB."

    # -------------------------------------------------------------------
    # Analyze
    # -------------------------------------------------------------------

    async def analyze(self, files: list[UploadFile]) -> GlpiImportAnalyzeResponse:
        if len(files) > MAX_FILES_PER_REQUEST:
            raise ValidationException(f"Envie no máximo {MAX_FILES_PER_REQUEST} arquivos por vez.")

        rows = [await self._analyze_one(file) for file in files]
        return GlpiImportAnalyzeResponse(rows=rows)

    async def _analyze_one(self, file: UploadFile) -> GlpiImportRow:
        filename = file.filename or "arquivo.xml"

        content = await self._read_capped(file)
        if content is None:
            return GlpiImportRow(filename=filename, status="ERROR", error_message=self._oversized_message())

        try:
            parsed = parse_inventory_xml(content)
        except GlpiParseError as exc:
            return GlpiImportRow(filename=filename, status="ERROR", error_message=str(exc))

        serial_number = parsed["serial_number"]
        matched = await self.repo.get_asset_by_serial_number(serial_number) if serial_number else None

        if matched:
            return GlpiImportRow(
                filename=filename,
                status="MATCHED",
                parsed=parsed["glpi_inventory"],
                serial_number=serial_number,
                suggested_name=parsed["suggested_name"],
                matched_asset_id=matched.id,
                matched_asset_tag=matched.tag,
                matched_asset_name=matched.name,
            )

        return GlpiImportRow(
            filename=filename,
            status="NEW",
            parsed=parsed["glpi_inventory"],
            serial_number=serial_number,
            suggested_name=parsed["suggested_name"],
        )

    # -------------------------------------------------------------------
    # Execute
    # -------------------------------------------------------------------

    async def execute(
        self,
        files: list[UploadFile],
        decisions: list[GlpiImportExecuteRowRequest],
        author_id: uuid.UUID,
    ) -> GlpiImportExecuteResponse:
        if len(files) > MAX_FILES_PER_REQUEST:
            raise ValidationException(f"Envie no máximo {MAX_FILES_PER_REQUEST} arquivos por vez.")

        decisions_by_filename = {d.filename: d for d in decisions}
        results: list[GlpiImportExecuteResult] = []

        for file in files:
            filename = file.filename or "arquivo.xml"
            decision = decisions_by_filename.get(filename)
            if decision is None:
                results.append(
                    GlpiImportExecuteResult(
                        filename=filename,
                        outcome="error",
                        error_message="Nenhuma decisão informada para este arquivo.",
                    )
                )
                continue
            results.append(await self._execute_one(file, decision, author_id))

        return GlpiImportExecuteResponse(
            results=results,
            created_count=sum(1 for r in results if r.outcome == "created"),
            updated_count=sum(1 for r in results if r.outcome == "updated"),
            skipped_count=sum(1 for r in results if r.outcome == "skipped"),
            error_count=sum(1 for r in results if r.outcome == "error"),
        )

    async def _execute_one(
        self, file: UploadFile, decision: GlpiImportExecuteRowRequest, author_id: uuid.UUID
    ) -> GlpiImportExecuteResult:
        filename = decision.filename

        if decision.action == "skip":
            return GlpiImportExecuteResult(filename=filename, outcome="skipped")

        content = await self._read_capped(file)
        if content is None:
            return GlpiImportExecuteResult(filename=filename, outcome="error", error_message=self._oversized_message())

        try:
            parsed = parse_inventory_xml(content)
        except GlpiParseError as exc:
            return GlpiImportExecuteResult(filename=filename, outcome="error", error_message=str(exc))

        glpi_inventory = parsed["glpi_inventory"]
        serial_number = parsed["serial_number"]

        try:
            if decision.action == "update":
                return await self._execute_update(decision, serial_number, glpi_inventory, author_id)
            return await self._execute_create(decision, parsed, serial_number, glpi_inventory, author_id)
        except AppException as exc:
            return GlpiImportExecuteResult(filename=filename, outcome="error", error_message=exc.message)

    async def _execute_update(
        self,
        decision: GlpiImportExecuteRowRequest,
        serial_number: str | None,
        glpi_inventory: dict,
        author_id: uuid.UUID,
    ) -> GlpiImportExecuteResult:
        if decision.asset_id is None:
            raise ValidationException("asset_id é obrigatório para atualizar um ativo existente.")

        asset = await self.asset_service.get_asset(decision.asset_id)
        # Sobrescreve só as chaves que o GLPI de fato informa (cpu/ram/storage/os/...),
        # preservando qualquer outro campo que o admin tenha preenchido manualmente.
        merged_specs = {**(asset.technical_specs or {}), **build_display_specs(glpi_inventory)}

        update = AssetUpdate(
            tag=asset.tag,
            serial_number=serial_number or asset.serial_number,
            name=asset.name,
            category_id=asset.category_id,
            status=asset.status,
            technical_specs=merged_specs,
            purchase_date=asset.purchase_date,
            warranty_expires=asset.warranty_expires,
            notes=asset.notes,
            unit_id=asset.unit_id,
            employee_id=asset.employee_id,
        )
        updated_asset = await self.asset_service.update_asset(asset.id, update, author_id)
        return GlpiImportExecuteResult(filename=decision.filename, outcome="updated", asset_id=updated_asset.id)

    async def _execute_create(
        self,
        decision: GlpiImportExecuteRowRequest,
        parsed: dict,
        serial_number: str | None,
        glpi_inventory: dict,
        author_id: uuid.UUID,
    ) -> GlpiImportExecuteResult:
        if not decision.tag or not decision.category_id or not decision.unit_id:
            raise ValidationException("Patrimônio, Categoria e Unidade são obrigatórios para criar um novo ativo.")

        create = AssetCreate(
            tag=decision.tag,
            serial_number=serial_number,
            name=decision.name or parsed["suggested_name"],
            category_id=decision.category_id,
            status=AssetStatus.IN_STOCK,
            technical_specs=build_display_specs(glpi_inventory),
            unit_id=decision.unit_id,
            employee_id=None,
        )
        created_asset = await self.asset_service.create_asset(create, author_id)
        return GlpiImportExecuteResult(filename=decision.filename, outcome="created", asset_id=created_asset.id)
