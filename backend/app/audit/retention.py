"""
Retenção da trilha de auditoria por categoria (Plano de Evolução, Fase 0 PR 9; S4).

- segurança: ``AUDIT_RETENTION_SECURITY_DAYS`` (padrão e mínimo: 1825 dias = 5 anos; só pode aumentar);
- operacional: ``AUDIT_RETENTION_OPERATIONAL_DAYS`` (padrão 730 dias = 2 anos).

Antes de apagar, os registros vencidos são exportados para ``<BACKUP_STORAGE_PATH>/audit-archive/`` em JSON Lines
compactado, com um arquivo ``.sha256`` ao lado (confere a integridade da cópia). Só depois a linha sai do banco.
É o único caminho que apaga auditoria; o PR 11 (auditoria imutável) restringe o banco a ele.
"""

import gzip
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.categories import OPERATIONAL, SECURITY
from app.audit.models import AuditLog
from app.config import get_settings

logger = logging.getLogger(__name__)
BATCH = 5000


def _row(log: AuditLog) -> dict:
    return {
        "id": str(log.id),
        "created_at": log.created_at.isoformat() if log.created_at else None,
        "event_type": log.event_type,
        "category": log.category,
        "entity_type": log.entity_type,
        "entity_id": str(log.entity_id),
        "user_id": str(log.user_id) if log.user_id else None,
        "actor_kind": log.actor_kind,
        "actor_email": log.actor_email,
        "ip": log.ip,
        "request_id": log.request_id,
        "data": log.data,
    }


async def _archive_and_delete(session: AsyncSession, category: str, cutoff: datetime, archive_dir: Path) -> int:
    total = 0
    while True:
        logs = list(
            (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.category == category, AuditLog.created_at < cutoff)
                    .order_by(AuditLog.created_at, AuditLog.id)
                    .limit(BATCH)
                )
            ).scalars()
        )
        if not logs:
            return total
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        target = archive_dir / f"audit-{category}-{stamp}.jsonl.gz"
        payload = "".join(json.dumps(_row(log), ensure_ascii=False, default=str) + "\n" for log in logs).encode()
        with gzip.open(target, "wb") as fh:
            fh.write(payload)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        target.with_name(target.name + ".sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
        await session.execute(delete(AuditLog).where(AuditLog.id.in_([log.id for log in logs])))
        await session.commit()
        total += len(logs)
        logger.info("Auditoria %s: %d registros arquivados em %s", category, len(logs), target.name)


async def apply_audit_retention(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    archive_dir = settings.backup_storage_dir / "audit-archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    return {
        SECURITY: await _archive_and_delete(
            session, SECURITY, now - timedelta(days=settings.AUDIT_RETENTION_SECURITY_DAYS), archive_dir
        ),
        OPERATIONAL: await _archive_and_delete(
            session, OPERATIONAL, now - timedelta(days=settings.AUDIT_RETENTION_OPERATIONAL_DAYS), archive_dir
        ),
    }
