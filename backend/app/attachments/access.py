"""
MOD-10 — Anexos (política de acesso por tipo de entidade)

Quem pode ler/enviar/apagar anexos depende da entidade dona do arquivo:
- TICKET: mesma regra de visibilidade do chamado; apagar exige ser técnico/gestão ou o autor do upload.
  Anexo **restrito** (``is_internal``, ADR-026) segue a regra das notas internas do chamado: para quem não as vê, ele
  não existe (some da listagem; download e exclusão por id dão 404, para não confirmar que existe).
- ASSET: ler exige ``assets.read`` (ou ``assets.read_own`` sendo o responsável pelo ativo);
  enviar/apagar exige ``assets.write``. Anexo de ativo não pode ser restrito.

A checagem fica neste ponto único: toda rota de anexo (e as futuras) passa por aqui.
"""

import enum
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.repository import AssetRepository
from app.attachments.models import Attachment
from app.attachments.service import AttachmentEntityType
from app.core.access import AccessContext
from app.core.exceptions import ForbiddenException, NotFoundException, ValidationException
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
    is_internal: bool = False,
) -> bool:
    """Levanta ``ForbiddenException``/``NotFoundException`` se o acesso não for permitido.

    Devolve se quem pede vê anexos restritos da entidade (a listagem filtra por isso). ``is_internal``: o upload
    pede um anexo restrito.
    """
    if entity_type == AttachmentEntityType.TICKET:
        service = ServiceDeskService(db)
        scope = access.ticket_scope()
        ticket = await service.get_ticket_for_user(ticket_id=entity_id, **scope)
        sees_internal = await service.can_see_internal(ticket, access.can_internal_notes, **scope)
        if attachment is not None and attachment.is_internal and not sees_internal:
            raise NotFoundException("Anexo", attachment.id)
        if is_internal and not sees_internal:
            raise ForbiddenException("Só o setor que atende o chamado envia anexos restritos.")
        if action == AttachmentAction.DELETE and not (
            access.is_technician or access.can_read_all or (attachment and attachment.uploaded_by_id == access.user_id)
        ):
            raise ForbiddenException("Apenas técnicos, gestão ou quem enviou o arquivo podem removê-lo.")
        return sees_internal

    if is_internal:
        raise ValidationException("Só anexos de chamado podem ser restritos.")

    if entity_type == AttachmentEntityType.ASSET:
        asset = await AssetRepository(db).get_asset(entity_id)
        if asset is None:
            raise NotFoundException("Ativo", entity_id)
        if action == AttachmentAction.READ:
            if access.can_read_asset(asset):
                return True
            raise ForbiddenException("Permissão insuficiente para acessar anexos deste ativo.")
        if access.has("assets.write"):
            return True
        raise ForbiddenException("Permissão 'assets.write' necessária para alterar anexos de ativos.")

    raise ForbiddenException("Tipo de entidade sem suporte a anexos.")
