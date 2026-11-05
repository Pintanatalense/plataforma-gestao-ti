"""
MOD-12 — Auditoria (Models)

A trilha guarda, além do evento, QUEM (id, tipo e e-mail do ator no momento do evento), DE ONDE (IP confiável e id
da requisição) e a CATEGORIA (segurança ou operacional, que define a retenção). ``user_id`` não tem chave estrangeira:
apagar uma conta (por exemplo, da demonstração) não pode apagar nem alterar a trilha dela.

No PostgreSQL a tabela é só de inserção (ADR-023): gatilho, selo em cadeia de hash por categoria (``chain_pos``,
``prev_hash``, ``row_hash``, preenchidos só pela função ``audit_seal``) e retenção como único caminho de exclusão.
"""
import uuid
from contextvars import ContextVar
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, event, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.audit.categories import category_for
from app.core.timestamps import TimestampMixin
from app.database import Base

# IP do cliente da requisição em curso (preenchido pelo middleware com client_ip, regra do proxy confiável).
current_client_ip: ContextVar[str | None] = ContextVar("audit_client_ip", default=None)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Sem ator = evento do sistema (worker, migration, comando no servidor).
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    actor_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="system", server_default="system")
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, default="operational", server_default="operational", index=True
    )
    ip: Mapped[str | None] = mapped_column(String(50), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Selo da cadeia (por categoria). Nulos até o job audit.seal; a aplicação nunca os grava.
    chain_pos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (Index("uq_audit_logs_category_chain_pos", "category", "chain_pos", unique=True),)

    user = relationship(
        "UserAccount",
        primaryjoin="foreign(AuditLog.user_id) == UserAccount.id",
        lazy="selectin",
        viewonly=True,
    )

    @property
    def user_email(self) -> str | None:
        return self.user.email if self.user else self.actor_email

    @property
    def user_name(self) -> str | None:
        if self.user:
            if getattr(self.user, "employee", None):
                return self.user.employee.name
            return self.user.email.split("@")[0].title()
        return self.actor_email.split("@")[0].title() if self.actor_email else None


class AuditChainState(Base):
    """Fim e âncora de cada cadeia (a âncora é o hash do último registro apagado pela retenção)."""

    __tablename__ = "audit_chain_state"

    category: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_pos: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    anchor_pos: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    anchor_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


@event.listens_for(AuditLog.__table__, "after_create")
def _create_chain_objects(target, connection, **kw) -> None:
    """``create_all`` em PostgreSQL (testes) ganha o mesmo gatilho e as mesmas funções da migration."""
    if connection.dialect.name != "postgresql":
        return
    from app.audit.chain_ddl import CURRENT

    for statement in CURRENT:
        connection.exec_driver_sql(statement)


@event.listens_for(AuditLog, "before_insert")
def _fill_audit_context(mapper, connection, target: AuditLog) -> None:
    """Toda gravação (pelo repositório ou direta) sai com categoria, ator, IP e requisição."""
    from app.core.request_logging import current_request_id
    from app.identity.models import UserAccount

    target.category = category_for(target.event_type)
    if target.user_id is not None:
        target.actor_kind = "human"
        if target.actor_email is None:
            target.actor_email = connection.execute(
                select(UserAccount.email).where(UserAccount.id == target.user_id)
            ).scalar()
    else:
        target.actor_kind = target.actor_kind if target.actor_kind not in (None, "human") else "system"
    if target.ip is None:
        data_ip = (target.data or {}).get("ip") if isinstance(target.data, dict) else None
        target.ip = str(data_ip)[:50] if data_ip else current_client_ip.get()
    if target.request_id is None:
        request_id = current_request_id()
        target.request_id = None if request_id == "-" else request_id

