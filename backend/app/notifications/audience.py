"""
Resolução de audiência: transforma seletores de uma regra em usuários, a partir do payload do evento.

Seletores: requester, creator, assignee, sector_attendants, counterpart, admins, role:<nome>, user:<uuid>.
Só consulta por ids (identity/organization); não importa models de service_desk (ADR-004).
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import Permission, Role, UserAccount
from app.notifications.models import DomainEvent
from app.organization.models import Employee

ATTENDANT_PERMISSION = "service_desk.tickets.manage"


@dataclass(frozen=True)
class AudienceMember:
    user_id: uuid.UUID
    email: str


def _to_uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _users_by_ids(session: AsyncSession, ids: set[uuid.UUID]) -> list[UserAccount]:
    if not ids:
        return []
    stmt = select(UserAccount).where(UserAccount.id.in_(ids), UserAccount.is_active.is_(True))
    return list((await session.execute(stmt)).scalars().all())


async def _requester_user(session: AsyncSession, payload: dict) -> list[UserAccount]:
    employee_id = _to_uuid(payload.get("requester_employee_id"))
    if not employee_id:
        return []
    stmt = select(UserAccount).where(UserAccount.employee_id == employee_id, UserAccount.is_active.is_(True))
    return list((await session.execute(stmt)).scalars().all())


async def _sector_attendants(session: AsyncSession, payload: dict) -> list[UserAccount]:
    """Atendentes ativos do setor responsável (mesma regra de visibilidade da API de chamados)."""
    sector_id = _to_uuid(payload.get("responsible_sector_id"))
    if not sector_id:
        return []
    stmt = (
        select(UserAccount)
        .join(Employee, Employee.id == UserAccount.employee_id)
        .join(UserAccount.roles)
        .join(Role.permissions)
        .where(
            Employee.sector_id == sector_id,
            UserAccount.is_active.is_(True),
            Permission.code == ATTENDANT_PERMISSION,
        )
        .distinct()
    )
    return list((await session.execute(stmt)).scalars().all())


async def _role_users(session: AsyncSession, role_name: str) -> list[UserAccount]:
    stmt = (
        select(UserAccount)
        .join(UserAccount.roles)
        .where(Role.name == role_name, UserAccount.is_active.is_(True))
        .distinct()
    )
    return list((await session.execute(stmt)).scalars().all())


async def _admins(session: AsyncSession) -> list[UserAccount]:
    """Superadministradores e usuários do perfil Administrador."""
    stmt = (
        select(UserAccount)
        .outerjoin(UserAccount.roles)
        .where(UserAccount.is_active.is_(True), (UserAccount.is_admin.is_(True)) | (Role.name == "Administrador"))
        .distinct()
    )
    return list((await session.execute(stmt)).scalars().all())


async def _counterpart(session: AsyncSession, event: DomainEvent) -> list[UserAccount]:
    """O outro lado da conversa. Nota interna (DEC-012) nunca chega ao solicitante."""
    payload = event.payload or {}
    assignee_id = _to_uuid(payload.get("assignee_id"))
    assignee = await _users_by_ids(session, {assignee_id} if assignee_id else set())
    if payload.get("is_internal"):
        return assignee

    requesters = await _requester_user(session, payload)
    requester_ids = {u.id for u in requesters}
    if event.actor_user_id in requester_ids:
        return assignee
    return requesters


async def resolve_audience(
    session: AsyncSession, event: DomainEvent, selectors: list[str], exclude_actor: bool = True
) -> list[AudienceMember]:
    payload = event.payload or {}
    found: dict[uuid.UUID, UserAccount] = {}

    for selector in selectors:
        if selector == "requester":
            users = await _requester_user(session, payload)
        elif selector == "creator":
            # Quem abriu o chamado (pode ser diferente do solicitante; ADR-026).
            creator_id = _to_uuid(payload.get("created_by_user_id"))
            users = await _users_by_ids(session, {creator_id} if creator_id else set())
        elif selector == "assignee":
            assignee_id = _to_uuid(payload.get("assignee_id"))
            users = await _users_by_ids(session, {assignee_id} if assignee_id else set())
        elif selector == "sector_attendants":
            users = await _sector_attendants(session, payload)
        elif selector == "admins":
            users = await _admins(session)
        elif selector == "counterpart":
            users = await _counterpart(session, event)
        elif selector.startswith("role:"):
            users = await _role_users(session, selector.removeprefix("role:"))
        elif selector.startswith("user:"):
            user_id = _to_uuid(selector.removeprefix("user:"))
            users = await _users_by_ids(session, {user_id} if user_id else set())
        else:
            users = []
        for user in users:
            found[user.id] = user

    if exclude_actor and event.actor_user_id:
        found.pop(event.actor_user_id, None)
    return [AudienceMember(user_id=u.id, email=u.email) for u in found.values()]
