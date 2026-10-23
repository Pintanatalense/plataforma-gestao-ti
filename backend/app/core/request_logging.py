"""Registro de logs com identificador de requisição.

Cada requisição recebe um `X-Request-ID` (o do cliente, se tiver formato seguro; senão um novo). O id volta no
cabeçalho da resposta e aparece em todas as linhas de log emitidas durante a requisição, o que permite achar
no log o erro que um usuário relatou. O nível vem de `LOG_LEVEL`.
"""

import logging
import re
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_request_id: ContextVar[str] = ContextVar("request_id", default="-")

LOG_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"


def current_request_id() -> str:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """Acrescenta `request_id` a cada registro (necessário para o formato acima)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


def setup_logging(level: str = "INFO") -> None:
    """Configura o log da aplicação uma única vez (idempotente)."""
    root = logging.getLogger()
    numeric = logging.getLevelName(level.upper())
    root.setLevel(numeric if isinstance(numeric, int) else logging.INFO)
    for handler in root.handlers:
        if getattr(handler, "_hedu", False):
            return
    handler = logging.StreamHandler()
    handler._hedu = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)


class RequestIdMiddleware:
    """Middleware ASGI puro (não bufferiza o corpo, ao contrário do BaseHTTPMiddleware)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(REQUEST_ID_HEADER.encode(), b"").decode("latin-1")
        request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        token = _request_id.set(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [h for h in message.get("headers", []) if h[0].lower() != REQUEST_ID_HEADER.encode()]
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            _request_id.reset(token)
