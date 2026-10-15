"""
MOD-01 — Gestão de Ambientes e Demonstração (Router)

Rotas administrativas para controle do modo Demo vs Produção,
preview de impacto, exclusão segura de dados fictícios e recarga.
"""

import uuid
from typing import Annotated
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import require_permission, get_token_payload, get_current_user_ip
from app.core.demo_service import DemoManagementService

router = APIRouter(prefix="/system/demo", tags=["Gestão de Ambientes & Demonstração"])


class CleanDemoRequest(BaseModel):
    confirmation_phrase: str = Field(
        ...,
        description="Frase de segurança exigida: 'LIMPAR DADOS DE DEMONSTRACAO'"
    )


@router.get(
    "/status",
    summary="Consulta o modo atual do sistema (DEMO vs PRODUCTION) e quantitativo de registros",
    dependencies=[Depends(require_permission("system.data.export"))]
)
async def get_demo_status(
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = DemoManagementService(session)
    return await service.get_demo_status()


@router.get(
    "/preview-clean",
    summary="Pré-visualização do impacto da limpeza: registros a remover vs preservados",
    dependencies=[Depends(require_permission("system.backup.manage"))]
)
async def preview_clean(
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = DemoManagementService(session)
    return await service.get_preview_clean()


@router.post(
    "/clean",
    summary="Limpeza segura dos dados demonstrativos com confirmação e verificação de backup",
    dependencies=[Depends(require_permission("system.backup.manage"))]
)
async def clean_demo_data(
    body: CleanDemoRequest,
    payload: Annotated[dict, Depends(get_token_payload)],
    ip_address: Annotated[str, Depends(get_current_user_ip)],
    session: Annotated[AsyncSession, Depends(get_db)]
):
    admin_user_id = uuid.UUID(payload["sub"])
    service = DemoManagementService(session)
    return await service.clean_demo_data(
        admin_user_id=admin_user_id,
        confirmation_phrase=body.confirmation_phrase,
        ip_address=ip_address
    )


@router.post(
    "/seed",
    status_code=status.HTTP_201_CREATED,
    summary="Recarrega dados demonstrativos modelo de forma limpa e idempotente",
    dependencies=[Depends(require_permission("system.backup.manage"))]
)
async def seed_demo_data(
    payload: Annotated[dict, Depends(get_token_payload)],
    session: Annotated[AsyncSession, Depends(get_db)]
):
    admin_user_id = uuid.UUID(payload["sub"])
    service = DemoManagementService(session)
    return await service.seed_demo_data(admin_user_id=admin_user_id)


@router.post(
    "/seed-test",
    status_code=status.HTTP_201_CREATED,
    summary="Recarrega dados da base de testes e homologação (QA)",
    dependencies=[Depends(require_permission("system.backup.manage"))]
)
async def seed_test_data(
    payload: Annotated[dict, Depends(get_token_payload)],
    session: Annotated[AsyncSession, Depends(get_db)]
):
    from app.seed_test import seed_test
    await seed_test(reset=False)
    return {
        "success": True,
        "message": "Base de testes e homologação (QA) recarregada com sucesso!",
        "system_mode": "TEST"
    }
