"""Canal de e-mail (SMTP). A configuração vem de `channel_configs` a cada envio."""
import asyncio
from typing import ClassVar

from app.notifications.channels.base import (
    AdapterContext,
    Capabilities,
    ChannelHealth,
    DeliveryResult,
    Message,
    Recipient,
)
from app.notifications.email_service import EmailService, send_smtp_raw


class EmailAdapter:
    channel: ClassVar[str] = "email"
    capabilities: ClassVar[Capabilities] = Capabilities(rich_text=True, rate_per_second=2.0, formatting="html")

    def __init__(self, ctx: AdapterContext) -> None:
        self._session_factory = ctx.session_factory

    async def send(self, recipient: Recipient, message: Message) -> DeliveryResult:
        async with self._session_factory() as session:
            config = await EmailService(session).get_config()
        if not config.is_enabled:
            return DeliveryResult("permanent", error="Canal de e-mail desabilitado.")

        link = f"{config.app_base_url.rstrip('/')}{message.link}" if message.link else None
        text_body = message.body_text + (f"\n\nAbrir no sistema: {link}" if link else "")
        html_body = message.body_html or f"<p>{message.body_text}</p>"
        if link and message.body_html:
            html_body = html_body.replace("{{link}}", link)

        outcome, detail = await asyncio.to_thread(
            send_smtp_raw, config, recipient.address, message.title, html_body, text_body
        )
        if outcome == "ok":
            return DeliveryResult("ok")
        return DeliveryResult(outcome, error=detail)

    async def health(self) -> ChannelHealth:
        async with self._session_factory() as session:
            config = await EmailService(session).get_config()
        if not config.is_enabled:
            return ChannelHealth(ok=False, detail="Desabilitado.")
        return ChannelHealth(ok=True, detail=f"{config.host}:{config.port} ({config.security})")
