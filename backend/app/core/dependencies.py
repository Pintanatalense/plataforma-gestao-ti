"""
Dependencies comuns injetáveis nos routers FastAPI.

Centraliza dependências reutilizáveis como:
- Sessão de banco
- Usuário autenticado
- Parâmetros de paginação
"""

from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import AppException, ForbiddenException, UnauthorizedException
from app.core.security import decode_access_token
from app.database import get_db
from app.identity.models import UserAccount


# Com troca de senha obrigatória pendente, só estas rotas funcionam.
_PASSWORD_CHANGE_ALLOWED_PATHS = {"/identity/me", "/identity/me/password"}


async def get_token_payload(
    request: Request,
    authorization: str | None = Header(None, description="Bearer token"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Valida o JWT e confere no banco que o usuário ainda existe e está ativo.

    As permissões continuam vindo do token (atualizadas a cada login); a flag ``is_admin`` do
    token só vale se o usuário ainda for admin no banco. Troca de senha obrigatória é imposta aqui.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedException("Token de autenticação inválido")

    payload = decode_access_token(authorization[7:])
    if payload is None:
        raise UnauthorizedException("Token expirado ou inválido")
    if payload.get("typ") == "ws":
        # Ticket de WebSocket (vai na URL e pode aparecer em log): só serve para abrir o WS.
        raise UnauthorizedException("Token inválido para esta operação")

    try:
        user_id = UUID(str(payload.get("sub")))
    except ValueError as exc:
        raise UnauthorizedException("Identificação de usuário inválida no token") from exc

    row = (
        await db.execute(
            select(
                UserAccount.is_active,
                UserAccount.is_admin,
                UserAccount.must_change_password,
                UserAccount.token_version,
            ).where(UserAccount.id == user_id)
        )
    ).first()
    if row is None or not row.is_active:
        raise UnauthorizedException("Usuário inexistente ou inativo")
    # Token sem `tv` (emitido antes do ADR-016) vale como versão 0, a de todo usuário existente.
    if int(payload.get("tv") or 0) != int(row.token_version or 0):
        raise UnauthorizedException("Sessão encerrada. Entre novamente.")

    payload["is_admin"] = bool(payload.get("is_admin")) and row.is_admin

    path = request.url.path.removeprefix(get_settings().API_V1_PREFIX)
    if row.must_change_password and path not in _PASSWORD_CHANGE_ALLOWED_PATHS:
        raise AppException(
            "É necessário trocar a senha antes de continuar.",
            code="PASSWORD_CHANGE_REQUIRED",
            status_code=403,
        )

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
    except ValueError as exc:
        raise UnauthorizedException("Identificação de usuário inválida no token") from exc


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


def require_any_permission(*required_permissions: str):
    """Libera se o usuário for admin ou tiver ao menos uma das permissões informadas."""
    async def _require_any_permission(payload: dict = Depends(get_token_payload)) -> None:
        if payload.get("is_admin"):
            return
        user_permissions = set(payload.get("permissions", []))
        if not user_permissions.intersection(required_permissions):
            raise ForbiddenException(
                "Permissão necessária: " + " ou ".join(f"'{p}'" for p in required_permissions) + "."
            )

    return _require_any_permission


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
