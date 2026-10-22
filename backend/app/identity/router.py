"""
MOD-03 — Identidade (Router)
"""

import uuid
from typing import Sequence

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user_id, get_current_user_ip, get_token_payload, require_permission
from app.database import get_db
from app.identity.schemas import (
    InitialSetup,
    PermissionOut,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    SetupStatus,
    Token,
    UserAccountCreate,
    UserAccountOut,
    UserAccountPasswordChange,
    UserAccountPasswordChangeOut,
    UserAccountPasswordUpdate,
    UserAccountUpdate,
)
from app.identity.services import Actor, IdentityService

router = APIRouter(prefix="/identity", tags=["Identity"])

# ==============================================================================
# Setup inicial (público — só funciona enquanto não houver usuários)
# ==============================================================================

@router.get("/setup/status", response_model=SetupStatus)
async def setup_status(db: AsyncSession = Depends(get_db)):
    service = IdentityService(db)
    return {"setup_required": await service.is_setup_required()}


@router.post("/setup", response_model=Token, status_code=status.HTTP_201_CREATED)
async def initial_setup(
    schema: InitialSetup,
    ip_address: str = Depends(get_current_user_ip),
    db: AsyncSession = Depends(get_db)
):
    service = IdentityService(db)
    token = await service.setup_first_admin(schema, ip_address)
    return {"access_token": token, "token_type": "bearer"}


# ==============================================================================
# Auth
# ==============================================================================

@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    ip_address: str = Depends(get_current_user_ip),
    db: AsyncSession = Depends(get_db)
):
    service = IdentityService(db)
    token = await service.authenticate(form_data.username, form_data.password, ip_address)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserAccountOut)
async def get_current_user(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    service = IdentityService(db)
    return await service.get_user(user_id)


@router.post("/me/password", response_model=UserAccountPasswordChangeOut)
async def change_own_password(
    schema: UserAccountPasswordChange,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    service = IdentityService(db)
    user, token = await service.change_own_password(user_id, schema)
    # Campos do usuário + token novo (o antigo deixou de valer): o frontend troca o token e segue logado.
    return {**UserAccountOut.model_validate(user).model_dump(), "access_token": token, "token_type": "bearer"}


# ==============================================================================
# Permissions
# ==============================================================================

@router.get("/permissions", response_model=list[PermissionOut], dependencies=[Depends(require_permission("identity.roles.read"))])
async def list_permissions(db: AsyncSession = Depends(get_db)):
    service = IdentityService(db)
    return await service.list_permissions()


# ==============================================================================
# Users
# ==============================================================================

@router.get("/users", response_model=list[UserAccountOut], dependencies=[Depends(require_permission("identity.users.read"))])
async def list_users(include_inactive: bool = True, db: AsyncSession = Depends(get_db)):
    service = IdentityService(db)
    return await service.list_users(include_inactive=include_inactive)


@router.post("/users", response_model=UserAccountOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("identity.users.create"))])
async def create_user(schema: UserAccountCreate, db: AsyncSession = Depends(get_db), payload: dict = Depends(get_token_payload)):
    service = IdentityService(db)
    return await service.create_user(schema, Actor.from_payload(payload))


@router.get("/users/{user_id}", response_model=UserAccountOut, dependencies=[Depends(require_permission("identity.users.read"))])
async def get_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = IdentityService(db)
    return await service.get_user(user_id, include_inactive=True)


@router.patch("/users/{user_id}", response_model=UserAccountOut, dependencies=[Depends(require_permission("identity.users.update"))])
async def update_user(user_id: uuid.UUID, schema: UserAccountUpdate, db: AsyncSession = Depends(get_db), payload: dict = Depends(get_token_payload)):
    service = IdentityService(db)
    return await service.update_user(user_id, schema, Actor.from_payload(payload))


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("identity.users.update"))])
async def delete_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db), payload: dict = Depends(get_token_payload)):
    service = IdentityService(db)
    await service.delete_user(user_id, Actor.from_payload(payload))
    return None


@router.patch("/users/{user_id}/password", response_model=UserAccountOut, dependencies=[Depends(require_permission("identity.users.update"))])
async def reset_password(
    user_id: uuid.UUID, schema: UserAccountPasswordUpdate, db: AsyncSession = Depends(get_db), payload: dict = Depends(get_token_payload)
):
    service = IdentityService(db)
    return await service.update_password(user_id, schema, Actor.from_payload(payload))


# ==============================================================================
# Roles
# ==============================================================================

@router.get("/roles", response_model=list[RoleOut], dependencies=[Depends(require_permission("identity.roles.read"))])
async def list_roles(db: AsyncSession = Depends(get_db)):
    service = IdentityService(db)
    return await service.list_roles()


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("identity.roles.create"))])
async def create_role(schema: RoleCreate, db: AsyncSession = Depends(get_db), payload: dict = Depends(get_token_payload)):
    service = IdentityService(db)
    return await service.create_role(schema, Actor.from_payload(payload))


@router.get("/roles/{role_id}", response_model=RoleOut, dependencies=[Depends(require_permission("identity.roles.read"))])
async def get_role(role_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = IdentityService(db)
    return await service.get_role(role_id)


@router.patch("/roles/{role_id}", response_model=RoleOut, dependencies=[Depends(require_permission("identity.roles.update"))])
async def update_role(role_id: uuid.UUID, schema: RoleUpdate, db: AsyncSession = Depends(get_db), payload: dict = Depends(get_token_payload)):
    service = IdentityService(db)
    return await service.update_role(role_id, schema, Actor.from_payload(payload))


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("identity.roles.update"))])
async def delete_role(role_id: uuid.UUID, db: AsyncSession = Depends(get_db), payload: dict = Depends(get_token_payload)):
    service = IdentityService(db)
    await service.delete_role(role_id, Actor.from_payload(payload))
    return None
