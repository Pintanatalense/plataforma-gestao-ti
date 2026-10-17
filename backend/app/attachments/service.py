"""
MOD-10 — Anexos (Service)

Armazenamento em disco sob ``ATTACHMENT_STORAGE_PATH``. O nome físico é sempre um
UUID (nunca derivado do cliente) e o caminho final é validado para não escapar da raiz.
"""

import enum
import logging
import os
import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.attachments.models import Attachment
from app.attachments.repository import AttachmentRepository
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_CHUNK = 1024 * 1024
_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\]")


class AttachmentEntityType(enum.StrEnum):
    """Tipos de entidade que aceitam anexos (lista fechada)."""

    TICKET = "TICKET"
    ASSET = "ASSET"


def _signature_ok(content_type: str, head: bytes) -> bool:
    """Confere os primeiros bytes com o tipo declarado (evita HTML/EXE disfarçado)."""
    if content_type == "application/pdf":
        return head.startswith(b"%PDF-")
    if content_type == "image/png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return head.startswith(b"\xff\xd8\xff")
    if content_type == "video/mp4":
        return head[4:8] == b"ftyp"
    if content_type.startswith("application/vnd.openxmlformats-officedocument"):
        return head.startswith(b"PK")
    return False


def _clean_filename(name: str | None) -> str:
    base = os.path.basename((name or "").replace("\\", "/"))
    base = _UNSAFE_NAME.sub("_", base).strip()
    return (base or "arquivo")[:255]


class AttachmentService:
    def __init__(self, repo: AttachmentRepository):
        self.repo = repo
        self.base_dir: Path = settings.attachment_storage_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_inside_base(self, relative: str) -> Path:
        base = self.base_dir.resolve()
        target = (base / relative).resolve()
        if base != target and base not in target.parents:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Caminho de anexo inválido.")
        return target

    async def upload_file(
        self,
        file: UploadFile,
        entity_type: AttachmentEntityType,
        entity_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Attachment:
        content_type = (file.content_type or "").lower()
        if content_type not in settings.ATTACHMENT_ALLOWED_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Tipo de arquivo não permitido.",
            )

        relative = f"{entity_type.value.lower()}/{entity_id}/{uuid.uuid4().hex}"
        target = self._resolve_inside_base(relative)
        target.parent.mkdir(parents=True, exist_ok=True)

        size_bytes = 0
        try:
            with open(target, "wb") as buffer:
                while chunk := await file.read(_CHUNK):
                    if size_bytes == 0 and not _signature_ok(content_type, chunk[:16]):
                        raise HTTPException(
                            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail="O conteúdo do arquivo não corresponde ao tipo informado.",
                        )
                    size_bytes += len(chunk)
                    if size_bytes > settings.attachment_max_size_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"Arquivo excede o limite de {settings.ATTACHMENT_MAX_SIZE_MB} MB.",
                        )
                    buffer.write(chunk)
            if size_bytes == 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo vazio.")
        except BaseException:
            target.unlink(missing_ok=True)
            raise

        attachment = Attachment(
            filename=_clean_filename(file.filename),
            content_type=content_type,
            size_bytes=size_bytes,
            file_path=relative,
            entity_type=entity_type.value,
            entity_id=entity_id,
            uploaded_by_id=user_id,
        )
        return await self.repo.create(attachment)

    async def list_attachments(self, entity_type: str, entity_id: uuid.UUID) -> list[Attachment]:
        return await self.repo.list_by_entity(entity_type, entity_id)

    async def get_attachment(self, attachment_id: uuid.UUID) -> Attachment:
        attachment = await self.repo.get_by_id(attachment_id)
        if not attachment:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anexo não encontrado.")
        return attachment

    def get_full_path(self, attachment: Attachment) -> Path:
        return self._resolve_inside_base(attachment.file_path)

    async def delete_attachment(self, attachment_id: uuid.UUID) -> None:
        attachment = await self.get_attachment(attachment_id)
        try:
            self.get_full_path(attachment).unlink(missing_ok=True)
        except OSError:
            logger.exception("Falha ao remover arquivo do anexo %s", attachment_id)
        await self.repo.soft_delete(attachment)
