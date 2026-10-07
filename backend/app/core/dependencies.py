"""
Dependencies comuns injetáveis nos routers FastAPI.

Centraliza dependências reutilizáveis como:
- Sessão de banco
- Usuário autenticado
- Parâmetros de paginação
"""

from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import decode_access_token
from app.database import get_db


async def get_token_payload(
    authorization: str | None = Header(None, description="Bearer token"),
) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedException("Token de autenticação inválido")

    token = authorization[7:]
    payload = decode_access_token(token)

    if payload is None:
        raise UnauthorizedException("Token expirado ou inválido")

    return payload


async def get_current_user_id(
    payload: dict = Depends(get_token_payload),
) -> UUID:
    """
    Extrai o ID do usuário autenticado a partir do token JWT no header Authorization.

    Uso:
        @router.get("/protected")
        async def protected(user_id: UUID = Depends(get_current_user_id)):
            ...

    Raises:
        UnauthorizedException: se o token for inválido, expirado ou ausente
    """
    sub = payload.get("sub")
    if sub is None:
        raise UnauthorizedException("Token sem identificação de usuário")

    try:
        return UUID(sub)
    except ValueError:
        raise UnauthorizedException("Identificação de usuário inválida no token")


async def get_current_user_ip(
    x_forwarded_for: str | None = Header(None),
    x_real_ip: str | None = Header(None),
) -> str:
    """
    Extrai o IP do cliente da request.

    Considera headers de proxy reverso (Nginx).
    """
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    if x_real_ip:
        return x_real_ip
    return "unknown"


def require_permission(required_permission: str):
    """
    Fábrica de dependências para verificar se o usuário tem a permissão requerida.
    Admin (is_admin=True) sempre tem permissão.
    """
    async def _require_permission(payload: dict = Depends(get_token_payload)) -> None:
        if payload.get("is_admin"):
            return
            
        user_permissions = payload.get("permissions", [])
        if required_permission not in user_permissions:
            raise ForbiddenException(f"Permissão '{required_permission}' necessária.")
            
    return _require_permission
