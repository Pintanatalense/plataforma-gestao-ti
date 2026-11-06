"""
Comandos administrativos que exigem acesso ao servidor (Plano de Evolução A2: recuperação de permissões críticas).

Uso (no servidor, dentro do contêiner do backend):
    docker compose exec backend python -m app.cli grant-critical --email admin@empresa.com.br --reason "chamado 123"
    docker compose exec backend python -m app.cli list-critical

``grant-critical`` concede TODAS as permissões críticas à conta indicada (ativa). Fica na auditoria com origem
"cli" e avisa todos os administradores. Não há caminho equivalente pela interface: quem não tem acesso ao servidor
não consegue conceder críticas a si mesmo.
"""

import argparse
import asyncio
import sys

from sqlalchemy import func, select

import app.models_registry  # noqa: F401  (registra todos os modelos antes das consultas)
from app.database import AsyncSessionLocal
from app.identity.critical import CriticalGrantService
from app.identity.models import UserAccount
from app.identity.permission_catalog import sync_permission_catalog


async def grant_critical(email: str, reason: str) -> int:
    async with AsyncSessionLocal() as session:
        await sync_permission_catalog(session)
        user = (
            await session.execute(
                select(UserAccount).where(func.lower(UserAccount.email) == email.strip().lower(), UserAccount.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            print(f"Conta ativa não encontrada: {email}", file=sys.stderr)
            return 1
        granted = await CriticalGrantService(session).grant_all(user.id, via="cli", reason=reason)
        await session.commit()
        print(f"{granted} permissão(ões) crítica(s) concedida(s) a {user.email}. Entre de novo para valerem no token.")
        return 0


async def list_critical() -> int:
    async with AsyncSessionLocal() as session:
        users = (await session.execute(select(UserAccount).where(UserAccount.deleted_at.is_(None)))).scalars().all()
        for user in sorted(users, key=lambda u: u.email):
            if user.critical_permissions:
                state = "ativo" if user.is_active else "inativo"
                print(f"{user.email} ({state}): {', '.join(user.critical_permissions)}")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Comandos administrativos do servidor.")
    sub = parser.add_subparsers(dest="command", required=True)
    grant = sub.add_parser("grant-critical", help="Concede todas as permissões críticas a uma conta ativa.")
    grant.add_argument("--email", required=True)
    grant.add_argument("--reason", required=True, help="Motivo (vai para a auditoria).")
    sub.add_parser("list-critical", help="Lista quem tem permissões críticas.")
    args = parser.parse_args(argv)

    if args.command == "grant-critical":
        return asyncio.run(grant_critical(args.email, args.reason))
    return asyncio.run(list_critical())


if __name__ == "__main__":
    sys.exit(main())
