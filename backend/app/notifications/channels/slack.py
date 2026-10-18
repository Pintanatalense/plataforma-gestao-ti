"""
Canal Slack (Web API via httpx; sem SDK). Saída = `chat.postMessage` para o id do usuário (mensagem direta
do app); entrada = Events API em `/integrations/slack/events` (ver `slack_webhook.py`).

Configuração em `channel_configs['slack']`: config = {bot_name, team_id, app_base_url},
segredos = {bot_token, signing_secret}.
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

SLACK_CHANNEL = "slack"
API_BASE = "https://slack.com/api"
MAX_TEXT = 3500  # o Slack trunca acima de ~4000 caracteres

# Erros em que reenviar não adianta: o destino ou a mensagem é o problema.
PERMANENT_ERRORS = {
    "channel_not_found", "user_not_found", "users_not_found", "is_archived", "user_disabled", "cannot_dm_bot",
    "not_in_channel", "msg_too_long", "no_text", "restricted_action", "cannot_reply_to_message",
}
# Erros de credencial: corrigir a configuração faz o reenvio funcionar.
AUTH_ERRORS = {"invalid_auth", "not_authed", "token_revoked", "token_expired", "account_inactive", "missing_scope"}


def http_client(timeout: float = 15.0) -> httpx.AsyncClient:
    """Ponto único de criação do cliente (os testes o substituem por um transporte falso)."""
    return httpx.AsyncClient(timeout=timeout)


async def api_call(token: str, method: str, payload: dict[str, Any] | None = None, timeout: float = 15.0) -> tuple[int, dict]:
    """Chama a Web API. Devolve (status HTTP, corpo JSON); `retry_after` do 429 entra no corpo."""
    try:
        async with http_client(timeout) as client:
            response = await client.post(
                f"{API_BASE}/{method}", json=payload or {}, headers={"Authorization": f"Bearer {token}"}
            )
    except httpx.HTTPError as exc:
        return 0, {"error": f"{type(exc).__name__}: {exc}"}
    try:
        body = response.json()
    except ValueError:
        body = {"error": response.text[:200]}
    if response.status_code == 429:
        body["retry_after"] = response.headers.get("Retry-After")
    return response.status_code, body


def classify(status: int, body: dict) -> DeliveryResult:
    """Traduz a resposta da Web API (quase sempre HTTP 200 com `ok`) para a política de retentativa."""
    error = str(body.get("error") or "")
    if status == 200 and body.get("ok"):
        return DeliveryResult("ok", provider_message_id=str(body.get("ts") or "") or None)
    if status == 429 or error == "ratelimited":
        retry_after = body.get("retry_after")
        seconds = int(retry_after) if str(retry_after or "").isdigit() else None
        return DeliveryResult("retryable", error="429 ratelimited", retry_after_seconds=seconds)
    if error in AUTH_ERRORS:
        return DeliveryResult("retryable", error=f"credencial do Slack inválida: {error}")
    if error in PERMANENT_ERRORS:
        return DeliveryResult("permanent", error=error)
    return DeliveryResult("retryable", error=f"{status or 'rede'} {error}".strip())


def render_text(message: Message, base_url: str | None) -> str:
    parts = [f"*{message.title}*" if message.title else "", message.body_text]
    if message.link and base_url:
        parts.append(f"<{base_url.rstrip('/')}{message.link}|Abrir no sistema>")
    text = "\n\n".join(p for p in parts if p)
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


class SlackAdapter:
    channel: ClassVar[str] = SLACK_CHANNEL
    capabilities: ClassVar[Capabilities] = Capabilities(inbound=True, max_len=MAX_TEXT, rate_per_second=1.0)

    def __init__(self, ctx: AdapterContext) -> None:
        self._session_factory = ctx.session_factory

    async def _config(self):
        async with self._session_factory() as session:
            return await load_channel(session, SLACK_CHANNEL)

    async def send(self, recipient: Recipient, message: Message) -> DeliveryResult:
        stored = await self._config()
        if stored is None or not stored.enabled or not stored.secrets.get("bot_token"):
            return DeliveryResult("permanent", error="Canal Slack desabilitado ou sem token.")
        text = render_text(message, stored.config.get("app_base_url"))
        status, body = await api_call(
            stored.secrets["bot_token"],
            "chat.postMessage",
            {"channel": recipient.address, "text": text, "unfurl_links": False, "unfurl_media": False},
        )
        return classify(status, body)

    async def health(self) -> ChannelHealth:
        stored = await self._config()
        if stored is None or not stored.enabled:
            return ChannelHealth(ok=False, detail="Desabilitado.")
        token = stored.secrets.get("bot_token")
        if not token:
            return ChannelHealth(ok=False, detail="Token do bot não configurado.")
        status, body = await api_call(token, "auth.test")
        if status == 200 and body.get("ok"):
            return ChannelHealth(ok=True, detail=f"{body.get('user', '?')} @ {body.get('team', '?')}")
        return ChannelHealth(ok=False, detail=f"{status or 'rede'}: {body.get('error', '')}")
