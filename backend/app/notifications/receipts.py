"""
Confirmações do provedor (ADR-025 M1): o que aconteceu com a mensagem DEPOIS que o gateway a aceitou.

`deliveries.status = SENT` continua significando "aceito pelo gateway". Quando a integração informa mais (WhatsApp
Evolution e Meta Cloud API), a entrega ganha `provider_status`: accepted < delivered < read. O estado só avança;
`failed` vale apenas enquanto nada foi entregue (um "falhou" atrasado não desfaz um "lido").

Confirmação que chega antes de o worker gravar o id da mensagem (corrida rara: o provedor confirma em milissegundos)
não encontra a entrega e é ignorada; a confirmação seguinte (ex.: "lida") corrige o estado.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import Delivery

logger = logging.getLogger(__name__)

PROVIDER_STATUSES = ("accepted", "delivered", "read", "failed")
_RANK = {"accepted": 1, "delivered": 2, "read": 3}


@dataclass(frozen=True)
class Receipt:
    provider_message_id: str
    status: str  # um de PROVIDER_STATUSES
    at: datetime | None = None


def advances(current: str | None, new: str) -> bool:
    """O estado novo acrescenta informação ao atual?"""
    if new == "failed":
        return current in (None, "accepted")
    if current == "failed":
        return True  # entregue/lido depois de um erro informado: vale o que chegou depois
    return _RANK.get(new, 0) > _RANK.get(current or "", 0)


async def apply_receipts(session: AsyncSession, channel: str, receipts: list[Receipt]) -> int:
    """Aplica as confirmações às entregas do canal. Retorna quantas mudaram. O commit fica com o chamador."""
    changed = 0
    for receipt in receipts:
        if receipt.status not in PROVIDER_STATUSES or not receipt.provider_message_id:
            continue
        delivery = (
            await session.execute(
                select(Delivery)
                .where(Delivery.channel == channel, Delivery.provider_message_id == receipt.provider_message_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if delivery is None:
            logger.debug("Confirmação %s sem entrega conhecida em %s", receipt.status, channel)
            continue
        if not advances(delivery.provider_status, receipt.status):
            continue
        delivery.provider_status = receipt.status
        delivery.provider_status_at = receipt.at or datetime.now(timezone.utc)
        changed += 1
    return changed
