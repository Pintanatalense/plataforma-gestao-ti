import os
import uuid
import shutil
from typing import List
from fastapi import UploadFile, HTTPException, status

from app.attachments.models import Attachment
from app.attachments.repository import AttachmentRepository

# Diretório base para os uploads
UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")

class AttachmentService:
    def __init__(self, repo: AttachmentRepository):
        self.repo = repo
        # Garante que a pasta de uploads exista
        os.makedirs(UPLOADS_DIR, exist_ok=True)

    async def upload_file(
        self, 
        file: UploadFile, 
        entity_type: str, 
        entity_id: uuid.UUID, 
        user_id: uuid.UUID
    ) -> Attachment:
        
        # Cria uma subpasta para a entidade para organizar os arquivos
        entity_folder = os.path.join(UPLOADS_DIR, entity_type.lower(), str(entity_id))
        os.makedirs(entity_folder, exist_ok=True)
        
        # Gera um nome de arquivo único para não sobrescrever
        file_extension = ""
        if file.filename and "." in file.filename:
            file_extension = f".{file.filename.split('.')[-1]}"
            
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(entity_folder, unique_filename)
        
        # Salva o arquivo no disco (leitura em chunks se for assíncrono seria ideal, mas para simplificar shutil é ok se o file.file já estiver na memória/spool)
        # O FastAPI já suporta read assíncrono:
        size_bytes = 0
        with open(file_path, "wb") as buffer:
            while content := await file.read(1024 * 1024):  # 1MB chunks
                buffer.write(content)
                size_bytes += len(content)

        # Caminho relativo para salvar no banco
        relative_path = os.path.join(entity_type.lower(), str(entity_id), unique_filename).replace("\\", "/")

        attachment = Attachment(
            filename=file.filename or "unknown",
            content_type=file.content_type or "application/octet-stream",
            size_bytes=size_bytes,
            file_path=relative_path,
            entity_type=entity_type,
            entity_id=entity_id,
            uploaded_by_id=user_id
        )
        
        return await self.repo.create(attachment)

    async def list_attachments(self, entity_type: str, entity_id: uuid.UUID) -> List[Attachment]:
        return await self.repo.list_by_entity(entity_type, entity_id)

    async def get_attachment(self, attachment_id: uuid.UUID) -> Attachment:
        attachment = await self.repo.get_by_id(attachment_id)
        if not attachment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Anexo não encontrado."
            )
        return attachment

    def get_full_path(self, attachment: Attachment) -> str:
        return os.path.join(UPLOADS_DIR, os.path.normpath(attachment.file_path))

    async def delete_attachment(self, attachment_id: uuid.UUID) -> None:
        attachment = await self.get_attachment(attachment_id)
        
        # Removemos o arquivo fisicamente ou deixamos lá? (ADR-003: podemos remover fisicamente para poupar espaço)
        full_path = self.get_full_path(attachment)
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
            except Exception as e:
                # Log error
                pass
                
        await self.repo.soft_delete(attachment)
