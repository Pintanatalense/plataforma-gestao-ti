"""
MOD-14 — Backups do Banco de Dados (Router)

Endpoints REST para gestão, histórico e download seguro de backups do PostgreSQL.
"""

from typing import Annotated
import uuid
from fastapi import APIRouter, Depends, status, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import require_permission, get_token_payload
from app.backup.schemas import DatabaseBackupResponse
from app.backup.services import BackupService

router = APIRouter(prefix="/system/backups", tags=["Sistema & Backups"])


@router.post(
    "/generate",
    response_model=DatabaseBackupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Gera um novo backup completo compactado (.sql.gz) do banco de dados",
    dependencies=[Depends(require_permission("system.backup.manage"))]
)
async def generate_backup(
    payload: Annotated[dict, Depends(get_token_payload)],
    session: Annotated[AsyncSession, Depends(get_db)]
):
    user_id = uuid.UUID(payload["sub"])
    service = BackupService(session)
    backup = await service.create_backup(user_id=user_id)
    return DatabaseBackupResponse.model_validate(backup)


@router.get(
    "",
    response_model=list[DatabaseBackupResponse],
    summary="Lista o histórico de backups gerados com status, tamanho e hash SHA-256",
    dependencies=[Depends(require_permission("system.backup.manage"))]
)
async def list_backups(
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = BackupService(session)
    backups = await service.list_backups()
    return [DatabaseBackupResponse.model_validate(b) for b in backups]


@router.get(
    "/{backup_id}/download",
    summary="Download protegido do arquivo de backup do banco de dados",
    dependencies=[Depends(require_permission("system.backup.download"))]
)
async def download_backup(
    backup_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = BackupService(session)
    backup = await service.get_backup(backup_id)

    file_path = service.storage_dir / backup.filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Arquivo físico de backup não encontrado no armazenamento.")

    return FileResponse(
        path=str(file_path),
        filename=backup.filename,
        media_type="application/gzip",
        headers={
            "X-Checksum-SHA256": backup.checksum_sha256,
            "Access-Control-Expose-Headers": "Content-Disposition, X-Checksum-SHA256"
        }
    )


@router.get(
    "/{backup_id}/verify",
    summary="Valida a integridade física do arquivo e o hash SHA-256 do backup",
    dependencies=[Depends(require_permission("system.backup.manage"))]
)
async def verify_backup(
    backup_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = BackupService(session)
    return await service.validate_backup_integrity(backup_id)


@router.delete(
    "/{backup_id}",
    summary="Exclui um arquivo de backup do histórico e do armazenamento",
    dependencies=[Depends(require_permission("system.backup.manage"))]
)
async def delete_backup(
    backup_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)]
):
    service = BackupService(session)
    await service.delete_backup(backup_id)
    return {"message": "Backup removido com sucesso."}

