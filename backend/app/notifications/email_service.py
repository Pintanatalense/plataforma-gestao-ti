"""
MOD-11 — Notificações por E-mail (Service)

Configuração SMTP (guardada em `channel_configs`, senha cifrada) e transporte SMTP.
O envio das notificações de negócio não acontece aqui: passa pelo outbox e pelo worker
(`notifications/channels/email.py`).
"""

import asyncio
import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Literal

from pydantic import BaseModel, EmailStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings_model import SystemSetting
from app.notifications.channel_store import load_channel, save_channel

logger = logging.getLogger(__name__)

EMAIL_CHANNEL = "email"
LEGACY_EMAIL_SETTING_KEY = "smtp_config"  # configuração antiga (senha em texto puro em system_settings)
MASKED_PASSWORD = "********"


class SmtpConfigSchema(BaseModel):
    is_enabled: bool = False
    host: str = "smtp.gmail.com"
    port: int = 587
    security: str = "STARTTLS"  # "NONE", "SSL_TLS", "STARTTLS"
    username: str = ""
    password: str = ""
    from_email: str = "suporte@empresa.com.br"
    from_name: str = "Service Desk - Gestão de TI"
    app_base_url: str = "http://localhost"


class SmtpTestEmailRequest(BaseModel):
    target_email: EmailStr
    host: str | None = None
    port: int | None = None
    security: str | None = None
    username: str | None = None
    password: str | None = None
    from_email: str | None = None
    from_name: str | None = None


SmtpOutcome = Literal["ok", "retryable", "permanent"]


def send_smtp_raw(
    config: SmtpConfigSchema, to_email: str, subject: str, html_body: str, text_body: str | None = None
) -> tuple[SmtpOutcome, str]:
    """Disparo SMTP síncrono (chamar em thread). Classifica a falha para a política de retentativa."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{config.from_name} <{config.from_email}>"
        msg["To"] = to_email

        if text_body:
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        if config.security == "SSL_TLS":
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(config.host, config.port, context=context, timeout=10.0) as server:
                if config.username and config.password:
                    server.login(config.username, config.password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(config.host, config.port, timeout=10.0) as server:
                server.ehlo()
                if config.security == "STARTTLS":
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                if config.username and config.password:
                    server.login(config.username, config.password)
                server.send_message(msg)

        logger.info("E-mail enviado para %s: %s", to_email, subject)
        return "ok", "E-mail enviado com sucesso."

    except smtplib.SMTPAuthenticationError as exc:
        # Credencial errada é problema de configuração: corrigir o canal faz o reenvio funcionar.
        return "retryable", f"Autenticação SMTP recusada: {exc}"
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as exc:
        code = getattr(exc, "smtp_code", 0) or 0
        return ("permanent" if 500 <= code < 600 else "retryable"), str(exc)
    except Exception as exc:  # timeout, DNS, conexão recusada, TLS...
        logger.warning("Falha no envio SMTP para %s: %s", to_email, exc)
        return "retryable", str(exc)


class EmailService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_config(self) -> SmtpConfigSchema:
        stored = await load_channel(self.session, EMAIL_CHANNEL)
        if stored is not None:
            try:
                return SmtpConfigSchema(
                    **stored.config, is_enabled=stored.enabled, password=stored.secrets.get("password", "")
                )
            except Exception:
                logger.exception("Configuração de e-mail inválida em channel_configs")
                return SmtpConfigSchema()

        # Instalações anteriores à Fase A: lê a configuração antiga até o primeiro salvamento.
        legacy = (
            await self.session.execute(select(SystemSetting).where(SystemSetting.key == LEGACY_EMAIL_SETTING_KEY))
        ).scalar_one_or_none()
        if legacy and legacy.metadata_json:
            try:
                return SmtpConfigSchema.model_validate(legacy.metadata_json)
            except Exception:
                pass
        return SmtpConfigSchema()

    async def update_config(self, new_config: SmtpConfigSchema) -> SmtpConfigSchema:
        # Mantém a senha atual se veio mascarada ou em branco
        if not new_config.password or new_config.password == MASKED_PASSWORD:
            new_config.password = (await self.get_config()).password

        dump = new_config.model_dump()
        password = dump.pop("password")
        enabled = dump.pop("is_enabled")
        await save_channel(self.session, EMAIL_CHANNEL, enabled, dump, {"password": password} if password else {})

        # A cópia antiga guardava a senha em texto puro: remove assim que a nova existe.
        await self.session.execute(delete(SystemSetting).where(SystemSetting.key == LEGACY_EMAIL_SETTING_KEY))
        await self.session.commit()
        return new_config

    async def test_smtp(self, req: SmtpTestEmailRequest) -> tuple[bool, str]:
        current_cfg = await self.get_config()
        typed_password = req.password if (req.password and req.password != MASKED_PASSWORD) else None
        target_host = (req.host or current_cfg.host).strip().lower()
        target_port = req.port or current_cfg.port
        target_user = req.username if req.username is not None else current_cfg.username
        same_endpoint = (
            target_host == (current_cfg.host or "").strip().lower()
            and target_port == current_cfg.port
            and target_user == current_cfg.username
        )
        # A senha guardada só pode ser usada contra o MESMO servidor, porta e usuário com que foi salva;
        # caso contrário, quem tem acesso à tela de teste poderia apontar o host para um servidor seu e capturá-la.
        if typed_password is None and not same_endpoint:
            return False, (
                "Para testar outro servidor, porta ou usuário, informe a senha: "
                "a senha salva só é usada com a configuração salva."
            )
        config = SmtpConfigSchema(
            is_enabled=True,
            host=req.host or current_cfg.host,
            port=req.port or current_cfg.port,
            security=req.security or current_cfg.security,
            username=req.username if req.username is not None else current_cfg.username,
            password=typed_password if typed_password is not None else current_cfg.password,
            from_email=req.from_email or current_cfg.from_email,
            from_name=req.from_name or current_cfg.from_name,
            app_base_url=current_cfg.app_base_url,
        )

        subject = "[Teste de Conexão] Plataforma de Gestão de TI"
        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
            <h2 style="color: #1976d2; margin-top: 0;">Teste de Envio de E-mail (SMTP)</h2>
            <p>Se você recebeu este e-mail, a configuração do servidor SMTP da <strong>Plataforma de Gestão de TI</strong> está funcionando perfeitamente!</p>
            <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="font-size: 12px; color: #666;">
                <strong>Servidor:</strong> {config.host}:{config.port} ({config.security})<br>
                <strong>Remetente:</strong> {config.from_email}<br>
                <strong>Data/Hora:</strong> {datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")}
            </p>
        </div>
        """
        outcome, detail = await asyncio.to_thread(
            send_smtp_raw, config, req.target_email, subject, html, "Teste de Conexão SMTP OK."
        )
        return outcome == "ok", detail
