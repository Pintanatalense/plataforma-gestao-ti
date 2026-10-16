"""
Fixtures compartilhadas para todos os testes.

Fornece:
- Banco de dados de teste (SQLite async in-memory)
- Sessão de teste
- Client HTTP para testes de integração
- Factory de usuários para autenticação em testes
"""

import os
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests._guard import DEFAULT_TEST_DATABASE_URL, assert_safe_test_url

# --- Segurança: precisa rodar ANTES de qualquer import de ``app`` ---------------
# O engine da aplicação (app.database) e o listener de auditoria usam
# settings.DATABASE_URL. Fixamos aqui um banco descartável, para que nenhum teste
# alcance o banco de desenvolvimento (padrão: localhost:5432/gestao_ti).
TEST_PG_URL: str | None = os.environ.get("TEST_DATABASE_URL")
if TEST_PG_URL:
    assert_safe_test_url(TEST_PG_URL)
os.environ["DATABASE_URL"] = TEST_PG_URL or DEFAULT_TEST_DATABASE_URL
import tempfile  # noqa: E402

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="gti_test_")
os.environ.setdefault("ATTACHMENT_STORAGE_PATH", os.path.join(_TEST_DATA_DIR, "attachments"))
os.environ.setdefault("BACKUP_STORAGE_PATH", os.path.join(_TEST_DATA_DIR, "backups"))
os.environ.setdefault("SECRET_KEY", "pytest-only-secret-key-0123456789abcdef0123456789")

from app.core.security import create_access_token, hash_password  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Testes marcados ``pg``/``migrations`` exigem um PostgreSQL de teste."""
    if TEST_PG_URL:
        return
    skip = pytest.mark.skip(reason="requer TEST_DATABASE_URL (PostgreSQL descartável)")
    for item in items:
        if "pg" in item.keywords or "migrations" in item.keywords:
            item.add_marker(skip)

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
