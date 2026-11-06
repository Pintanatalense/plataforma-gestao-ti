"""
Permissões críticas: concessão explícita e individual (Plano de Evolução S5/A2).

Regras:
- crítica nunca vem de perfil nem do ``is_admin``; só de uma linha em ``user_critical_grants``;
- pela API, só quem tem ``identity.critical.grant`` concede ou revoga, e nunca para si mesmo;
- não se revoga ``identity.critical.grant`` do último usuário ativo que a tem (a recuperação seria só pelo servidor);
- toda concessão e revogação vai para a auditoria e avisa todos os administradores (regra ``identity.critical_changed``);
- revogar encerra as sessões da pessoa (o token já emitido deixaria de refletir a revogação só no próximo login).
"""

import uuid
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.repository import AuditRepository
from app.core.exceptions import BusinessRuleException, ConflictException, ForbiddenException, NotFoundException
from app.identity.models import Permission, UserAccount, UserCriticalGrant
from app.identity.permission_catalog import BY_CODE, CRITICAL_CODES
from app.notifications.outbox import emit_event

GRANT_PERMISSION = "identity.critical.grant"
VIAS = ("setup", "migration", "cli", "api")


class CriticalGrantService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[UserCriticalGrant]:
        stmt = (
            select(UserCriticalGrant)
            .where(UserCriticalGrant.user_id == user_id)
            .order_by(UserCriticalGrant.granted_at)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def _permission(self, code: str) -> Permission:
        if code not in CRITICAL_CODES:
            raise BusinessRuleException(f"'{code}' não é uma permissão crítica.", rule="identity.critical.unknown")
        perm = (await self.session.execute(select(Permission).where(Permission.code == code))).scalar_one_or_none()
        if perm is None:
            raise NotFoundException("Permissão", code)
        return perm

    async def _target(self, user_id: uuid.UUID) -> UserAccount:
        user = await self.session.get(UserAccount, user_id)
        if user is None or user.deleted_at is not None:
            raise NotFoundException("Usuário", user_id)
        return user

    async def grant(
        self,
        user_id: uuid.UUID,
        code: str,
        *,
        via: str,
        actor_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> UserCriticalGrant | None:
        """Concede (idempotente: já concedida devolve ``None`` sem auditar de novo). O commit fica com quem chamou."""
        assert via in VIAS, via
        if via == "api" and actor_id == user_id:
            raise ForbiddenException("Ninguém concede permissão crítica a si mesmo.")
        perm = await self._permission(code)
        target = await self._target(user_id)
        if via == "api" and not target.is_active:
            raise BusinessRuleException("Usuário inativo não recebe permissão crítica.", rule="identity.critical.inactive")

        exists = await self.session.execute(
            select(UserCriticalGrant.id).where(
                UserCriticalGrant.user_id == user_id, UserCriticalGrant.permission_id == perm.id
            )
        )
        if exists.first() is not None:
            return None

        grant = UserCriticalGrant(
            user_id=user_id, permission_id=perm.id, granted_by_user_id=actor_id, granted_via=via, reason=reason
        )
        self.session.add(grant)
        await self.session.flush()
        await self._record("identity.critical_granted", target, code, via, actor_id, reason)
        return grant

    async def grant_all(self, user_id: uuid.UUID, *, via: str, actor_id: uuid.UUID | None = None, reason: str | None = None) -> int:
        """Concessão inicial (assistente de instalação) e recuperação pelo servidor: todas as críticas."""
        granted = 0
        for code in sorted(CRITICAL_CODES):
            if await self.grant(user_id, code, via=via, actor_id=actor_id, reason=reason):
                granted += 1
        return granted

    async def revoke(self, user_id: uuid.UUID, code: str, *, actor_id: uuid.UUID, reason: str | None = None) -> None:
        perm = await self._permission(code)
        target = await self._target(user_id)
        grant = (
            await self.session.execute(
                select(UserCriticalGrant).where(
                    UserCriticalGrant.user_id == user_id, UserCriticalGrant.permission_id == perm.id
                )
            )
        ).scalar_one_or_none()
        if grant is None:
            raise NotFoundException("Concessão", code)

        if code == GRANT_PERMISSION and await self._active_holders(perm.id, exclude_user_id=user_id) == 0:
            raise ConflictException(
                "Não é possível revogar a última concessão de 'Conceder permissões críticas'. "
                "Conceda a outra pessoa antes."
            )

        await self.session.delete(grant)
        target.token_version = (target.token_version or 0) + 1
        await self.session.flush()
        await self._record("identity.critical_revoked", target, code, "api", actor_id, reason)

    async def _active_holders(self, permission_id: uuid.UUID, exclude_user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(UserCriticalGrant)
            .join(UserAccount, UserAccount.id == UserCriticalGrant.user_id)
            .where(
                UserCriticalGrant.permission_id == permission_id,
                UserCriticalGrant.user_id != exclude_user_id,
                UserAccount.is_active.is_(True),
                UserAccount.deleted_at.is_(None),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def _record(
        self,
        event_type: str,
        target: UserAccount,
        code: str,
        via: str,
        actor_id: uuid.UUID | None,
        reason: str | None,
    ) -> None:
        data = {"permission": code, "via": via, "reason": reason}
        await AuditRepository(self.session).create(
            event_type=event_type, entity_type="user", entity_id=target.id, data=data, user_id=actor_id
        )
        await emit_event(
            self.session,
            event_type="identity.critical_changed",
            entity_type="user",
            entity_id=target.id,
            payload={
                "action": "granted" if event_type.endswith("granted") else "revoked",
                "permission": code,
                "permission_label": BY_CODE[code].label,
                "target_email": target.email,
                "via": via,
            },
            actor_user_id=actor_id,
            priority="high",
        )
