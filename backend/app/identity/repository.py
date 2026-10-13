"""
MOD-03 — Identidade (Repository)

Centraliza as queries no banco de dados para UserAccount, Role e Permission.
"""

import uuid
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.identity.models import Permission, Role, UserAccount


class IdentityRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ==========================================================================
    # UserAccount
    # ==========================================================================

    async def get_user(self, user_id: uuid.UUID, include_inactive: bool = False) -> UserAccount | None:
        stmt = select(UserAccount).options(
            selectinload(UserAccount.roles).selectinload(Role.permissions)
        ).where(UserAccount.id == user_id)
        if not include_inactive:
            stmt = stmt.where(UserAccount.is_active == True)
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> UserAccount | None:
        stmt = select(UserAccount).options(
            selectinload(UserAccount.roles).selectinload(Role.permissions)
        ).where(UserAccount.email == email, UserAccount.is_active == True)
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def email_exists(self, email: str) -> bool:
        """Considera também contas inativas (a constraint UNIQUE vale para todas)."""
        stmt = select(UserAccount.id).where(UserAccount.email == email)
        result = await self.session.execute(stmt)
        return result.first() is not None

    async def count_users(self) -> int:
        """Total de contas, incluindo inativas — usado para detectar instalação nova."""
        stmt = select(func.count()).select_from(UserAccount)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_users(self, include_inactive: bool = True) -> Sequence[UserAccount]:
        stmt = select(UserAccount).options(
            selectinload(UserAccount.roles).selectinload(Role.permissions)
        )
        if not include_inactive:
            stmt = stmt.where(UserAccount.is_active == True)
        stmt = stmt.order_by(UserAccount.email)
        
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_user(self, user: UserAccount) -> UserAccount:
        self.session.add(user)
        await self.session.flush()
        return user

    async def update_user(self, user: UserAccount) -> UserAccount:
        await self.session.flush()
        return user

    async def delete_role(self, role: Role) -> None:
        await self.session.delete(role)
        await self.session.flush()

    # ==========================================================================
    # Role
    # ==========================================================================

    async def get_role(self, role_id: uuid.UUID) -> Role | None:
        stmt = select(Role).options(
            selectinload(Role.permissions)
        ).where(Role.id == role_id)
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_roles(self) -> Sequence[Role]:
        stmt = select(Role).options(
            selectinload(Role.permissions)
        ).order_by(Role.name)
        
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_role_by_name(self, name: str) -> Role | None:
        stmt = select(Role).where(Role.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_roles_by_ids(self, role_ids: list[uuid.UUID]) -> Sequence[Role]:
        if not role_ids:
            return []
        stmt = select(Role).options(selectinload(Role.permissions)).where(Role.id.in_(role_ids))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_role(self, role: Role) -> Role:
        self.session.add(role)
        await self.session.flush()
        return role

    async def update_role(self, role: Role) -> Role:
        await self.session.flush()
        return role

    # ==========================================================================
    # Permission
    # ==========================================================================

    async def get_permission(self, permission_id: uuid.UUID) -> Permission | None:
        stmt = select(Permission).where(Permission.id == permission_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_permissions(self) -> Sequence[Permission]:
        stmt = select(Permission).order_by(Permission.code)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_permissions_by_ids(self, permission_ids: list[uuid.UUID]) -> Sequence[Permission]:
        if not permission_ids:
            return []
        stmt = select(Permission).where(Permission.id.in_(permission_ids))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_permission(self, permission: Permission) -> Permission:
        self.session.add(permission)
        await self.session.flush()
        return permission
