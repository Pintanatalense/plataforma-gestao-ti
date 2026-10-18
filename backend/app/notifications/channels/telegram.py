"""
Canal Telegram (Bot API via httpx; sem SDK). Saída = `sendMessage`; entrada = long polling no worker
(ver `telegram_poller.py`), então nada precisa ser exposto na internet.

Configuração em `channel_configs['telegram']`: config = {bot_username, app_base_url}, segredo = {bot_token}.
"""
import logging
from typing import Any, ClassVar

import httpx

from app.notifications.channel_store import load_channel
from app.notifications.channels.base import (
    AdapterContext,
    Capabilities,
    ChannelHealth,
    DeliveryResult,
    Message,
    Recipient,
)

# O token faz parte da URL da Bot API; o httpx loga cada requisição em INFO com a URL completa.
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

TELEGRAM_CHANNEL = "telegram"
API_BASE = "https://api.telegram.org"
MAX_TEXT = 4000  # limite da API é 4096


def http_client(timeout: float = 15.0) -> httpx.AsyncClient:
    """Ponto único de criação do cliente (os testes o substituem por um transporte falso)."""
    return httpx.AsyncClient(timeout=timeout)


async def api_call(token: str, method: str, payload: dict[str, Any] | None = None, timeout: float = 15.0) -> tuple[int, dict]:
    """Chama a Bot API. Devolve (status HTTP, corpo JSON). Erros de rede viram status 0."""
    try:
        async with http_client(timeout) as client:
            response = await client.post(f"{API_BASE}/bot{token}/{method}", json=payload or {})
    except httpx.HTTPError as exc:
        return 0, {"description": f"{type(exc).__name__}: {exc}"}
    try:
        body = response.json()
    except ValueError:
        body = {"description": response.text[:200]}
    return response.status_code, body


def classify(status: int, body: dict) -> DeliveryResult:
    """Traduz a resposta da Bot API para a política de retentativa do hub."""
    description = str(body.get("description") or "")
    if status == 200 and body.get("ok"):
        return DeliveryResult("ok", provider_message_id=str((body.get("result") or {}).get("message_id", "")) or None)
    if status == 429:
        retry_after = (body.get("parameters") or {}).get("retry_after")
        return DeliveryResult("retryable", error=f"429 {description}", retry_after_seconds=int(retry_after) if retry_after else None)
    if status in (401, 404):
        # Token revogado/errado: corrigir a configuração faz o reenvio funcionar.
        return DeliveryResult("retryable", error=f"{status} token do bot inválido: {description}")
    if status in (400, 403):
        # Chat inexistente, bot bloqueado pelo usuário, mensagem inválida: reenviar não adianta.
        return DeliveryResult("permanent", error=f"{status} {description}")
    return DeliveryResult("retryable", error=f"{status or 'rede'} {description}")


def render_text(message: Message, base_url: str | None) -> str:
    parts = [message.title, message.body_text]
    if message.link and base_url:
        parts.append(f"Abrir no sistema: {base_url.rstrip('/')}{message.link}")
    text = "\n\n".join(p for p in parts if p)
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


class TelegramAdapter:
    channel: ClassVar[str] = TELEGRAM_CHANNEL
    capabilities: ClassVar[Capabilities] = Capabilities(inbound=True, max_len=MAX_TEXT, rate_per_second=5.0)

    def __init__(self, ctx: AdapterContext) -> None:
        self._session_factory = ctx.session_factory

    async def _config(self):
        async with self._session_factory() as session:
            return await load_channel(session, TELEGRAM_CHANNEL)

    async def send(self, recipient: Recipient, message: Message) -> DeliveryResult:
        stored = await self._config()
        if stored is None or not stored.enabled or not stored.secrets.get("bot_token"):
            return DeliveryResult("permanent", error="Canal Telegram desabilitado ou sem token.")
        text = render_text(message, stored.config.get("app_base_url"))
        status, body = await api_call(
            stored.secrets["bot_token"],
            "sendMessage",
            {"chat_id": recipient.address, "text": text, "disable_web_page_preview": True},
        )
        return classify(status, body)

    async def health(self) -> ChannelHealth:
        stored = await self._config()
        if stored is None or not stored.enabled:
            return ChannelHealth(ok=False, detail="Desabilitado.")
        token = stored.secrets.get("bot_token")
        if not token:
            return ChannelHealth(ok=False, detail="Token do bot não configurado.")
        status, body = await api_call(token, "getMe")
        if status == 200 and body.get("ok"):
            return ChannelHealth(ok=True, detail=f"@{body['result'].get('username', '?')}")
        return ChannelHealth(ok=False, detail=f"{status or 'rede'}: {body.get('description', '')}")
