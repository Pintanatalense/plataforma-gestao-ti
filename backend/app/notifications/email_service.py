"""
MOD-11 — Notificações por E-mail (Service)

Envio de e-mails transacionais via SMTP:
- Configuração e persistência de parâmetros SMTP (armazenamento seguro via SystemSetting)
- Teste de conectividade e entrega de e-mail
- Notificações de respostas em chamados com respeito estrito à regra de privacidade DEC-012
"""

import asyncio
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleException
from app.core.settings_model import SystemSetting
from app.identity.models import UserAccount
from app.service_desk.models import Ticket, TicketInteraction

logger = logging.getLogger(__name__)

EMAIL_SETTING_KEY = "smtp_config"


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


class EmailService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_config(self) -> SmtpConfigSchema:
        stmt = select(SystemSetting).where(SystemSetting.key == EMAIL_SETTING_KEY)
        setting = (await self.session.execute(stmt)).scalar_one_or_none()
        if not setting or not setting.metadata_json:
            return SmtpConfigSchema()
        try:
            return SmtpConfigSchema.model_validate(setting.metadata_json)
        except Exception:
            return SmtpConfigSchema()

    async def update_config(self, new_config: SmtpConfigSchema) -> SmtpConfigSchema:
        stmt = select(SystemSetting).where(SystemSetting.key == EMAIL_SETTING_KEY)
        setting = (await self.session.execute(stmt)).scalar_one_or_none()

        # Preserva senha se veio mascarada ou em branco
        if setting and setting.metadata_json:
            old_pw = setting.metadata_json.get("password", "")
            if not new_config.password or new_config.password == "********":
                new_config.password = old_pw

        dump = new_config.model_dump()
        if not setting:
            setting = SystemSetting(key=EMAIL_SETTING_KEY, value="SMTP", metadata_json=dump)
            self.session.add(setting)
        else:
            setting.metadata_json = dump

        await self.session.commit()
        return new_config

    def _send_smtp_raw(
        self,
        config: SmtpConfigSchema,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str | None = None
    ) -> tuple[bool, str]:
        """Disparo síncrono SMTP em thread pool."""
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
                        context = ssl.create_default_context()
                        server.starttls(context=context)
                        server.ehlo()
                    if config.username and config.password:
                        server.login(config.username, config.password)
                    server.send_message(msg)

            logger.info("E-mail enviado com sucesso para %s: %s", to_email, subject)
            return True, "E-mail enviado com sucesso."

        except Exception as exc:
            err_msg = f"Falha no envio SMTP para {to_email}: {exc}"
            logger.warning(err_msg)
            return False, str(exc)

    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str | None = None
    ) -> tuple[bool, str]:
        config = await self.get_config()
        if not config.is_enabled:
            logger.debug("Envio de e-mail desativado nas configurações do sistema.")
            return False, "Notificações por e-mail desativadas."

        return await asyncio.to_thread(self._send_smtp_raw, config, to_email, subject, html_body, text_body)

    async def test_smtp(self, req: SmtpTestEmailRequest) -> tuple[bool, str]:
        current_cfg = await self.get_config()
        config = SmtpConfigSchema(
            is_enabled=True,
            host=req.host or current_cfg.host,
            port=req.port or current_cfg.port,
            security=req.security or current_cfg.security,
            username=req.username if req.username is not None else current_cfg.username,
            password=req.password if (req.password and req.password != "********") else current_cfg.password,
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
        return await asyncio.to_thread(self._send_smtp_raw, config, req.target_email, subject, html, "Teste de Conexão SMTP OK.")

    async def notify_ticket_interaction(
        self,
        ticket: Ticket,
        interaction: TicketInteraction,
        author: UserAccount
    ) -> None:
        """
        Detecta e dispara notificação por e-mail respeitando a regra DEC-012:
        - Interações internas (is_internal=True) JAMAIS são enviadas para o solicitante!
        - Interações públicas (is_internal=False) notificam a contraparte do atendimento.
        """
        config = await self.get_config()
        if not config.is_enabled:
            return

        # 1. Obter e-mail do solicitante
        requester_email = None
        if ticket.requester:
            if getattr(ticket.requester, "user_account", None):
                requester_email = ticket.requester.user_account.email
            else:
                stmt_u = select(UserAccount).where(UserAccount.employee_id == ticket.requester.id)
                u_res = (await self.session.execute(stmt_u)).scalar_one_or_none()
                if u_res:
                    requester_email = u_res.email

        # 2. Obter e-mail do atendente atribuído
        assignee_email = None
        if ticket.assignee:
            assignee_email = ticket.assignee.email

        # Decisão de destinatários
        recipient_emails = []

        if interaction.is_internal:
            # REGRA DEC-012: NOTA INTERNA NUNCA VAI PARA O SOLICITANTE!
            # Notifica apenas o atendente responsável se ele não for o autor da nota
            if assignee_email and assignee_email != author.email:
                recipient_emails.append(assignee_email)
            logger.info("[E-mail] Nota interna no chamado #%s — Solicitante não notificado (DEC-012). Destinatários: %s", ticket.id, recipient_emails)
        else:
            # RESPOSTA PÚBLICA:
            # Se autor é o solicitante -> notifica atendente responsável
            if author.email == requester_email:
                if assignee_email:
                    recipient_emails.append(assignee_email)
            else:
                # Se autor é atendente ou admin -> notifica solicitante
                if requester_email and requester_email != author.email:
                    recipient_emails.append(requester_email)

        if not recipient_emails:
            return

        # 3. Montar template do e-mail
        short_id = str(ticket.id)[:8]
        subject = f"[Chamado #{short_id}] Nova resposta: {ticket.title}"
        author_name = getattr(author.employee, "name", None) or author.email.split("@")[0].title()
        action_type = "comentário interno" if interaction.is_internal else "nova mensagem"
        ticket_url = f"{config.app_base_url.rstrip('/')}/service-desk/{ticket.id}"

        html_body = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 640px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px; background-color: #ffffff;">
            <div style="border-bottom: 2px solid #3b82f6; padding-bottom: 12px; margin-bottom: 20px;">
                <h2 style="color: #1e293b; margin: 0; font-size: 20px;">Atualização no Chamado #{short_id}</h2>
                <span style="color: #64748b; font-size: 14px;">Plataforma de Gestão de TI</span>
            </div>

            <p style="font-size: 15px; color: #334155;">
                O colaborador <strong>{author_name}</strong> registrou um(a) <strong>{action_type}</strong> no chamado:
            </p>

            <div style="background-color: #f8fafc; border-left: 4px solid #3b82f6; padding: 14px; margin: 16px 0; border-radius: 4px;">
                <strong style="color: #0f172a; display: block; margin-bottom: 6px;">{ticket.title}</strong>
                <p style="margin: 0; color: #475569; font-size: 14px; line-height: 1.5; white-space: pre-wrap;">{interaction.message}</p>
            </div>

            <p style="font-size: 12px; color: #94a3b8; margin: 16px 0;">
                Prioridade: <strong>{ticket.priority}</strong> &nbsp;|&nbsp; Status: <strong>{ticket.status}</strong> &nbsp;|&nbsp; Data: {datetime.now(timezone.utc).strftime("%d/%m/%Y às %H:%M")}
            </p>

            <div style="margin: 24px 0 16px 0;">
                <a href="{ticket_url}" style="background-color: #2563eb; color: #ffffff; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 14px; display: inline-block;">
                    Acessar Chamado
                </a>
            </div>

            <hr style="border: 0; border-top: 1px solid #f1f5f9; margin: 24px 0 16px 0;">
            <p style="font-size: 12px; color: #94a3b8; margin: 0;">
                Este é um e-mail automático gerado pelo sistema. Não responda diretamente a este remetente.
            </p>
        </div>
        """

        text_body = f"""Chamado #{short_id}: {ticket.title}
Autor: {author_name}
Mensagem:
{interaction.message}

Acesse o chamado em: {ticket_url}
"""

        for recipient in recipient_emails:
            await self.send_email(
                to_email=recipient,
                subject=subject,
                html_body=html_body,
                text_body=text_body
            )
