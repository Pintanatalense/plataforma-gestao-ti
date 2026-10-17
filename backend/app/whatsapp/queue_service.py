"""
MOD-15 — WhatsApp Integration (Queue & Anti-Ban Service)

Fila de mensagens persistente (Outbox) com proteção anti-ban:
- Escalonamento com Jitter aleatório e delays humanizados
- Controle de concorrência (evita disparos simultâneos)
- Cooldown por contato individual (evita sobrecarga do mesmo número)
- Emulação de presença de digitação (sendPresence "composing")
- Limitador de mensagens por minuto/hora
- Kill Switch / Pausa de emergência imediata
"""

import asyncio
from datetime import datetime, timezone, timedelta
import logging
import random
import uuid
from typing import Sequence
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.whatsapp.models import WhatsAppConfig, WhatsAppOutbox
from app.whatsapp.adapter import get_whatsapp_adapter

logger = logging.getLogger(__name__)


class WhatsAppQueueService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_config(self) -> WhatsAppConfig:
        stmt = select(WhatsAppConfig).limit(1)
        config = (await self.session.execute(stmt)).scalar_one_or_none()
        if not config:
            config = WhatsAppConfig(provider="NONE", is_enabled=False)
            self.session.add(config)
            await self.session.flush()
        return config

    async def enqueue_message(
        self,
        to_phone: str,
        message: str,
        priority: int = 2,
        ticket_id: uuid.UUID | None = None,
        template_id: uuid.UUID | None = None,
        scheduled_for: datetime | None = None,
        metadata: dict | None = None
    ) -> WhatsAppOutbox:
        """Adiciona uma mensagem à fila protegida de saída."""
        clean_phone = "".join(ch for ch in to_phone if ch.isdigit())
        outbox_item = WhatsAppOutbox(
            to_phone=clean_phone,
            message=message.strip(),
            priority=priority,
            ticket_id=ticket_id,
            template_id=template_id,
            scheduled_for=scheduled_for or datetime.now(timezone.utc),
            status="PENDING",
            metadata_json=metadata or {}
        )
        self.session.add(outbox_item)
        await self.session.flush()
        logger.info("[WhatsAppQueue] Mensagem enfileirada #%s para %s (Prioridade: %d)", outbox_item.id, clean_phone, priority)
        return outbox_item

    async def get_stats(self) -> dict:
        """Retorna métricas em tempo real sobre a fila e proteção anti-ban."""
        config = await self.get_config()
        now_utc = datetime.now(timezone.utc)
        start_of_today = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)

        # Contadores
        pending_count = (await self.session.execute(
            select(func.count(WhatsAppOutbox.id)).where(WhatsAppOutbox.status == "PENDING")
        )).scalar_one()

        sent_today_count = (await self.session.execute(
            select(func.count(WhatsAppOutbox.id)).where(
                and_(WhatsAppOutbox.status == "SENT", WhatsAppOutbox.sent_at >= start_of_today)
            )
        )).scalar_one()

        failed_count = (await self.session.execute(
            select(func.count(WhatsAppOutbox.id)).where(WhatsAppOutbox.status == "FAILED")
        )).scalar_one()

        # Mensagens no último minuto
        one_min_ago = now_utc - timedelta(minutes=1)
        sent_last_min = (await self.session.execute(
            select(func.count(WhatsAppOutbox.id)).where(
                and_(WhatsAppOutbox.status == "SENT", WhatsAppOutbox.sent_at >= one_min_ago)
            )
        )).scalar_one()

        return {
            "pending_count": pending_count,
            "sent_today_count": sent_today_count,
            "failed_count": failed_count,
            "sent_last_minute": sent_last_min,
            "anti_ban_enabled": config.anti_ban_enabled,
            "emergency_pause": config.emergency_pause,
            "min_delay_seconds": config.min_delay_seconds,
            "max_delay_seconds": config.max_delay_seconds,
            "simulate_typing": config.simulate_typing,
            "max_messages_per_minute": config.max_messages_per_minute,
            "cooldown_per_recipient_seconds": config.cooldown_per_recipient_seconds,
        }

    async def process_outbox(
        self,
        max_batch: int = 10,
        skip_sleep: bool = False
    ) -> dict:
        """
        Processa lote da fila de saída aplicando todas as regras de segurança anti-ban.
        Garante intervalo, digitação simulada e cooldown por contato.
        """
        config = await self.get_config()

        if not config.is_enabled:
            return {"processed": 0, "status": "disabled", "message": "Integração do WhatsApp está desativada."}

        if config.emergency_pause:
            return {"processed": 0, "status": "paused", "message": "Kill Switch / Pausa de emergência ativa. Disparos bloqueados."}

        now_utc = datetime.now(timezone.utc)

        # Validação do limite de mensagens por minuto (Anti-burst)
        if config.anti_ban_enabled:
            one_min_ago = now_utc - timedelta(minutes=1)
            sent_last_min = (await self.session.execute(
                select(func.count(WhatsAppOutbox.id)).where(
                    and_(WhatsAppOutbox.status == "SENT", WhatsAppOutbox.sent_at >= one_min_ago)
                )
            )).scalar_one()

            if sent_last_min >= config.max_messages_per_minute:
                return {
                    "processed": 0,
                    "status": "rate_limited",
                    "message": f"Limite de {config.max_messages_per_minute} msgs/min atingido. Aguardando resfriamento."
                }

        # Busca itens pendentes para processar
        stmt = (
            select(WhatsAppOutbox)
            .where(
                and_(
                    WhatsAppOutbox.status == "PENDING",
                    (WhatsAppOutbox.scheduled_for.is_(None) | (WhatsAppOutbox.scheduled_for <= now_utc))
                )
            )
            .order_by(WhatsAppOutbox.priority.asc(), WhatsAppOutbox.scheduled_for.asc(), WhatsAppOutbox.created_at.asc())
            .limit(max_batch)
        )
        items: Sequence[WhatsAppOutbox] = (await self.session.execute(stmt)).scalars().all()

        if not items:
            return {"processed": 0, "status": "idle", "message": "Nenhuma mensagem pendente na fila."}

        adapter = get_whatsapp_adapter(config)
        processed_count = 0
        failed_count = 0

        for item in items:
            # Revalida kill switch antes de cada disparo individual
            await self.session.refresh(config)
            if config.emergency_pause:
                logger.warning("[WhatsAppQueue] Pausa de emergência acionada durante execução do lote.")
                break

            # 1. Cooldown por contato (evita disparos consecutivos rápidos para o mesmo destinatário)
            if config.anti_ban_enabled and config.cooldown_per_recipient_seconds > 0:
                stmt_last_sent = select(func.max(WhatsAppOutbox.sent_at)).where(
                    and_(WhatsAppOutbox.to_phone == item.to_phone, WhatsAppOutbox.status == "SENT")
                )
                last_sent_recipient = (await self.session.execute(stmt_last_sent)).scalar_one_or_none()
                if last_sent_recipient:
                    elapsed = (datetime.now(timezone.utc) - last_sent_recipient).total_seconds()
                    if elapsed < config.cooldown_per_recipient_seconds:
                        # Adia o agendamento desta mensagem para permitir que outras pessoas recebam antes
                        rem = config.cooldown_per_recipient_seconds - elapsed
                        item.scheduled_for = datetime.now(timezone.utc) + timedelta(seconds=rem + 1)
                        await self.session.flush()
                        logger.info("[WhatsAppQueue] Cooldown ativo para %s. Reagendado para daqui a %.1fs", item.to_phone, rem)
                        continue

            # 2. Simulação de digitação ("composing...")
            if config.simulate_typing:
                typing_ms = config.typing_duration_seconds * 1000
                await adapter.send_presence(item.to_phone, presence="composing", delay_ms=typing_ms)
                if not skip_sleep:
                    # Pequena pausa simulando tempo de digitação
                    await asyncio.sleep(min(config.typing_duration_seconds, 2))

            # 3. Jitter e Delay humanizado aleatório
            if config.anti_ban_enabled and not skip_sleep:
                min_d = max(1, config.min_delay_seconds)
                max_d = max(min_d, config.max_delay_seconds)
                delay = random.uniform(min_d, max_d)
                logger.info("[WhatsAppQueue] Anti-Ban Jitter aplicado: %.2fs antes do envio para %s", delay, item.to_phone)
                await asyncio.sleep(delay)

            # 4. Disparo seguro
            try:
                success = await adapter.send_message(item.to_phone, item.message)
                if success:
                    item.status = "SENT"
                    item.sent_at = datetime.now(timezone.utc)
                    item.last_error = (
                        "Provedor MOCK: mensagem simulada, nada foi enviado de fato."
                        if config.provider == "MOCK" else None
                    )
                    processed_count += 1
                else:
                    item.attempts += 1
                    item.last_error = "Provedor rejeitou ou falhou ao enviar."
                    if item.attempts >= item.max_attempts:
                        item.status = "FAILED"
                    else:
                        # Backoff progressivo
                        item.scheduled_for = datetime.now(timezone.utc) + timedelta(seconds=30 * item.attempts)
                    failed_count += 1
            except Exception as exc:
                logger.exception("[WhatsAppQueue] Erro ao enviar mensagem #%s: %s", item.id, exc)
                item.attempts += 1
                item.last_error = str(exc)
                if item.attempts >= item.max_attempts:
                    item.status = "FAILED"
                else:
                    item.scheduled_for = datetime.now(timezone.utc) + timedelta(seconds=30 * item.attempts)
                failed_count += 1

            await self.session.flush()

        await self.session.commit()
        return {
            "processed": processed_count,
            "failed": failed_count,
            "status": "success",
            "message": f"{processed_count} mensagens enviadas com sucesso ({failed_count} falhas)."
        }

    async def cancel_item(self, item_id: uuid.UUID) -> bool:
        stmt = select(WhatsAppOutbox).where(WhatsAppOutbox.id == item_id)
        item = (await self.session.execute(stmt)).scalar_one_or_none()
        if not item or item.status != "PENDING":
            return False
        item.status = "CANCELLED"
        await self.session.commit()
        return True

    async def retry_item(self, item_id: uuid.UUID) -> bool:
        stmt = select(WhatsAppOutbox).where(WhatsAppOutbox.id == item_id)
        item = (await self.session.execute(stmt)).scalar_one_or_none()
        if not item:
            return False
        item.status = "PENDING"
        item.attempts = 0
        item.last_error = None
        item.scheduled_for = datetime.now(timezone.utc)
        await self.session.commit()
        return True
