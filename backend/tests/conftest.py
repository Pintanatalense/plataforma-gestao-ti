"""
Fixtures compartilhadas para todos os testes.

Fornece:
- Banco de dados de teste (SQLite async in-memory)
- Sessão de teste
- Client HTTP para testes de integração
- Factory de usuários para autenticação em testes
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.database import Base, get_db
from app.main import app

# Engine de teste — SQLite async in-memory
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
)

TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session")
def event_loop():
    """Cria um event loop para toda a sessão de teste."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """Cria e destrói tabelas para cada teste."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Fornece uma sessão de banco de teste."""
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Fornece um client HTTP para testes de integração.

    Substitui a dependência do banco pela sessão de teste.
    """

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


def make_auth_headers(user_id: str | None = None, **extra_claims: Any) -> dict[str, str]:
    """
    Gera headers de autenticação para testes.

    Args:
        user_id: UUID do usuário (gera um aleatório se não fornecido)
        **extra_claims: claims adicionais no JWT

    Returns:
        Dict com header Authorization: Bearer <token>
    """
    uid = user_id or str(uuid4())
    token = create_access_token({"sub": uid, **extra_claims})
    return {"Authorization": f"Bearer {token}"}
