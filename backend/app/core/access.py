"""
Contexto de acesso único (Plano de Evolução, Fase 0 PR 7; S1).

Quem é o principal, o que ele pode e de onde ele é (colaborador, unidade, setor), montado UMA vez por requisição e
usado por todas as regras de escopo: chamados, ativos, anexos, organização e o atendimento por chat. Antes cada
módulo montava o seu (um ``dict`` no router de chamados, ``UserCtx`` no chat, checagens soltas em ativos e anexos),
com o risco de uma rota nova esquecer uma regra.

A regra de permissão é a mesma de ``require_permission``: administrador tem todas, exceto as críticas, que só valem
por concessão individual (PR 5).
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.permission_catalog import CRITICAL_CODES, is_critical

TICKETS_MANAGE = "service_desk.tickets.manage"
TICKETS_READ_ALL = "service_desk.tickets.read_all"
INTERNAL_NOTES = "service_desk.interactions.internal"
TICKET_REPORTS = "service_desk.reports.read"
CREATE_ON_BEHALF = "service_desk.tickets.create_on_behalf"
ROUTE_ANY_SECTOR = "service_desk.tickets.route_any_sector"


def has_permission(is_admin: bool, permissions: frozenset[str] | set[str] | list[str], code: str) -> bool:
    if code in permissions:
        return True
    return bool(is_admin) and not is_critical(code)


@dataclass(frozen=True)
class AccessContext:
    user_id: uuid.UUID
    is_admin: bool
    permissions: frozenset[str]
    employee_id: uuid.UUID | None = None
    unit_id: uuid.UUID | None = None
    sector_id: uuid.UUID | None = None
    # Nome para mensagens (atendimento por chat); não participa de decisão de acesso.
    name: str = field(default="", compare=False)

    def has(self, code: str) -> bool:
        return has_permission(self.is_admin, self.permissions, code)

    # --- Chamados ---------------------------------------------------------------------------------------------

    @property
    def is_technician(self) -> bool:
        """Atendente: vê e atende os chamados do próprio setor, os atribuídos a si e os que abriu."""
        return self.has(TICKETS_MANAGE)

    @property
    def can_read_all(self) -> bool:
        """Gestão: vê todos os chamados."""
        return self.has(TICKETS_READ_ALL)

    @property
    def can_internal_notes(self) -> bool:
        return self.is_technician or self.has(INTERNAL_NOTES)

    @property
    def can_view_reports(self) -> bool:
        return self.has(TICKET_REPORTS)

    @property
    def can_create_on_behalf(self) -> bool:
        """Abrir chamado com outro colaborador como solicitante."""
        return self.has(CREATE_ON_BEHALF)

    @property
    def can_route_any_sector(self) -> bool:
        """Escolher setor responsável diferente do definido pela categoria."""
        return self.has(ROUTE_ANY_SECTOR)

    def ticket_scope(self) -> dict:
        """Argumentos de escopo que os serviços de chamados recebem."""
        return {
            "user_employee_id": self.employee_id,
            "user_id": self.user_id,
            "sector_id": self.sector_id,
            "is_technician": self.is_technician,
            "can_read_all": self.can_read_all,
        }

    # --- Ativos -----------------------------------------------------------------------------------------------

    def owns_asset(self, asset) -> bool:
        return self.employee_id is not None and asset.employee_id == self.employee_id

    def can_read_asset(self, asset) -> bool:
        """``assets.read`` vê todos; ``assets.read_own`` só os ativos sob sua responsabilidade."""
        return self.has("assets.read") or (self.has("assets.read_own") and self.owns_asset(asset))


async def _employee_scope(session: AsyncSession, employee_id: uuid.UUID | None):
    from app.organization.models import Employee

    if employee_id is None:
        return None
    return (await session.execute(select(Employee).where(Employee.id == employee_id))).scalar_one_or_none()


async def build_access_context(
    session: AsyncSession, user_id: uuid.UUID, *, is_admin: bool, permissions
) -> AccessContext:
    """Contexto de quem já foi autenticado (``is_admin`` e ``permissions`` vêm do token validado no banco)."""
    from app.identity.repository import IdentityRepository

    # Carrega a conta inteira (com colaborador), como o contexto antigo dos chamados: respostas como a de uma
    # interação nova leem ``author.employee`` e dependem dessa conta já estar carregada na sessão.
    user = await IdentityRepository(session).get_user(user_id)
    employee_id = user.employee_id if user else None
    employee = await _employee_scope(session, employee_id)
    return AccessContext(
        user_id=user_id,
        is_admin=bool(is_admin),
        permissions=frozenset(permissions or ()),
        employee_id=employee.id if employee else employee_id,
        unit_id=employee.unit_id if employee else None,
        sector_id=employee.sector_id if employee else None,
        name=employee.name if employee else "",
    )


async def load_access_context(session: AsyncSession, user_id: uuid.UUID) -> AccessContext | None:
    """
    Contexto a partir do banco, sem token (atendimento por chat): permissões ATUAIS, calculadas como no login
    (perfis sem as críticas + concessões individuais). Conta inexistente ou inativa => ``None``.
    """
    from app.identity.models import Permission, Role, UserAccount

    user = (await session.execute(select(UserAccount).where(UserAccount.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    role_codes = set(
        (
            await session.execute(
                select(Permission.code).join(Permission.roles).join(Role.users).where(UserAccount.id == user_id)
            )
        ).scalars()
    )
    permissions = (role_codes - CRITICAL_CODES) | set(user.critical_permissions)
    employee = await _employee_scope(session, user.employee_id)
    return AccessContext(
        user_id=user.id,
        is_admin=bool(user.is_admin),
        permissions=frozenset(permissions),
        employee_id=employee.id if employee else None,
        unit_id=employee.unit_id if employee else None,
        sector_id=employee.sector_id if employee else None,
        name=employee.name if employee else user.email.split("@")[0],
    )
