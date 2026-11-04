"""
MOD-10 — Anexos (política de acesso por tipo de entidade)

Quem pode ler/enviar/apagar anexos depende da entidade dona do arquivo:
- TICKET: mesma regra de visibilidade do chamado; apagar exige ser técnico/gestão ou o autor do upload.
- ASSET: ler exige ``assets.read`` (ou ``assets.read_own`` sendo o responsável pelo ativo);
  enviar/apagar exige ``assets.write``.
"""

import enum
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.repository import AssetRepository
from app.attachments.models import Attachment
from app.attachments.service import AttachmentEntityType
from app.core.access import AccessContext
from app.core.exceptions import ForbiddenException, NotFoundException
from app.service_desk.services import ServiceDeskService


class AttachmentAction(enum.StrEnum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"


async def ensure_attachment_access(
    *,
    db: AsyncSession,
    access: AccessContext,
    entity_type: AttachmentEntityType,
    entity_id: uuid.UUID,
    action: AttachmentAction,
    attachment: Attachment | None = None,
) -> None:
    """Levanta ``ForbiddenException``/``NotFoundException`` se o acesso não for permitido."""
    if entity_type == AttachmentEntityType.TICKET:
        await ServiceDeskService(db).get_ticket_for_user(ticket_id=entity_id, **access.ticket_scope())
        if action == AttachmentAction.DELETE and not (
            access.is_technician or access.can_read_all or (attachment and attachment.uploaded_by_id == access.user_id)
        ):
            raise ForbiddenException("Apenas técnicos, gestão ou quem enviou o arquivo podem removê-lo.")
        return

    if entity_type == AttachmentEntityType.ASSET:
        asset = await AssetRepository(db).get_asset(entity_id)
        if asset is None:
            raise NotFoundException("Ativo", entity_id)
        if action == AttachmentAction.READ:
            if access.can_read_asset(asset):
                return
            raise ForbiddenException("Permissão insuficiente para acessar anexos deste ativo.")
        if access.has("assets.write"):
            return
        raise ForbiddenException("Permissão 'assets.write' necessária para alterar anexos de ativos.")

    raise ForbiddenException("Tipo de entidade sem suporte a anexos.")
