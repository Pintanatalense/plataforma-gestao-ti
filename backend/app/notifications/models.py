"""
MOD-11 — Notificações (Models)

Caixa de entrada in-app (`notifications`) e hub de entrega (ADR-013): outbox de eventos,
entregas com retentativa, regras de roteamento, configuração de canais e agenda do worker.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timestamps import TimestampMixin
from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_accounts.id"), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'info', 'warning', 'success', 'error'

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Vínculo opcional com a entidade de origem
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    user = relationship("UserAccount")


class DomainEvent(Base):
    """Fato de negócio gravado na mesma transação da mudança (padrão outbox)."""

    __tablename__ = "domain_events"
    __table_args__ = (Index("ix_domain_events_pending", "fanned_out_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    fanned_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NotificationRule(Base, TimestampMixin):
    """Regra evento -> audiência -> canais. As semeadas têm `code` e nunca são sobrescritas."""

    __tablename__ = "notification_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # exato ou prefixo "ticket.*"
    condition: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    audience: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    channels: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    template_code: Mapped[str] = mapped_column(String(100), nullable=False)


class Delivery(Base):
    """Uma mensagem para um destinatário por um canal, com estado de envio e retentativas."""

    __tablename__ = "deliveries"
    __table_args__ = (
        Index("ix_deliveries_dispatch", "status", "next_attempt_at"),
        # teto por pessoa por hora do WhatsApp (contagem de enviadas por canal, endereço e hora do envio)
        Index("ix_deliveries_channel_address_sent", "channel", "address", "sent_at"),
        # confirmação do provedor chega pelo webhook com o id da mensagem (ADR-025 M1)
        Index("ix_deliveries_channel_provider_message", "channel", "provider_message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("domain_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("notification_rules.id", ondelete="SET NULL"), nullable=True
    )
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    # Envio da Central de Mensagens a que pertence (ADR-025 M3); nulo nas entregas de regra, robô e mensagem direta.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("outbound_messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    # PENDING, SENDING, SENT, DEAD, SKIPPED, CANCELLED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    message: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # O que o provedor confirmou depois do envio: accepted, delivered, read, failed (ADR-025 §2). SENT só diz que o
    # gateway aceitou; nulo = o canal não informa ou ainda não informou.
    provider_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MessageTemplate(Base, TimestampMixin):
    """Modelo reutilizável da Central de Mensagens (ADR-025 §3). Corpo em marcação neutra (`**negrito**`, `- item`,
    links) e variáveis `{{nome}}`; cada canal o recebe no formato que suporta. As respostas rápidas do chamado
    continuam em `wa_templates`."""

    __tablename__ = "message_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    channels: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # vazio = qualquer canal
    subject: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )


class OutboundMessage(Base, TimestampMixin):
    """Um envio da Central (manual ou teste): o que foi pedido, a quem e quantos ficaram de fora. É o histórico que
    sobrevive à limpeza de 90 dias das entregas; o andamento de cada destinatário fica em `deliveries.message_id`."""

    __tablename__ = "outbound_messages"
    __table_args__ = (Index("ix_outbound_messages_author_created", "created_by", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")  # manual, test, scheduled
    # Ocorrência de um agendamento (M4): de qual agendamento e para que instante estava marcada
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("message_schedules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("message_templates.id", ondelete="SET NULL"), nullable=True
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    # [{user_id, email, outcome: queued | no_address | out_of_scope | inactive}] no momento do envio
    recipients: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    queued_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="QUEUED")  # QUEUED, CANCELLED
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )


class MessageSchedule(Base, TimestampMixin):
    """Envio da Central marcado para depois, uma vez ou recorrente (ADR-025 M4). O job `messages.schedules` cria uma
    `outbound_messages` por ocorrência, com a chave `schedule_id|instante`, e avança `next_run_at` na mesma transação.

    Recorrência: `once` (em `run_at`), `daily`, `weekly` (`weekdays`, 0 = segunda) ou `monthly` (`month_day`; em mês
    mais curto, o último dia), sempre às `time_of_day` no fuso `timezone`. Com `calendar_id` (calendário do SLA), dia
    sem expediente ou feriado é pulado (`non_business_rule = skip`) ou vai para o próximo dia útil (`next`)."""

    __tablename__ = "message_schedules"
    __table_args__ = (Index("ix_message_schedules_due", "status", "next_run_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("message_templates.id", ondelete="SET NULL"), nullable=True
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    recipient_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    recurrence: Mapped[str] = mapped_column(String(20), nullable=False)  # once, daily, weekly, monthly
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # só em once
    time_of_day: Mapped[str | None] = mapped_column(String(5), nullable=True)  # HH:MM nas recorrentes
    weekdays: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    month_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    calendar_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sla_calendars.id", ondelete="RESTRICT"), nullable=True
    )
    non_business_rule: Mapped[str] = mapped_column(String(10), nullable=False, default="skip")  # skip, next

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")  # ACTIVE, PAUSED, DONE, CANCELLED
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)  # sent, failed, missed
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    runs_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # ok, retryable, permanent
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ChannelConfig(Base, TimestampMixin):
    """Configuração de um canal; os segredos ficam cifrados (Fernet, APP_ENCRYPTION_KEY)."""

    __tablename__ = "channel_configs"

    channel: Mapped[str] = mapped_column(String(30), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    secrets_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)


class AutomationMark(Base):
    """Memória das automações: 'já avisei sobre isto'. A chave inclui o fato (ex.: item + faixa), então
    refazer o fato (nova garantia, estoque reabastecido) rearma o aviso."""

    __tablename__ = "automation_marks"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ScheduledJob(Base):
    """Agenda executada pelo worker: `every:<minutos>` ou `daily:HH:MM` no fuso do sistema."""

    __tablename__ = "scheduled_jobs"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    schedule: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Tentativas seguidas que falharam (a próxima nova tentativa é a de número retry_attempt + 1); 0 = em dia.
    retry_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class JobRun(Base):
    """Uma execução de um job (Plano de Evolução, Fase 0 PR 12).

    ``running`` com concessão (``lease_until``) renovada enquanto roda; no máximo uma ``running`` por job (índice
    único parcial). Concessão vencida = o worker caiu ou travou: a execução vira ``interrupted`` e entra na fila de
    nova tentativa. Status finais: ``ok``, ``error``, ``timeout`` (passou do tempo máximo e foi encerrada) e
    ``interrupted``.
    """

    __tablename__ = "job_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    isolated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "uq_job_runs_one_running",
            "job_name",
            unique=True,
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
        Index("ix_job_runs_job_started", "job_name", "started_at"),
    )


class UserNotificationPref(Base, TimestampMixin):
    """Preferências do usuário. O canal in-app não pode ser desligado (piso garantido)."""

    __tablename__ = "user_notification_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_accounts.id", ondelete="CASCADE"), primary_key=True)
    channels_disabled: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    categories_disabled: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    quiet_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quiet_start: Mapped[str] = mapped_column(String(5), nullable=False, default="20:00")
    quiet_end: Mapped[str] = mapped_column(String(5), nullable=False, default="07:00")
    critical_bypass: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class UserChannelAddress(Base, TimestampMixin):
    """Endereço do usuário num canal externo (ex.: chat id do Telegram), válido só após o vínculo por código."""

    __tablename__ = "user_channel_addresses"
    __table_args__ = (
        UniqueConstraint("channel", "address", name="uq_channel_address"),
        UniqueConstraint("user_id", "channel", name="uq_user_channel"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PushSubscription(Base):
    """Um navegador/aparelho que ativou o pop-up (Web Push). O endpoint identifica o aparelho, não a pessoa."""

    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(600), nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(String(200), nullable=False)
    auth: Mapped[str] = mapped_column(String(100), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChannelLinkCode(Base):
    """Código de uso único para vincular a conta a um canal. Guarda só o HMAC, nunca o código."""

    __tablename__ = "channel_link_codes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ConversationSession(Base):
    """Estado da conversa com um remetente externo (independe do transporte)."""

    __tablename__ = "conversation_sessions"
    __table_args__ = (UniqueConstraint("channel", "external_id", name="uq_conversation_sender"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True)
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="IDLE")
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_interaction_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class InboundMessage(Base):
    """Mensagem recebida já processada: a unicidade (canal, id) impede executar duas vezes numa reentrega."""

    __tablename__ = "inbound_messages"
    __table_args__ = (UniqueConstraint("channel", "message_id", name="uq_inbound_message"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    message_id: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeat"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    beat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    info: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
