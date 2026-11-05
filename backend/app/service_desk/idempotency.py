"""
Idempotência das rotas que criam chamados (ADR-026, PR 2b): ``POST /tickets`` e ``POST /tickets/{id}/children``.

A tela manda ``Idempotency-Key`` (um UUID por intenção de envio) e repete a mesma chave nas novas tentativas.

1. **Reserva antes de criar:** ``INSERT … ON CONFLICT (user_id, key) DO NOTHING RETURNING id``. Não gera erro de
   unicidade nem deixa a transação abortada. No PostgreSQL, se outra transação acabou de inserir a mesma chave, o
   INSERT espera ela terminar.
2. **Reserva vazia:** outra requisição tem a chave. A linha é lida com ``FOR SHARE``, que espera o commit ou o rollback
   da outra:
   - outra operação (rota ou principal diferentes): 422;
   - mesmo pedido: devolve os mesmos chamados (replay);
   - outro corpo: 422;
   - a outra desfez (a linha sumiu): tenta reservar mais uma vez.
3. **Reserva feita:** a rota cria os chamados e grava ``response_ids`` na mesma linha e na mesma transação. Um erro
   desfaz tudo, inclusive a chave.

Sem cabeçalho, nada muda.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationException
from app.service_desk.models import IdempotencyKey

RETENTION = timedelta(hours=48)
CREATE_TICKET = "POST /tickets"
ADD_CHILDREN = "POST /tickets/{id}/children"


@dataclass
class Claim:
    """``replay_ids`` preenchido: o pedido já foi atendido e a rota devolve esses chamados sem criar nada."""

    row_id: uuid.UUID | None = None
    replay_ids: list[uuid.UUID] | None = None


def parse_key(raw: str | None) -> str | None:
    if raw is None:
        return None
    try:
        return str(uuid.UUID(raw.strip()))
    except ValueError:
        raise ValidationException("Idempotency-Key deve ser um UUID.") from None


def request_hash(body: dict) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _insert(session: AsyncSession):
    if (await session.connection()).dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(IdempotencyKey)


async def _reserve(session: AsyncSession, values: dict) -> uuid.UUID | None:
    stmt = (
        (await _insert(session))
        .values(**values)
        .on_conflict_do_nothing(index_elements=["user_id", "key"])
        .returning(IdempotencyKey.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def claim(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    key: str,
    endpoint: str,
    target_id: uuid.UUID | None,
    body_hash: str,
) -> Claim:
    values = {
        "id": uuid.uuid4(), "user_id": user_id, "key": key, "endpoint": endpoint, "target_id": target_id,
        "request_hash": body_hash, "response_ids": [],
    }
    for _ in range(2):  # a segunda volta só acontece se a outra requisição desfez a reserva dela
        row_id = await _reserve(session, values)
        if row_id is not None:
            return Claim(row_id=row_id)
        existing = (
            await session.execute(
                select(IdempotencyKey)
                .where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if existing is None:
            continue
        if existing.endpoint != endpoint or existing.target_id != target_id:
            raise ValidationException("Chave de idempotência já usada em outra operação.")
        if existing.request_hash != body_hash:
            raise ValidationException("Chave de idempotência já usada com outro conteúdo.")
        return Claim(replay_ids=[uuid.UUID(str(i)) for i in existing.response_ids])
    raise ValidationException("Não foi possível reservar a chave de idempotência; tente de novo.")


async def record(session: AsyncSession, claimed: Claim, ids: list[uuid.UUID]) -> None:
    """Grava o resultado na linha reservada, na mesma transação da criação."""
    if claimed.row_id is None:
        return
    row = await session.get(IdempotencyKey, claimed.row_id)
    row.response_ids = [str(i) for i in ids]
    await session.flush()


async def purge_expired(session: AsyncSession, now: datetime | None = None) -> int:
    """Apaga as chaves com mais de 48 h (chamado pelo job ``retention.cleanup``, sem commit)."""
    cutoff = (now or datetime.now(timezone.utc)) - RETENTION
    result = await session.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < cutoff))
    return result.rowcount or 0
