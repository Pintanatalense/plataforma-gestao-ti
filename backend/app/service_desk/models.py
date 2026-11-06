"""
MOD-04 — Service Desk (Models)

Entidades do módulo de Service Desk:
- TicketCategory
- Ticket
- TicketInteraction
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timestamps import TimestampMixin
import app.sla.models  # noqa: F401  (a FK sla_policy_id precisa da tabela no metadata)
from app.database import Base

if TYPE_CHECKING:
    from app.organization.models import Employee  # type: ignore
    from app.identity.models import UserAccount  # type: ignore


class TicketCategory(Base, TimestampMixin):
    __tablename__ = "sd_ticket_category"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_sector_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sectors.id"), nullable=True)
    form_schema: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # NULL = "Não se aplica": o chamado desta categoria não tem relógio de SLA (ADR-017).
    sla_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sla_policies.id", ondelete="SET NULL"), nullable=True, index=True
    )


class Ticket(Base, TimestampMixin):
    __tablename__ = "sd_ticket"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Enum-like strings: LOW, MEDIUM, HIGH, CRITICAL
    priority: Mapped[str] = mapped_column(String(50), nullable=False, default="LOW")
    
    # Enum-like strings: OPENED, IN_PROGRESS, PENDING, RESOLVED, CLOSED, CANCELED (só subchamados, ADR-026)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="OPENED")

    # Respostas aos pré-requisitos/formulário dinâmico da categoria
    custom_fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Relacionamentos Externos
    requester_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), nullable=False)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_accounts.id"), nullable=True)
    
    origin_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"), nullable=False)
    origin_sector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sectors.id"), nullable=False)
    responsible_sector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sectors.id"), nullable=False)
    
    # Relacionamento Interno
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sd_ticket_category.id"), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    # Quem abriu (pode ser diferente do solicitante, que é para quem o pedido é feito). Obrigatório em todo chamado
    # novo; nulo só nos antigos que a migration não conseguiu identificar, marcados com creator_unknown (o gatilho
    # sd_ticket_creator_guard impede um chamado novo de usar a marca).
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_accounts.id"), nullable=True, index=True
    )
    creator_unknown: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    # Chamados vinculados (ADR-026): um nível só. O filho é um chamado comum com fila, SLA e histórico próprios.
    parent_ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sd_ticket.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # Etapa obrigatória: enquanto não concluída (cancelada não conta), o principal não pode ser resolvido.
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), nullable=False)
    # Subchamado novo que substitui uma etapa cancelada (o cancelado fica como estava, só deixa de ser obrigatório).
    replaces_ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sd_ticket.id", ondelete="RESTRICT"), nullable=True
    )
    # Modelo de atendimento usado para pré-preencher os subchamados (só rastreio; ADR-026, PR 4).
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sd_ticket_templates.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "created_by_user_id IS NOT NULL OR creator_unknown", name="ck_sd_ticket_creator_known"
        ),
        CheckConstraint("parent_ticket_id IS NULL OR parent_ticket_id <> id", name="ck_sd_ticket_not_own_parent"),
    )

    # Relationships
    category: Mapped["TicketCategory | None"] = relationship("TicketCategory")
    interactions: Mapped[list["TicketInteraction"]] = relationship("TicketInteraction", back_populates="ticket", cascade="all, delete-orphan", lazy="selectin")
    materials: Mapped[list["TicketMaterial"]] = relationship("TicketMaterial", back_populates="ticket", cascade="all, delete-orphan", lazy="selectin")
    assets = relationship("Asset", secondary="sd_ticket_assets")
    requester: Mapped["Employee"] = relationship("Employee", foreign_keys=[requester_id], lazy="selectin")
    assignee: Mapped["UserAccount | None"] = relationship("UserAccount", foreign_keys=[assignee_id], lazy="selectin")
    created_by: Mapped["UserAccount | None"] = relationship(
        "UserAccount", foreign_keys=[created_by_user_id], lazy="selectin"
    )

    @property
    def created_by_name(self) -> str | None:
        """Nome de quem abriu; ``None`` nos chamados antigos sem criador registrado (a tela mostra "não registrado")."""
        if self.created_by:
            if getattr(self.created_by, "employee", None):
                return self.created_by.employee.name
            return self.created_by.email
        return None

    @property
    def requester_name(self) -> str | None:
        return self.requester.name if self.requester else None

    @property
    def requester_phone(self) -> str | None:
        return self.requester.phone if self.requester else None

    @property
    def assignee_name(self) -> str | None:

        if self.assignee:
            if getattr(self.assignee, "employee", None):
                return self.assignee.employee.name
            return self.assignee.email
        return None


@event.listens_for(Ticket.__table__, "after_create")
def _create_creator_guard(target, connection, **kw) -> None:
    """``create_all`` em PostgreSQL (testes) ganha o mesmo gatilho da migration."""
    if connection.dialect.name != "postgresql":
        return
    from app.service_desk.creator_ddl import CURRENT

    for statement in CURRENT:
        connection.exec_driver_sql(statement)


class TicketTemplate(Base, TimestampMixin):
    """Modelo de atendimento (ADR-026, PR 4): uma lista de subchamados que a tela usa para pré-preencher a abertura.

    O backend nunca cria nada a partir do modelo: recebe a lista explícita e aplica a cada item as regras de sempre
    (direcionamento, formulário, SLA). Nenhum nome de processo existe no código.
    """

    __tablename__ = "sd_ticket_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    items: Mapped[list["TicketTemplateItem"]] = relationship(
        "TicketTemplateItem", back_populates="template", cascade="all, delete-orphan",
        order_by="TicketTemplateItem.sort", lazy="selectin",
    )


class TicketTemplateItem(Base):
    __tablename__ = "sd_ticket_template_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sd_ticket_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sd_ticket_category.id"), nullable=False)
    # Nulo: o setor padrão da categoria, decidido na abertura.
    responsible_sector_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sectors.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_custom_fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    template: Mapped["TicketTemplate"] = relationship("TicketTemplate", back_populates="items")


class IdempotencyKey(Base):
    """Chave de idempotência das rotas de criação de chamados (ADR-026, PR 2b).

    A linha é reservada antes de criar qualquer coisa e gravada na mesma transação da criação: um rollback leva a
    chave junto. Presa a uma operação (``endpoint`` + ``target_id``): a mesma chave em outra operação é recusada.
    """

    __tablename__ = "sd_idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_sd_idempotency_keys_user_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    # Modelo da rota ("POST /tickets", "POST /tickets/{id}/children") e o principal, quando houver.
    endpoint: Mapped[str] = mapped_column(String(60), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


ticket_assets = Table(
    "sd_ticket_assets",
    Base.metadata,
    Column("ticket_id", ForeignKey("sd_ticket.id", ondelete="CASCADE"), primary_key=True),
    Column("asset_id", ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
)

class TicketMaterial(Base, TimestampMixin):
    __tablename__ = "sd_ticket_materials"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sd_ticket.id", ondelete="CASCADE"), nullable=False)
    stock_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stk_items.id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_accounts.id"), nullable=False)

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="materials")
    stock_item = relationship("StockItem")

class TicketInteraction(Base, TimestampMixin):
    __tablename__ = "sd_ticket_interaction"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sd_ticket.id"), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_accounts.id"), nullable=False)
    
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="interactions")
    author: Mapped["UserAccount"] = relationship("UserAccount", foreign_keys=[author_id], lazy="selectin")

    @property
    def author_email(self) -> str | None:
        return self.author.email if self.author else None

    @property
    def author_name(self) -> str | None:
        if self.author:
            if getattr(self.author, "employee", None):
                return self.author.employee.name
            if self.author.email:
                return self.author.email.split("@")[0].title()
        return None
