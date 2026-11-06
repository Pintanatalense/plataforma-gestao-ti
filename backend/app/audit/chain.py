"""
Selo e verificação da cadeia de hash da auditoria (ADR-023; Plano de Evolução, Fase 0 PR 11; S4).

O trabalho é feito pelas funções do banco (``app/audit/chain_ddl.py``); aqui só são chamadas. Fora do PostgreSQL
(SQLite dos testes rápidos) não há cadeia: as funções devolvem zero/vazio.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
SEAL_BATCH = 5000


def is_postgres(session: AsyncSession) -> bool:
    return session.get_bind().dialect.name == "postgresql"


@dataclass(frozen=True)
class ChainStatus:
    category: str
    checked: int
    last_pos: int
    last_hash: str
    problem: str | None


async def seal_pending(session: AsyncSession) -> int:
    """Sela tudo o que ainda não foi selado (lotes de 5000, um commit por lote)."""
    if not is_postgres(session):
        return 0
    total = 0
    while True:
        sealed = (await session.execute(text("SELECT audit_seal(:limit)"), {"limit": SEAL_BATCH})).scalar_one()
        await session.commit()
        total += sealed
        if sealed < SEAL_BATCH:
            return total


async def verify_chain(session: AsyncSession) -> list[ChainStatus]:
    if not is_postgres(session):
        return []
    rows = await session.execute(
        text(
            "SELECT v.chain_category, v.checked, v.chain_last_pos, s.last_hash, v.problem FROM audit_verify() v "
            "JOIN audit_chain_state s ON s.category = v.chain_category ORDER BY v.chain_category"
        )
    )
    return [ChainStatus(r.chain_category, r.checked, r.chain_last_pos, r.last_hash, r.problem) for r in rows]
