import json
import uuid

from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.glpi_import_schemas import (
    GlpiImportAnalyzeResponse,
    GlpiImportExecuteResponse,
    GlpiImportExecuteRowRequest,
)
from app.assets.glpi_import_service import GlpiAssetImportService
from app.assets.repository import AssetRepository
from app.assets.schemas import AssetCategoryCreate, AssetCategoryResponse, AssetCategoryUpdate, AssetCreate, AssetResponse, AssetUpdate
from app.assets.services import AssetService
from app.assets.statement_template import BLOCK_FIELDS, DEFAULT_TEMPLATE, INLINE_FIELDS, unknown_fields
from app.audit.repository import AuditRepository
from app.core.exceptions import ValidationException
from app.core.dependencies import require_permission, get_current_user_id, get_token_payload
from app.database import get_db
from app.movements.repository import AssetMovementRepository


router = APIRouter()


def get_asset_service(db: AsyncSession = Depends(get_db)) -> AssetService:
    return AssetService(AssetRepository(db), AssetMovementRepository(db))


def get_glpi_import_service(db: AsyncSession = Depends(get_db)) -> GlpiAssetImportService:
    return GlpiAssetImportService(AssetRepository(db), AssetService(AssetRepository(db), AssetMovementRepository(db)))


@router.get("/categories", response_model=list[AssetCategoryResponse], dependencies=[Depends(require_permission("assets.read"))])
async def list_categories(
    service: AssetService = Depends(get_asset_service),
):
    return await service.list_categories()


@router.post("/categories", response_model=AssetCategoryResponse, dependencies=[Depends(require_permission("assets.categories.manage"))])
async def create_category(
    schema: AssetCategoryCreate,
    service: AssetService = Depends(get_asset_service),
):
    return await service.create_category(schema)


@router.put("/categories/{category_id}", response_model=AssetCategoryResponse, dependencies=[Depends(require_permission("assets.categories.manage"))])
async def update_category(
    category_id: uuid.UUID,
    schema: AssetCategoryUpdate,
    service: AssetService = Depends(get_asset_service),
):
    return await service.update_category(category_id, schema)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("assets.categories.manage"))])
async def delete_category(
    category_id: uuid.UUID,
    service: AssetService = Depends(get_asset_service),
):
    await service.delete_category(category_id)


# ---- Modelo do Termo de Responsabilidade (declarado antes de "/{asset_id}") -------------------------------------

STATEMENT_ENTITY_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "asset_statement_template")


class StatementTemplateIn(BaseModel):
    template: str = Field(..., max_length=40000)


def _template_payload(template: str, is_default: bool) -> dict:
    return {
        "template": template,
        "is_default": is_default,
        "default_template": DEFAULT_TEMPLATE,
        "fields": INLINE_FIELDS,
        "blocks": BLOCK_FIELDS,
        "unknown_fields": unknown_fields(template),
    }


@router.get("/statement-template", dependencies=[Depends(require_permission("assets.read"))],
            summary="Modelo atual do Termo de Responsabilidade (próprio da empresa ou padrão do sistema)")
async def get_statement_template(service: AssetService = Depends(get_asset_service)):
    template, is_default = await service.get_statement_template()
    return _template_payload(template, is_default)


@router.put("/statement-template", dependencies=[Depends(require_permission("organization.company.update"))],
            summary="Salva o modelo próprio do Termo de Responsabilidade")
async def save_statement_template(
    body: StatementTemplateIn,
    service: AssetService = Depends(get_asset_service),
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    saved = await service.save_statement_template(body.template)
    await AuditRepository(db).create(
        event_type="assets.statement_template_changed", entity_type="system_setting", entity_id=STATEMENT_ENTITY_ID,
        data={"customized": True, "characters": len(saved)}, user_id=user_id,
    )
    return _template_payload(saved, False)


@router.delete("/statement-template", dependencies=[Depends(require_permission("organization.company.update"))],
               summary="Volta ao modelo padrão do sistema")
async def reset_statement_template(
    service: AssetService = Depends(get_asset_service),
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    await service.reset_statement_template()
    await AuditRepository(db).create(
        event_type="assets.statement_template_changed", entity_type="system_setting", entity_id=STATEMENT_ENTITY_ID,
        data={"customized": False}, user_id=user_id,
    )
    return _template_payload(DEFAULT_TEMPLATE, True)


@router.post("/statement-template/preview", response_class=HTMLResponse,
             dependencies=[Depends(require_permission("organization.company.update"))],
             summary="Prévia do modelo com dados de exemplo (não salva nada)")
async def preview_statement_template(body: StatementTemplateIn, service: AssetService = Depends(get_asset_service)):
    return HTMLResponse(content=await service.render_statement_preview(body.template))


@router.get("", response_model=list[AssetResponse], dependencies=[Depends(require_permission("assets.read"))])
async def list_assets(
    unit_id: uuid.UUID | None = None,
    employee_id: uuid.UUID | None = None,
    service: AssetService = Depends(get_asset_service),
):
    return await service.list_assets(unit_id=unit_id, employee_id=employee_id)


@router.get("/me", response_model=list[AssetResponse], summary="Lista os ativos atribuídos ao colaborador do usuário logado (notebook, celular, etc.)")
async def list_my_assets(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
    service: AssetService = Depends(get_asset_service),
):
    from app.identity.repository import IdentityRepository
    repo = IdentityRepository(session)
    user = await repo.get_user(current_user_id)
    if not user or not user.employee_id:
        return []
    return await service.list_assets(employee_id=user.employee_id)


@router.post(
    "/glpi-import/analyze",
    response_model=GlpiImportAnalyzeResponse,
    summary="Analisa arquivos de inventário XML do GLPI Agent e indica ativos novos/já cadastrados",
    dependencies=[Depends(require_permission("assets.import"))],
)
async def analyze_glpi_import(
    files: list[UploadFile] = File(...),
    service: GlpiAssetImportService = Depends(get_glpi_import_service),
):
    return await service.analyze(files)


@router.post(
    "/glpi-import/execute",
    response_model=GlpiImportExecuteResponse,
    summary="Executa a importação/atualização dos ativos a partir do inventário GLPI já analisado",
    dependencies=[Depends(require_permission("assets.import"))],
)
async def execute_glpi_import(
    files: list[UploadFile] = File(...),
    decisions: str = Form(...),
    service: GlpiAssetImportService = Depends(get_glpi_import_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    try:
        raw_decisions = json.loads(decisions)
        if not isinstance(raw_decisions, list):
            raise ValueError("decisions deve ser uma lista")
        parsed_decisions = [GlpiImportExecuteRowRequest.model_validate(d) for d in raw_decisions]
    except ValueError as exc:  # inclui pydantic.ValidationError e json.JSONDecodeError
        raise ValidationException("Decisões de importação inválidas.") from exc
    return await service.execute(files, parsed_decisions, current_user_id)


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: uuid.UUID,
    service: AssetService = Depends(get_asset_service),
    payload: dict = Depends(get_token_payload),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
):
    permissions = payload.get("permissions", [])
    is_admin = payload.get("is_admin", False)
    if is_admin or "assets.read" in permissions:
        return await service.get_asset(asset_id)

    if "assets.read_own" in permissions:
        from app.identity.repository import IdentityRepository
        repo = IdentityRepository(session)
        user = await repo.get_user(current_user_id)
        asset = await service.get_asset(asset_id)
        if user and user.employee_id and asset.employee_id == user.employee_id:
            return asset

    from app.core.exceptions import ForbiddenException
    raise ForbiddenException("Permissão insuficiente para visualizar este ativo.")


@router.post("", response_model=AssetResponse, dependencies=[Depends(require_permission("assets.write"))])
async def create_asset(
    schema: AssetCreate,
    service: AssetService = Depends(get_asset_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    return await service.create_asset(schema, current_user_id)


@router.put("/{asset_id}", response_model=AssetResponse, dependencies=[Depends(require_permission("assets.write"))])
async def update_asset(
    asset_id: uuid.UUID,
    schema: AssetUpdate,
    service: AssetService = Depends(get_asset_service),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    return await service.update_asset(asset_id, schema, current_user_id)


@router.get(
    "/{asset_id}/responsibility-statement",
    response_class=HTMLResponse,
    summary="Gera Termo de Responsabilidade e Cautela pronto para impressão/PDF",
)
async def get_responsibility_statement(
    asset_id: uuid.UUID,
    service: AssetService = Depends(get_asset_service),
    payload: dict = Depends(get_token_payload),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
):
    permissions = payload.get("permissions", [])
    is_admin = payload.get("is_admin", False)
    if not (is_admin or "assets.read" in permissions):
        if "assets.read_own" in permissions:
            from app.identity.repository import IdentityRepository
            repo = IdentityRepository(session)
            user = await repo.get_user(current_user_id)
            asset = await service.get_asset(asset_id)
            if not (user and user.employee_id and asset.employee_id == user.employee_id):
                from app.core.exceptions import ForbiddenException
                raise ForbiddenException("Permissão insuficiente para gerar termo deste ativo.")
        else:
            from app.core.exceptions import ForbiddenException
            raise ForbiddenException("Permissão insuficiente.")

    html_content = await service.generate_responsibility_statement(asset_id)
    return HTMLResponse(content=html_content)


@router.get(
    "/{asset_id}/tickets",
    summary="Lista todos os chamados relacionados a este ativo patrimonial",
)
async def list_asset_tickets(
    asset_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    payload: dict = Depends(get_token_payload),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    from app.service_desk.services import ServiceDeskService
    from app.service_desk.schemas import TicketResponse

    permissions = payload.get("permissions", [])
    is_admin = payload.get("is_admin", False)
    if not (is_admin or "assets.read" in permissions or "service_desk.tickets.read" in permissions):
        if "assets.read_own" in permissions:
            from app.identity.repository import IdentityRepository
            from app.assets.repository import AssetRepository
            from app.movements.repository import AssetMovementRepository
            user = await IdentityRepository(session).get_user(current_user_id)
            asset = await AssetService(AssetRepository(session), AssetMovementRepository(session)).get_asset(asset_id)
            if not (user and user.employee_id and asset.employee_id == user.employee_id):
                from app.core.exceptions import ForbiddenException
                raise ForbiddenException("Permissão insuficiente para visualizar chamados deste ativo.")
        else:
            from app.core.exceptions import ForbiddenException
            raise ForbiddenException("Permissão insuficiente.")

    sd_service = ServiceDeskService(session)
    tickets = await sd_service.list_tickets_by_asset(asset_id)
    return [TicketResponse.model_validate(t) for t in tickets]

