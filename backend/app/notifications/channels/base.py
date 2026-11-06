"""Contrato dos canais de entrega (ADR-013, D3)."""
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import ClassVar, Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class Recipient:
    """Destino já resolvido: e-mail, id de usuário (in-app), chat id, telefone..."""

    address: str
    user_id: str | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class Message:
    title: str
    body_text: str
    body_html: str | None = None  # só e-mail; já escapado
    link: str | None = None  # caminho relativo dentro do sistema (ex.: /service-desk/<id>)
    priority: str = "normal"
    entity_type: str | None = None
    entity_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "body_text": self.body_text,
            "body_html": self.body_html,
            "link": self.link,
            "priority": self.priority,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(**{k: data.get(k) for k in ("title", "body_text", "body_html", "link", "entity_type", "entity_id")},
                   priority=data.get("priority") or "normal")


@dataclass(frozen=True)
class DeliveryResult:
    outcome: Literal["ok", "retryable", "permanent"]
    provider_message_id: str | None = None
    error: str | None = None
    retry_after_seconds: int | None = None
    # Adiada por ritmo/limite do próprio canal: volta à fila depois de `retry_after_seconds` SEM gastar tentativa
    # nem contar para o circuito (não houve falha, só esperamos a vez).
    deferred: bool = False


@dataclass(frozen=True)
class Capabilities:
    """O que a NOSSA integração com o canal faz hoje (não o que o provedor promete). A tela e o editor só oferecem o
    que estiver aqui (ADR-025 §4): recurso ligado sem código que o envie seria uma promessa falsa."""

    rich_text: bool = False
    inbound: bool = False
    max_len: int | None = None
    rate_per_second: float | None = None  # teto do canal; None = sem limite. O administrador só pode baixar.
    formatting: str = "plain"  # plain, html, whatsapp (*negrito*), slack (mrkdwn)
    attachments: bool = False
    typing: bool = False
    delivery_receipts: bool = False  # o provedor confirma "entregue" (deliveries.provider_status)
    read_receipts: bool = False  # e "lida"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ChannelHealth:
    ok: bool
    detail: str = ""


class ChannelAdapter(Protocol):
    channel: ClassVar[str]
    capabilities: ClassVar[Capabilities]

    async def send(self, recipient: Recipient, message: Message) -> DeliveryResult: ...

    async def health(self) -> ChannelHealth: ...


SessionFactory = Callable[[], AsyncSession]


@dataclass
class AdapterContext:
    """O que o worker entrega a cada adapter ao instanciá-lo."""

    session_factory: SessionFactory
    extra: dict = field(default_factory=dict)
