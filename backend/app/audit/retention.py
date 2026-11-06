"""
Retenção da trilha de auditoria por categoria (Plano de Evolução, Fase 0 PRs 9 e 11; S4; ADR-023).

- segurança: ``AUDIT_RETENTION_SECURITY_DAYS`` (padrão e mínimo: 1825 dias = 5 anos; só pode aumentar);
- operacional: ``AUDIT_RETENTION_OPERATIONAL_DAYS`` (padrão 730 dias = 2 anos).

Antes de apagar, os registros vencidos são exportados para ``<BACKUP_STORAGE_PATH>/audit-archive/`` em JSON Lines
compactado (com o selo da cadeia), com um arquivo ``.sha256`` ao lado. Só depois a linha sai do banco.

No PostgreSQL é o **único** caminho que apaga auditoria: a aplicação não tem DELETE em ``audit_logs``; quem apaga é
a função ``audit_purge`` (do dono), que só aceita o começo selado da cadeia da categoria, só registros vencidos e
nunca prazo abaixo do mínimo. O "agora" é o do banco.
"""

import gzip
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, literal_column, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.categories import OPERATIONAL, SECURITY
from app.audit.chain import is_postgres, seal_pending
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
        "chain_pos": log.chain_pos,
        "prev_hash": log.prev_hash,
        "row_hash": log.row_hash,
    }


def _archive(logs: list[AuditLog], category: str, archive_dir: Path) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    target = archive_dir / f"audit-{category}-{stamp}.jsonl.gz"
    payload = "".join(json.dumps(_row(log), ensure_ascii=False, default=str) + "\n" for log in logs).encode()
    with gzip.open(target, "wb") as fh:
        fh.write(payload)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_name(target.name + ".sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    logger.info("Auditoria %s: %d registros arquivados em %s", category, len(logs), target.name)


async def _expired_prefix(session: AsyncSession, category: str, days: int) -> list[AuditLog]:
    """Começo selado da cadeia em que TODOS os registros venceram (para no primeiro que ainda vale)."""
    cutoff = literal_column(f"now() - make_interval(days => {int(days)})")
    boundary = (
        await session.execute(
            select(func.min(AuditLog.chain_pos)).where(
                AuditLog.category == category, AuditLog.chain_pos.is_not(None), AuditLog.created_at >= cutoff
            )
        )
    ).scalar()
    query = select(AuditLog).where(
        AuditLog.category == category, AuditLog.chain_pos.is_not(None), AuditLog.created_at < cutoff
    )
    if boundary is not None:
        query = query.where(AuditLog.chain_pos < boundary)
    return list((await session.execute(query.order_by(AuditLog.chain_pos).limit(BATCH))).scalars())


async def _purge_postgres(session: AsyncSession, category: str, days: int, archive_dir: Path) -> int:
    total = 0
    while True:
        logs = await _expired_prefix(session, category, days)
        if not logs:
            return total
        _archive(logs, category, archive_dir)
        total += (
            await session.execute(
                text("SELECT audit_purge(:category, :days, :max_pos)"),
                {"category": category, "days": days, "max_pos": logs[-1].chain_pos},
            )
        ).scalar_one()
        await session.commit()
        session.expunge_all()


async def _purge_without_chain(session: AsyncSession, category: str, days: int, archive_dir: Path) -> int:
    """SQLite (testes rápidos): sem cadeia nem gatilho."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
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
        _archive(logs, category, archive_dir)
        await session.execute(delete(AuditLog).where(AuditLog.id.in_([log.id for log in logs])))
        await session.commit()
        total += len(logs)


async def apply_audit_retention(session: AsyncSession) -> dict[str, int]:
    settings = get_settings()
    archive_dir = settings.backup_storage_dir / "audit-archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    days = {SECURITY: settings.AUDIT_RETENTION_SECURITY_DAYS, OPERATIONAL: settings.AUDIT_RETENTION_OPERATIONAL_DAYS}
    if is_postgres(session):
        await seal_pending(session)  # só o que está selado pode sair
        return {category: await _purge_postgres(session, category, d, archive_dir) for category, d in days.items()}
    return {category: await _purge_without_chain(session, category, d, archive_dir) for category, d in days.items()}
