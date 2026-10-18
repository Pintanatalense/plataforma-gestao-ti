"""
Entrada do Telegram por long polling (decisão do ADR-013: sem webhook, nada exposto na internet).

Roda como tarefa dentro do worker. O `offset` é recuperado do maior `update_id` já processado em
`inbound_messages`, então reiniciar o worker não repete nem perde mensagens (e a unicidade do
`update_id` protege contra qualquer repetição).
"""
import asyncio
import logging
import time
from collections import defaultdict, deque

from sqlalchemy import BigInteger, cast, func, select

from app.notifications.channel_store import load_channel
from app.notifications.channels.base import SessionFactory
from app.notifications.channels.telegram import TELEGRAM_CHANNEL, api_call
from app.notifications.conversation.inbound import process_inbound
from app.notifications.models import InboundMessage

logger = logging.getLogger(__name__)

POLL_TIMEOUT = 25  # segundos de long polling na API
IDLE_SLEEP = 10.0  # canal desabilitado/sem token: confere a configuração de tempos em tempos
MAX_PER_MINUTE = 20


class SenderRateLimiter:
    """Limite por remetente para impedir inundação de chamados/respostas (janela deslizante de 60 s)."""

    def __init__(self, limit: int = MAX_PER_MINUTE, window: float = 60.0) -> None:
        self.limit, self.window = limit, window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, sender: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        hits = self._hits[sender]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


def parse_update(update: dict) -> tuple[str, str, str] | None:
    """(message_id, external_id, texto) de uma mensagem de texto em chat privado; senão None."""
    message = update.get("message")
    if not message or not isinstance(message.get("text"), str):
        return None
    chat = message.get("chat") or {}
    if chat.get("type") != "private" or "id" not in chat:
        return None  # grupos e canais ficam de fora: o bot atende pessoas, não salas
    return str(update["update_id"]), str(chat["id"]), message["text"]


async def handle_update(session_factory: SessionFactory, update: dict, limiter: SenderRateLimiter) -> bool:
    parsed = parse_update(update)
    if parsed is None:
        return False
    message_id, external_id, text = parsed
    if not limiter.allow(external_id):
        logger.warning("Telegram: remetente %s acima do limite; mensagem descartada.", external_id)
        return False
    async with session_factory() as session:
        processed = await process_inbound(session, TELEGRAM_CHANNEL, message_id, external_id, text)
        await session.commit()
    return processed


async def last_update_id(session_factory: SessionFactory) -> int | None:
    async with session_factory() as session:
        return (
            await session.execute(
                select(func.max(cast(InboundMessage.message_id, BigInteger))).where(
                    InboundMessage.channel == TELEGRAM_CHANNEL
                )
            )
        ).scalar_one_or_none()


async def poll_once(session_factory: SessionFactory, token: str, offset: int | None, limiter: SenderRateLimiter) -> tuple[int | None, int | None]:
    """Uma chamada de getUpdates. Retorna (novo offset, status HTTP)."""
    payload: dict = {"timeout": POLL_TIMEOUT, "allowed_updates": ["message"]}
    if offset is not None:
        payload["offset"] = offset
    status, body = await api_call(token, "getUpdates", payload, timeout=POLL_TIMEOUT + 10)
    if status != 200 or not body.get("ok"):
        logger.warning("Telegram getUpdates falhou (%s): %s", status, body.get("description"))
        return offset, status
    for update in body.get("result", []):
        offset = update["update_id"] + 1
        try:
            await handle_update(session_factory, update, limiter)
        except Exception:
            # Uma mensagem problemática não pode travar a fila nem ser reprocessada para sempre.
            logger.exception("Falha ao processar update %s do Telegram", update.get("update_id"))
    return offset, status


async def poll_forever(session_factory: SessionFactory, stop: asyncio.Event, wake: asyncio.Event | None = None) -> None:
    limiter = SenderRateLimiter()
    offset: int | None = None
    failures = 0
    while not stop.is_set():
        async with session_factory() as session:
            stored = await load_channel(session, TELEGRAM_CHANNEL)
        token = stored.secrets.get("bot_token") if stored and stored.enabled else None
        if not token:
            offset = None
            await _sleep(stop, IDLE_SLEEP)
            continue

        if offset is None:
            last = await last_update_id(session_factory)
            offset = last + 1 if last is not None else None

        new_offset, status = await poll_once(session_factory, token, offset, limiter)
        if status == 200:
            failures = 0
            if new_offset != offset and wake is not None:
                wake.set()  # há respostas na fila: o dispatcher não precisa esperar o próximo ciclo
            offset = new_offset
        else:
            failures += 1
            await _sleep(stop, min(60.0, 2.0**failures))


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
