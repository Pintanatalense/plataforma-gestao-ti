"""
Registro dos canais. Adicionar um canal = um arquivo em `channels/` + uma linha aqui.
"""
from app.notifications.channels.base import AdapterContext, ChannelAdapter
from app.notifications.channels.email import EmailAdapter
from app.notifications.channels.in_app import InAppAdapter
from app.notifications.channels.telegram import TelegramAdapter
from app.notifications.channels.whatsapp import WhatsAppAdapter

ADAPTERS: dict[str, type] = {
    InAppAdapter.channel: InAppAdapter,
    EmailAdapter.channel: EmailAdapter,
    TelegramAdapter.channel: TelegramAdapter,
    WhatsAppAdapter.channel: WhatsAppAdapter,
}


def build_adapter(channel: str, ctx: AdapterContext) -> ChannelAdapter | None:
    adapter_cls = ADAPTERS.get(channel)
    return adapter_cls(ctx) if adapter_cls else None
