"""
MOD-03 — Recuperação de senha por e-mail (ADR-018).

Desligada por padrão. Só pode ser ligada com o SMTP habilitado, com TLS e homologado (teste de envio
bem-sucedido para o mesmo host/porta/usuário). O token nunca é guardado nem registrado: só o SHA-256.
"""

import asyncio
import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.repository import AuditRepository
from app.core.exceptions import BusinessRuleException, ForbiddenException, NotFoundException, ValidationException
from app.core.security import hash_password
from app.config import get_settings
from app.core.settings_model import SystemSetting
from app.database import AsyncSessionLocal
from app.identity.models import PasswordResetRequest, UserAccount
from app.identity.repository import IdentityRepository
from app.identity.services import IdentityService
from app.notifications.email_service import PASSWORD_RESET_KEY, EmailService, SmtpConfigSchema, send_smtp_raw

logger = logging.getLogger(__name__)

SETTING_KEY = PASSWORD_RESET_KEY
TOKEN_TTL = timedelta(minutes=30)
WINDOW = timedelta(hours=1)
LIMIT_PER_EMAIL = 3
LIMIT_PER_IP = 10
SECURE_MODES = ("STARTTLS", "SSL_TLS")

INVALID_LINK = "Link inválido ou expirado. Peça um novo link de recuperação."
_UNKNOWN_ENTITY = uuid.uuid5(uuid.NAMESPACE_OID, "password-reset:unknown")
_CONFIG_ENTITY = uuid.uuid5(uuid.NAMESPACE_OID, "password-reset:config")


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_email(email: str) -> str:
    """HMAC (com a chave da aplicação): um vazamento do banco não permite adivinhar e-mails por dicionário."""
    return hmac.new(get_settings().SECRET_KEY.encode("utf-8"), email.encode("utf-8"), hashlib.sha256).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def smtp_ready(config: SmtpConfigSchema, homologated: bool) -> bool:
    """SMTP apto a enviar links de recuperação: habilitado, com TLS e homologado."""
    return config.is_enabled and config.security in SECURE_MODES and homologated


class PasswordResetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = IdentityRepository(session)
        self.email = EmailService(session)

    # ------------------------------------------------------------------ estado / configuração
    async def _flag(self) -> bool:
        row = await self.session.get(SystemSetting, SETTING_KEY)
        return bool(row and row.value == "true")

    async def smtp_state(self) -> tuple[SmtpConfigSchema, bool]:
        config = await self.email.get_config()
        return config, smtp_ready(config, await self.email.is_homologated(config))

    async def is_enabled(self) -> bool:
        """Ligada pelo administrador E SMTP apto agora (se o SMTP quebrar, a recuperação some da tela)."""
        if not await self._flag():
            return False
        return (await self.smtp_state())[1]

    async def get_config(self) -> dict:
        _, ready = await self.smtp_state()
        return {"enabled": await self._flag(), "smtp_ready": ready}

    async def set_enabled(self, enabled: bool, user_id: uuid.UUID | None, is_admin: bool = False) -> dict:
        if enabled and not is_admin:
            # quem só gerencia o SMTP não pode abrir um caminho de troca de senha sem login
            raise ForbiddenException("Apenas administradores podem ativar a recuperação de senha.")
        if enabled:
            _, ready = await self.smtp_state()
            if not ready:
                raise BusinessRuleException(
                    "Para ativar, o SMTP precisa estar habilitado, com STARTTLS ou SSL/TLS, "
                    "e ter passado em um teste de envio com a configuração atual.",
                    rule="password_reset.smtp_not_ready",
                )
        row = await self.session.get(SystemSetting, SETTING_KEY)
        if row is None:
            self.session.add(SystemSetting(key=SETTING_KEY, value="true" if enabled else "false", metadata_json={}))
        else:
            row.value = "true" if enabled else "false"
        await AuditRepository(self.session).create(
            event_type="identity.password_reset_configured", entity_type="user", entity_id=_CONFIG_ENTITY,
            data={"enabled": enabled}, user_id=user_id,
        )
        await self.session.commit()
        return await self.get_config()

    async def _require_enabled(self) -> SmtpConfigSchema:
        if not await self._flag():
            raise NotFoundException("Recuperação de senha", "desabilitada")
        config, ready = await self.smtp_state()
        if not ready:
            raise NotFoundException("Recuperação de senha", "indisponível")
        return config

    # ------------------------------------------------------------------ pedido
    async def request(self, email: str, ip: str | None) -> tuple[SmtpConfigSchema, str, str] | None:
        """Registra o pedido. Devolve (config SMTP, e-mail, token) só quando há um e-mail a enviar."""
        config = await self._require_enabled()
        now = datetime.now(timezone.utc)
        email_norm = email.strip().lower()
        email_hash = hash_email(email_norm)
        since = now - WINDOW
        # "unknown" (sem cabeçalho) e valores gigantes não viram um balde global nem estouram a coluna
        if ip in (None, "", "unknown"):
            ip = None
        else:
            ip = ip[:50]

        # Serializa pedidos concorrentes do mesmo e-mail/IP: sem isso, pedidos em paralelo leem "contagem 0" e
        # todos passam pelo limite (e geram vários tokens válidos). No SQLite dos testes não há lock.
        if self.session.get_bind().dialect.name == "postgresql":
            for key in sorted({f"pwreset:e:{email_hash}", f"pwreset:i:{ip}"}):
                await self.session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": key})

        by_email = await self.session.scalar(
            select(func.count()).select_from(PasswordResetRequest).where(
                PasswordResetRequest.email_hash == email_hash, PasswordResetRequest.created_at > since
            )
        )
        by_ip = 0
        if ip:
            by_ip = await self.session.scalar(
                select(func.count()).select_from(PasswordResetRequest).where(
                    PasswordResetRequest.requested_ip == ip, PasswordResetRequest.created_at > since
                )
            )
        if (by_email or 0) >= LIMIT_PER_EMAIL or (by_ip or 0) >= LIMIT_PER_IP:
            return None  # a resposta ao cliente continua igual; só não cria token nem envia

        user = (
            await self.session.execute(
                select(UserAccount).where(func.lower(UserAccount.email) == email_norm, UserAccount.is_active.is_(True))
            )
        ).scalars().first()
        token: str | None = None
        record = PasswordResetRequest(email_hash=email_hash, requested_ip=ip, user_id=user.id if user else None)
        if user:
            # um novo pedido invalida os anteriores ainda abertos
            await self.session.execute(
                update(PasswordResetRequest)
                .where(
                    PasswordResetRequest.user_id == user.id,
                    PasswordResetRequest.used_at.is_(None),
                    PasswordResetRequest.token_hash.is_not(None),
                )
                .values(used_at=now)
            )
            token = secrets.token_urlsafe(32)
            record.token_hash = hash_secret(token)
            record.expires_at = now + TOKEN_TTL
        self.session.add(record)
        await AuditRepository(self.session).create(
            event_type="identity.password_reset_requested", entity_type="user",
            entity_id=user.id if user else _UNKNOWN_ENTITY, data={"ip": ip}, user_id=None,
        )
        await self.session.commit()
        if user and token:
            return config, user.email, token
        return None

    # ------------------------------------------------------------------ confirmação
    async def confirm(self, token: str, new_password: str, ip: str | None) -> None:
        await self._require_enabled()
        now = datetime.now(timezone.utc)
        record = (
            await self.session.execute(
                select(PasswordResetRequest).where(PasswordResetRequest.token_hash == hash_secret(token))
            )
        ).scalar_one_or_none()
        if (
            record is None
            or record.used_at is not None
            or record.expires_at is None
            or _aware(record.expires_at) <= now
            or record.user_id is None
        ):
            raise ValidationException(INVALID_LINK)
        user = await self.repo.get_user(record.user_id)
        if user is None:
            raise ValidationException(INVALID_LINK)

        # Uso único ATÔMICO: só um dos confirms simultâneos do mesmo token consegue marcar `used_at`.
        claimed = await self.session.execute(
            update(PasswordResetRequest)
            .where(
                PasswordResetRequest.id == record.id,
                PasswordResetRequest.used_at.is_(None),
                PasswordResetRequest.expires_at > now,
            )
            .values(used_at=now)
            .execution_options(synchronize_session=False)  # a avaliação em Python compararia datas naive x aware
        )
        if claimed.rowcount != 1:
            raise ValidationException(INVALID_LINK)

        user.hashed_password = hash_password(new_password)
        user.must_change_password = False
        IdentityService._clear_lockout(user)
        IdentityService._revoke_sessions(user)  # derruba qualquer sessão aberta com a senha antiga
        await self.session.execute(
            update(PasswordResetRequest)
            .where(
                PasswordResetRequest.user_id == user.id,
                PasswordResetRequest.used_at.is_(None),
                PasswordResetRequest.id != record.id,
            )
            .values(used_at=now)
        )
        await self.repo.update_user(user)
        await AuditRepository(self.session).create(
            event_type="identity.password_reset_completed", entity_type="user", entity_id=user.id,
            data={"ip": ip}, user_id=user.id,
        )
        await self.session.commit()


# ---------------------------------------------------------------------- envio (depois da resposta)
def build_reset_message(config: SmtpConfigSchema, token: str) -> tuple[str, str, str]:
    link = f"{config.app_base_url.rstrip('/')}/reset-password?token={token}"
    subject = "Recuperação de senha — Gestão de TI"
    minutes = int(TOKEN_TTL.total_seconds() // 60)
    text = (
        f"Recebemos um pedido para redefinir a sua senha.\n\nAbra o link (vale por {minutes} minutos e só pode "
        f"ser usado uma vez):\n{link}\n\nSe não foi você, ignore este e-mail: nada será alterado."
    )
    html = (
        '<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;padding:20px">'
        "<h2>Recuperação de senha</h2>"
        "<p>Recebemos um pedido para redefinir a sua senha.</p>"
        f'<p><a href="{link}" style="background:#1976d2;color:#fff;padding:10px 18px;border-radius:6px;'
        'text-decoration:none">Redefinir senha</a></p>'
        f"<p>O link vale por {minutes} minutos e só pode ser usado uma vez.</p>"
        '<p style="color:#666;font-size:12px">Se não foi você, ignore este e-mail: nada será alterado.</p></div>'
    )
    return subject, html, text


async def deliver_reset_email(config: SmtpConfigSchema, to_email: str, token: str) -> None:
    """Envia o link. Roda em background, depois da resposta 202; a falha só vai para a auditoria."""
    subject, html, text = build_reset_message(config, token)
    outcome, _detail = await asyncio.to_thread(send_smtp_raw, config, to_email, subject, html, text)
    if outcome == "ok":
        return
    # sem token e sem endereço no log: só o tipo da falha
    logger.warning("Falha ao enviar e-mail de recuperação de senha (%s)", outcome)
    try:
        async with AsyncSessionLocal() as session:
            await AuditRepository(session).create(
                event_type="identity.password_reset_send_failed", entity_type="user",
                entity_id=_UNKNOWN_ENTITY, data={"outcome": outcome}, user_id=None,
            )
            await session.commit()
    except Exception:  # a auditoria da falha não pode derrubar a tarefa
        logger.exception("Não foi possível auditar a falha de envio da recuperação de senha")
