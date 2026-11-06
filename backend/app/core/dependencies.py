"""
Dependencies comuns injetáveis nos routers FastAPI.

Centraliza dependências reutilizáveis como:
- Sessão de banco
- Usuário autenticado
- Parâmetros de paginação
"""

import ipaddress
from functools import lru_cache
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import AppException, ForbiddenException, UnauthorizedException
from app.core.security import decode_access_token
from app.database import get_db
from app.identity.models import UserAccount
from app.core.access import AccessContext, build_access_context, has_permission as _has_permission


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


@lru_cache
def _trusted_proxies() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    raw = get_settings().TRUSTED_PROXIES
    return tuple(ipaddress.ip_network(item.strip(), strict=False) for item in raw.split(",") if item.strip())


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request: Request) -> str:
    """
    IP de quem fez a requisição, para auditoria, limites e logs.

    Os cabeçalhos de proxy só valem quando a conexão vem de um proxy confiável (``TRUSTED_PROXIES``, o Nginx do
    Compose). O Nginx sobrescreve ``X-Real-IP`` e ``X-Forwarded-For`` com o IP que ele viu; por isso o cliente não
    escolhe o próprio IP. Conexão direta de fora dessas redes: vale o IP da conexão e os cabeçalhos são ignorados.

    Proxy confiável sem cabeçalho válido devolve ``"unknown"``, nunca o IP do proxy: senão todos os clientes
    dividiriam o mesmo "IP" nos limites por IP (``"unknown"`` não conta como um IP).
    """
    peer = _valid_ip(request.client.host) if request.client else None
    if peer is None:
        return "unknown"
    if not any(ipaddress.ip_address(peer) in network for network in _trusted_proxies()):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0]
    return _valid_ip(request.headers.get("x-real-ip")) or _valid_ip(forwarded) or "unknown"


async def get_current_user_ip(request: Request) -> str:
    """Dependência FastAPI de ``client_ip``."""
    return client_ip(request)


def has_permission(payload: dict, code: str) -> bool:
    """
    Regra única de permissão a partir do token. Administrador passa em tudo, menos nas permissões críticas: essas
    exigem concessão explícita (``user_critical_grants``), que o login coloca em ``permissions``.
    """
    return _has_permission(bool(payload.get("is_admin")), payload.get("permissions", []), code)


async def get_access_context(
    payload: dict = Depends(get_token_payload),
    db: AsyncSession = Depends(get_db),
) -> AccessContext:
    """Contexto de acesso único da requisição (FastAPI reaproveita o mesmo objeto em todas as dependências)."""
    return await build_access_context(
        db, uuid_from_payload(payload), is_admin=payload.get("is_admin", False), permissions=payload.get("permissions")
    )


def uuid_from_payload(payload: dict) -> UUID:
    return UUID(str(payload["sub"]))


def require_any_permission(*required_permissions: str):
    """Libera se o usuário tiver ao menos uma das permissões informadas (admin: ver ``has_permission``)."""
    async def _require_any_permission(payload: dict = Depends(get_token_payload)) -> None:
        if not any(has_permission(payload, code) for code in required_permissions):
            raise ForbiddenException(
                "Permissão necessária: " + " ou ".join(f"'{p}'" for p in required_permissions) + "."
            )

    return _require_any_permission


def require_permission(required_permission: str):
    """
    Fábrica de dependências para verificar se o usuário tem a permissão requerida.
    Admin (is_admin=True) tem todas, exceto as críticas (``has_permission``).
    """
    async def _require_permission(payload: dict = Depends(get_token_payload)) -> None:
        if not has_permission(payload, required_permission):
            raise ForbiddenException(f"Permissão '{required_permission}' necessária.")
            
    return _require_permission
