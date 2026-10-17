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
from app.core.exceptions import ForbiddenException, NotFoundException
from app.identity.repository import IdentityRepository
from app.service_desk.services import ServiceDeskService


class AttachmentAction(enum.StrEnum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"


async def ensure_attachment_access(
    *,
    db: AsyncSession,
    payload: dict,
    user_id: uuid.UUID,
    entity_type: AttachmentEntityType,
    entity_id: uuid.UUID,
    action: AttachmentAction,
    attachment: Attachment | None = None,
) -> None:
    """Levanta ``ForbiddenException``/``NotFoundException`` se o acesso não for permitido."""
    is_admin = bool(payload.get("is_admin", False))
    permissions = payload.get("permissions", [])

    user = await IdentityRepository(db).get_user(user_id)
    employee_id = user.employee_id if user else None

    if entity_type == AttachmentEntityType.TICKET:
        is_technician = is_admin or "service_desk.tickets.manage" in permissions
        can_read_all = is_admin or "service_desk.tickets.read_all" in permissions
        await ServiceDeskService(db).get_ticket_for_user(
            ticket_id=entity_id,
            user_employee_id=employee_id,
            is_technician=is_technician,
            can_read_all=can_read_all,
            user_id=user_id,
        )
        if action == AttachmentAction.DELETE and not (
            is_technician or can_read_all or (attachment and attachment.uploaded_by_id == user_id)
        ):
            raise ForbiddenException("Apenas técnicos, gestão ou quem enviou o arquivo podem removê-lo.")
        return

    if entity_type == AttachmentEntityType.ASSET:
        asset = await AssetRepository(db).get_asset(entity_id)
        if asset is None:
            raise NotFoundException("Ativo", entity_id)
        if is_admin:
            return
        if action == AttachmentAction.READ:
            if "assets.read" in permissions:
                return
            if "assets.read_own" in permissions and employee_id and asset.employee_id == employee_id:
                return
            raise ForbiddenException("Permissão insuficiente para acessar anexos deste ativo.")
        if "assets.write" in permissions:
            return
        raise ForbiddenException("Permissão 'assets.write' necessária para alterar anexos de ativos.")

    raise ForbiddenException("Tipo de entidade sem suporte a anexos.")
