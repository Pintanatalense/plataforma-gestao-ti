"""
MOD-03 — Identidade (Services)

Regras de negócio para as entidades de identidade e controle de acesso.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import uuid
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.repository import AuditRepository
from app.core.exceptions import (
    AppException,
    BusinessRuleException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from app.core.security import create_access_token, hash_password, verify_password
from app.identity.models import Permission, Role, UserAccount
from app.identity.permission_catalog import CRITICAL_CODES
from app.identity.repository import IdentityRepository
from app.identity.schemas import (
    InitialSetup,
    RoleCreate,
    RoleUpdate,
    UserAccountCreate,
    UserAccountPasswordChange,
    UserAccountPasswordUpdate,
    UserAccountUpdate,
)

ADMIN_ROLE_NAME = "Administrador"
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15
# Hash bcrypt válido (de uma senha aleatória descartada), usado só para igualar o tempo de resposta.
_DUMMY_HASH = hash_password("dummy-password-for-timing-only")
# tentativas com e-mail inexistente não têm conta para ligar o registro: usam um identificador fixo
_UNKNOWN_ACCOUNT = uuid.uuid5(uuid.NAMESPACE_OID, "identity:unknown-account")


@dataclass(frozen=True)
class Actor:
    """Quem está executando a operação administrativa (vem do JWT já validado no banco)."""

    id: uuid.UUID
    is_admin: bool
    permissions: frozenset[str]

    @classmethod
    def from_payload(cls, payload: dict) -> "Actor":
        return cls(
            id=uuid.UUID(str(payload["sub"])),
            is_admin=bool(payload.get("is_admin")),
            permissions=frozenset(payload.get("permissions") or []),
        )


class IdentityService:
    def __init__(self, session: AsyncSession):
        self.repo = IdentityRepository(session)

    async def _audit(self, event_type: str, entity_id: uuid.UUID, data: dict, user_id: uuid.UUID | None) -> None:
        """Trilha de auditoria (MOD-12). Nunca recebe senha, token nem o texto digitado no campo de e-mail."""
        await AuditRepository(self.repo.session).create(
            event_type=event_type, entity_type="user", entity_id=entity_id, data=data, user_id=user_id
        )

    # ==========================================================================
    # Auth
    # ==========================================================================

    async def authenticate(self, email: str, password: str, ip_address: str | None = None) -> str:
        user = await self.repo.get_user_by_email(email)
        if not user:
            # Mesmo custo de uma verificação real, para não revelar se o e-mail existe pelo tempo de resposta.
            verify_password(password, _DUMMY_HASH)
            await self._audit("identity.login_failed", _UNKNOWN_ACCOUNT, {"ip": ip_address, "known_account": False}, None)
            await self.repo.session.commit()  # o get_db faria rollback ao levantar a exceção
            raise UnauthorizedException("Credenciais inválidas.")

        now = datetime.now(timezone.utc)
        locked_until = user.locked_until
        if locked_until is not None and locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until is not None and locked_until > now:
            await self._audit("identity.login_blocked", user.id, {"ip": ip_address}, user.id)
            await self.repo.session.commit()
            raise AppException(
                "Muitas tentativas inválidas. Tente novamente em alguns minutos.",
                code="ACCOUNT_LOCKED",
                status_code=429,
            )

        if not verify_password(password, user.hashed_password):
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= MAX_FAILED_LOGINS:
                user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                user.failed_login_count = 0
            await self.repo.update_user(user)
            await self._audit(
                "identity.login_failed", user.id,
                {"ip": ip_address, "known_account": True, "locked_now": user.locked_until is not None}, user.id,
            )
            # Persistir a tentativa antes de responder: o get_db faria rollback ao levantar a exceção.
            await self.repo.session.commit()
            raise UnauthorizedException("Credenciais inválidas.")

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        if ip_address:
            user.last_login_ip = ip_address
        await self.repo.update_user(user)
        await self._audit("identity.login_success", user.id, {"ip": ip_address}, user.id)

        return self._issue_token(user)

    @staticmethod
    def _revoke_sessions(user: UserAccount) -> None:
        """Invalida todos os tokens já emitidos para o usuário."""
        user.token_version = (user.token_version or 0) + 1

    @staticmethod
    def _clear_lockout(user: UserAccount) -> None:
        user.failed_login_count = 0
        user.locked_until = None

    def _issue_token(self, user: UserAccount) -> str:
        # Perfis dão as permissões comuns; críticas só por concessão explícita (mesmo que um perfil a contenha).
        roles = [r.name for r in user.roles]
        permissions = {p.code for r in user.roles for p in r.permissions} - CRITICAL_CODES
        permissions |= set(user.critical_permissions)

        token_data = {
            "sub": str(user.id),
            "roles": roles,
            "permissions": list(permissions),
            "is_admin": user.is_admin,
            "must_change_password": user.must_change_password,
            "tv": user.token_version or 0,
        }

        return create_access_token(data=token_data)

    # ==========================================================================
    # Setup inicial
    # ==========================================================================

    async def is_setup_required(self) -> bool:
        """A instalação é considerada nova enquanto não existir nenhuma conta."""
        return await self.repo.count_users() == 0

    async def setup_first_admin(self, schema: InitialSetup, ip_address: str | None = None) -> str:
        """
        Cria o primeiro administrador no primeiro acesso da instalação.

        Substitui a senha padrão do seed: quem instala define a própria senha.
        Bloqueado assim que existir qualquer usuário.
        """
        if not await self.is_setup_required():
            raise ConflictException("A configuração inicial já foi concluída.", {"rule": "identity.setup_done"})

        admin_role = await self.repo.get_role_by_name(ADMIN_ROLE_NAME)
        if admin_role is None:
            # Seed não executado: cria o perfil com todas as permissões comuns (críticas nunca vão em perfil).
            admin_role = Role(name=ADMIN_ROLE_NAME, description="Acesso total ao sistema.")
            admin_role.permissions = [p for p in await self.repo.list_permissions() if p.code not in CRITICAL_CODES]
            await self.repo.create_role(admin_role)
        else:
            # Recarrega com permissions (necessárias para montar o token).
            admin_role = await self.get_role(admin_role.id)

        user = UserAccount(
            email=schema.email,
            hashed_password=hash_password(schema.password),
            must_change_password=False,
            is_admin=True,
            last_login_at=datetime.now(timezone.utc),
            last_login_ip=ip_address,
        )
        user.roles = [admin_role]
        await self.repo.create_user(user)

        # Concessão inicial (A2): quem instala recebe as permissões críticas, registrado na auditoria.
        from app.identity.critical import CriticalGrantService
        from app.identity.permission_catalog import sync_permission_catalog

        await sync_permission_catalog(self.repo.session)
        await CriticalGrantService(self.repo.session).grant_all(
            user.id, via="setup", actor_id=user.id, reason="primeiro administrador (assistente de instalação)"
        )
        await self._audit("identity.setup_completed", user.id, {"ip": ip_address, "mode": schema.setup_mode}, user.id)
        await self.repo.session.refresh(user, ["critical_grants"])

        from app.core.starter_catalog import seed_starter_catalog
        await seed_starter_catalog(self.repo.session)

        if schema.setup_mode == "DEMO":
            from app.core.demo_service import DemoManagementService
            demo_svc = DemoManagementService(self.repo.session)
            await demo_svc.seed_demo_data(admin_user_id=user.id)
        else:
            # Modo CLEAN: Configuração de implantação empresarial limpa
            from app.organization.models import Company
            from app.core.settings_model import SystemSetting
            from sqlalchemy import select

            comp = (await self.repo.session.execute(select(Company).order_by(Company.created_at).limit(1))).scalars().first()
            if not comp:
                comp = Company(
                    name=schema.company_name or "Empresa Contratante S.A.",
                    cnpj=schema.company_cnpj or None,
                    is_demo=False,
                )
                self.repo.session.add(comp)
            else:
                if schema.company_name:
                    comp.name = schema.company_name
                if schema.company_cnpj:
                    comp.cnpj = schema.company_cnpj

            stmt_st = select(SystemSetting).where(SystemSetting.key == "system_mode")
            setting = (await self.repo.session.execute(stmt_st)).scalar_one_or_none()
            if not setting:
                setting = SystemSetting(key="system_mode", value="PRODUCTION")
                self.repo.session.add(setting)
            else:
                setting.value = "PRODUCTION"
            await self.repo.session.commit()

        return self._issue_token(user)

    # ==========================================================================
    # UserAccount
    # ==========================================================================

    async def get_user(self, user_id: uuid.UUID, include_inactive: bool = False) -> UserAccount:
        user = await self.repo.get_user(user_id, include_inactive=include_inactive)
        if not user:
            raise NotFoundException("Usuário", user_id)
        return user

    async def list_users(self, include_inactive: bool = True) -> Sequence[UserAccount]:
        return await self.repo.list_users(include_inactive=include_inactive)

    async def _resolve_roles(self, role_ids: list[uuid.UUID]) -> list[Role]:
        roles = list(await self.repo.get_roles_by_ids(role_ids))
        missing = set(role_ids) - {r.id for r in roles}
        if missing:
            raise NotFoundException("Perfil", ", ".join(str(m) for m in missing))
        return roles

    # --- Regras de não-escalada de privilégio ------------------------------------------------------

    @staticmethod
    def _role_codes(roles: Sequence[Role]) -> set[str]:
        return {p.code for r in roles for p in r.permissions}

    def _ensure_can_grant_roles(self, actor: Actor, roles: Sequence[Role]) -> None:
        """Quem não é admin só atribui perfis cujas permissões ele mesmo possui."""
        if actor.is_admin:
            return
        excess = self._role_codes(roles) - actor.permissions
        if excess:
            raise ForbiddenException(
                "Você não pode atribuir perfis com permissões que você não possui: " + ", ".join(sorted(excess))
            )

    def _ensure_can_manage_user(self, actor: Actor, target: UserAccount) -> None:
        """Não-admin não altera administradores nem quem tem mais poder do que ele."""
        if actor.is_admin:
            return
        if target.is_admin:
            raise ForbiddenException("Apenas administradores podem alterar uma conta de administrador.")
        if self._role_codes(target.roles) - actor.permissions:
            raise ForbiddenException("Você não pode alterar um usuário com mais permissões do que as suas.")

    async def _ensure_not_last_admin(self, target: UserAccount) -> None:
        """Impede ficar sem nenhum administrador ativo."""
        if target.is_admin and target.is_active and target.deleted_at is None:
            if await self.repo.count_active_admins(exclude_user_id=target.id) == 0:
                raise ConflictException("Não é possível remover, desativar ou rebaixar o último administrador ativo.")

    async def create_user(self, schema: UserAccountCreate, actor: Actor) -> UserAccount:
        if await self.repo.email_exists(schema.email):
            raise ConflictException("Email já cadastrado.", {"field": "email"})

        if schema.is_admin and not actor.is_admin:
            raise ForbiddenException("Apenas administradores podem criar outro administrador.")
        roles = await self._resolve_roles(schema.role_ids)
        self._ensure_can_grant_roles(actor, roles)

        user = UserAccount(
            employee_id=schema.employee_id,
            email=schema.email,
            hashed_password=hash_password(schema.password),
            must_change_password=schema.must_change_password,
            is_admin=schema.is_admin,
            is_active=schema.is_active if schema.is_active is not None else True,
        )
        user.roles = roles

        created = await self.repo.create_user(user)
        await self._audit(
            "identity.user_created", created.id,
            {"is_admin": created.is_admin, "roles": sorted(r.name for r in roles)}, actor.id,
        )
        return created

    async def update_user(self, user_id: uuid.UUID, schema: UserAccountUpdate, actor: Actor) -> UserAccount:
        user = await self.get_user(user_id, include_inactive=True)
        self._ensure_can_manage_user(actor, user)
        if schema.is_admin is not None and schema.is_admin != user.is_admin and not actor.is_admin:
            raise ForbiddenException("Apenas administradores podem conceder ou retirar o papel de administrador.")
        # rebaixar ou desativar o último administrador deixaria o sistema sem gestão
        if (schema.is_admin is False) or (schema.is_active is False):
            await self._ensure_not_last_admin(user)

        changes: list[str] = []
        if schema.email is not None and schema.email != user.email:
            if await self.repo.email_exists(schema.email):
                raise ConflictException("Email já cadastrado.", {"field": "email"})
            user.email = schema.email
            changes.append("email")

        if schema.must_change_password is not None:
            if schema.must_change_password != user.must_change_password:
                changes.append("must_change_password")
            user.must_change_password = schema.must_change_password

        if schema.is_admin is not None:
            if schema.is_admin != user.is_admin:
                self._revoke_sessions(user)
                changes.append("is_admin")
            user.is_admin = schema.is_admin

        if schema.role_ids is not None:
            new_roles = await self._resolve_roles(schema.role_ids)
            self._ensure_can_grant_roles(actor, new_roles)
            if {r.id for r in new_roles} != {r.id for r in user.roles}:
                self._revoke_sessions(user)
                changes.append("roles")
            user.roles = new_roles

        if schema.is_active is not None:
            if schema.is_active != user.is_active:
                self._revoke_sessions(user)
                changes.append("is_active")
            user.is_active = schema.is_active
            if not schema.is_active and user.deleted_at is None:
                user.soft_delete()
            elif schema.is_active and user.deleted_at is not None:
                user.restore()

        updated = await self.repo.update_user(user)
        if changes:
            await self._audit("identity.user_updated", user.id, {"changed": changes}, actor.id)
        return updated

    async def delete_user(self, user_id: uuid.UUID, actor: Actor) -> None:
        user = await self.get_user(user_id, include_inactive=True)
        self._ensure_can_manage_user(actor, user)
        await self._ensure_not_last_admin(user)
        self._revoke_sessions(user)
        user.soft_delete()
        await self.repo.update_user(user)
        await self._audit("identity.user_deactivated", user.id, {}, actor.id)

    async def update_password(
        self, user_id: uuid.UUID, schema: UserAccountPasswordUpdate, actor: Actor
    ) -> UserAccount:
        """Redefinição por administrador: a senha é temporária e deve ser trocada no próximo login."""
        user = await self.get_user(user_id)
        # sem esta trava, quem só tem identity.users.update assumiria a conta de um administrador
        self._ensure_can_manage_user(actor, user)
        user.hashed_password = hash_password(schema.password)
        user.must_change_password = True
        self._revoke_sessions(user)
        self._clear_lockout(user)
        updated = await self.repo.update_user(user)
        await self._audit("identity.password_reset_by_admin", user.id, {}, actor.id)
        return updated

    async def change_own_password(
        self, user_id: uuid.UUID, schema: UserAccountPasswordChange
    ) -> tuple[UserAccount, str]:
        """Troca de senha pelo próprio usuário, exigindo a senha atual.

        Encerra todas as outras sessões (token_version) e devolve um token novo para a sessão atual.
        """
        user = await self.get_user(user_id)
        if not verify_password(schema.current_password, user.hashed_password):
            raise BusinessRuleException("Senha atual incorreta.", rule="identity.current_password")
        if schema.current_password == schema.new_password:
            raise BusinessRuleException("A nova senha deve ser diferente da atual.", rule="identity.password_reuse")
        user.hashed_password = hash_password(schema.new_password)
        user.must_change_password = False
        self._revoke_sessions(user)
        self._clear_lockout(user)
        user = await self.repo.update_user(user)
        await self._audit("identity.password_changed", user.id, {}, user.id)
        return user, self._issue_token(user)

    # ==========================================================================
    # Role
    # ==========================================================================

    async def get_role(self, role_id: uuid.UUID) -> Role:
        role = await self.repo.get_role(role_id)
        if not role:
            raise NotFoundException("Perfil", role_id)
        return role

    async def list_roles(self) -> Sequence[Role]:
        return await self.repo.list_roles()

    async def _resolve_permissions(self, permission_ids: list[uuid.UUID]) -> list[Permission]:
        permissions = list(await self.repo.get_permissions_by_ids(permission_ids))
        missing = set(permission_ids) - {p.id for p in permissions}
        if missing:
            raise NotFoundException("Permissão", ", ".join(str(m) for m in missing))
        critical = sorted(p.code for p in permissions if p.code in CRITICAL_CODES)
        if critical:
            raise BusinessRuleException(
                "Permissões críticas não entram em perfil; conceda individualmente ao usuário: " + ", ".join(critical),
                rule="identity.critical.not_in_role",
            )
        return permissions

    def _ensure_can_grant_permissions(self, actor: Actor, permissions: Sequence[Permission]) -> None:
        if actor.is_admin:
            return
        excess = {p.code for p in permissions} - actor.permissions
        if excess:
            raise ForbiddenException(
                "Você não pode conceder permissões que você não possui: " + ", ".join(sorted(excess))
            )

    async def create_role(self, schema: RoleCreate, actor: Actor) -> Role:
        if await self.repo.get_role_by_name(schema.name):
            raise ConflictException(f"Já existe um perfil chamado '{schema.name}'.", {"field": "name"})

        role = Role(
            name=schema.name,
            description=schema.description
        )
        permissions = await self._resolve_permissions(schema.permission_ids)
        self._ensure_can_grant_permissions(actor, permissions)
        role.permissions = permissions

        created = await self.repo.create_role(role)
        await self._audit(
            "identity.role_created", created.id, {"name": created.name, "permissions": len(permissions)}, actor.id
        )
        return created

    async def update_role(self, role_id: uuid.UUID, schema: RoleUpdate, actor: Actor) -> Role:
        role = await self.get_role(role_id)
        # perfil que contém permissões além das do ator não pode ser reescrito por ele
        self._ensure_can_grant_permissions(actor, list(role.permissions))

        role_changes: list[str] = []
        if schema.name is not None and schema.name != role.name:
            if await self.repo.get_role_by_name(schema.name):
                raise ConflictException(f"Já existe um perfil chamado '{schema.name}'.", {"field": "name"})
            role.name = schema.name
            role_changes.append("name")
        if schema.description is not None:
            role.description = schema.description

        if schema.permission_ids is not None:
            permissions = await self._resolve_permissions(schema.permission_ids)
            self._ensure_can_grant_permissions(actor, permissions)
            if {p.id for p in permissions} != {p.id for p in role.permissions}:
                await self.repo.bump_token_version_for_role(role.id)
                role_changes.append("permissions")
            role.permissions = permissions

        updated_role = await self.repo.update_role(role)
        await self._audit("identity.role_updated", role.id, {"name": role.name, "changed": role_changes}, actor.id)
        return updated_role

    async def delete_role(self, role_id: uuid.UUID, actor: Actor) -> None:
        role = await self.get_role(role_id)
        self._ensure_can_grant_permissions(actor, list(role.permissions))
        await self.repo.bump_token_version_for_role(role.id)
        name = role.name
        await self.repo.delete_role(role)
        await self._audit("identity.role_deleted", role.id, {"name": name}, actor.id)

    # ==========================================================================
    # Permission
    # ==========================================================================

    async def list_permissions(self) -> Sequence[Permission]:
        return await self.repo.list_permissions()
