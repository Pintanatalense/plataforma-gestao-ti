"""
MOD-03 — Identidade (Services)

Regras de negócio para as entidades de identidade e controle de acesso.
"""

from datetime import datetime, timezone
import uuid
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event, event_bus
from app.core.exceptions import (
    BusinessRuleException,
    ConflictException,
    NotFoundException,
    UnauthorizedException,
)
from app.core.security import create_access_token, hash_password, verify_password
from app.identity.models import Permission, Role, UserAccount
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


class IdentityService:
    def __init__(self, session: AsyncSession):
        self.repo = IdentityRepository(session)

    # ==========================================================================
    # Auth
    # ==========================================================================

    async def authenticate(self, email: str, password: str, ip_address: str | None = None) -> str:
        user = await self.repo.get_user_by_email(email)
        if not user:
            raise UnauthorizedException("Credenciais inválidas.")
            
        if not verify_password(password, user.hashed_password):
            raise UnauthorizedException("Credenciais inválidas.")
            
        # Update login metadata
        user.last_login_at = datetime.now(timezone.utc)
        if ip_address:
            user.last_login_ip = ip_address
            
        await self.repo.update_user(user)
        
        return self._issue_token(user)

    def _issue_token(self, user: UserAccount) -> str:
        # Extrair permissions e roles (flat)
        roles = [r.name for r in user.roles]
        permissions = {p.code for r in user.roles for p in r.permissions}
        
        token_data = {
            "sub": str(user.id),
            "roles": roles,
            "permissions": list(permissions),
            "is_admin": user.is_admin,
            "must_change_password": user.must_change_password,
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
            # Seed não executado: cria o perfil com todas as permissões existentes.
            admin_role = Role(name=ADMIN_ROLE_NAME, description="Acesso total ao sistema.")
            admin_role.permissions = list(await self.repo.list_permissions())
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

        if schema.setup_mode == "DEMO":
            from app.core.demo_service import DemoManagementService
            demo_svc = DemoManagementService(self.repo.session)
            await demo_svc.seed_demo_data(admin_user_id=user.id)
        else:
            # Modo CLEAN: Configuração de implantação empresarial limpa
            from app.organization.models import Company
            from app.core.settings_model import SystemSetting
            from sqlalchemy import select

            stmt = select(Company)
            comp = (await self.repo.session.execute(stmt)).scalar_one_or_none()
            if not comp:
                comp = Company(
                    corporate_name=schema.company_name or "Empresa Contratante S.A.",
                    trade_name=schema.company_name or "Matriz",
                    cnpj=schema.company_cnpj or "00.000.000/0001-00",
                    is_demo=False
                )
                self.repo.session.add(comp)
            elif schema.company_name:
                comp.corporate_name = schema.company_name
                comp.trade_name = schema.company_name
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

    async def create_user(self, schema: UserAccountCreate) -> UserAccount:
        if await self.repo.email_exists(schema.email):
            raise ConflictException("Email já cadastrado.", {"field": "email"})
            
        roles = await self._resolve_roles(schema.role_ids)
        
        user = UserAccount(
            employee_id=schema.employee_id,
            email=schema.email,
            hashed_password=hash_password(schema.password),
            must_change_password=schema.must_change_password,
            is_admin=schema.is_admin,
            is_active=schema.is_active if schema.is_active is not None else True,
        )
        user.roles = roles
        
        return await self.repo.create_user(user)

    async def update_user(self, user_id: uuid.UUID, schema: UserAccountUpdate) -> UserAccount:
        user = await self.get_user(user_id, include_inactive=True)
        
        if schema.email is not None and schema.email != user.email:
            if await self.repo.email_exists(schema.email):
                raise ConflictException("Email já cadastrado.", {"field": "email"})
            user.email = schema.email
            
        if schema.must_change_password is not None:
            user.must_change_password = schema.must_change_password
            
        if schema.is_admin is not None:
            user.is_admin = schema.is_admin
            
        if schema.role_ids is not None:
            user.roles = await self._resolve_roles(schema.role_ids)

        if schema.is_active is not None:
            user.is_active = schema.is_active
            if not schema.is_active and user.deleted_at is None:
                user.soft_delete()
            elif schema.is_active and user.deleted_at is not None:
                user.restore()
            
        return await self.repo.update_user(user)

    async def delete_user(self, user_id: uuid.UUID) -> None:
        user = await self.get_user(user_id, include_inactive=True)
        user.soft_delete()
        await self.repo.update_user(user)

    async def update_password(self, user_id: uuid.UUID, schema: UserAccountPasswordUpdate) -> UserAccount:
        """Redefinição por administrador: a senha é temporária e deve ser trocada no próximo login."""
        user = await self.get_user(user_id)
        user.hashed_password = hash_password(schema.password)
        user.must_change_password = True
        return await self.repo.update_user(user)

    async def change_own_password(self, user_id: uuid.UUID, schema: UserAccountPasswordChange) -> UserAccount:
        """Troca de senha pelo próprio usuário, exigindo a senha atual."""
        user = await self.get_user(user_id)
        if not verify_password(schema.current_password, user.hashed_password):
            raise BusinessRuleException("Senha atual incorreta.", rule="identity.current_password")
        if schema.current_password == schema.new_password:
            raise BusinessRuleException("A nova senha deve ser diferente da atual.", rule="identity.password_reuse")
        user.hashed_password = hash_password(schema.new_password)
        user.must_change_password = False
        return await self.repo.update_user(user)

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
        return permissions

    async def create_role(self, schema: RoleCreate) -> Role:
        if await self.repo.get_role_by_name(schema.name):
            raise ConflictException(f"Já existe um perfil chamado '{schema.name}'.", {"field": "name"})

        role = Role(
            name=schema.name,
            description=schema.description
        )
        role.permissions = await self._resolve_permissions(schema.permission_ids)
        
        return await self.repo.create_role(role)

    async def update_role(self, role_id: uuid.UUID, schema: RoleUpdate) -> Role:
        role = await self.get_role(role_id)
        
        if schema.name is not None and schema.name != role.name:
            if await self.repo.get_role_by_name(schema.name):
                raise ConflictException(f"Já existe um perfil chamado '{schema.name}'.", {"field": "name"})
            role.name = schema.name
        if schema.description is not None:
            role.description = schema.description
            
        if schema.permission_ids is not None:
            role.permissions = await self._resolve_permissions(schema.permission_ids)
            
        return await self.repo.update_role(role)

    async def delete_role(self, role_id: uuid.UUID) -> None:
        role = await self.get_role(role_id)
        await self.repo.delete_role(role)

    # ==========================================================================
    # Permission
    # ==========================================================================

    async def list_permissions(self) -> Sequence[Permission]:
        return await self.repo.list_permissions()
