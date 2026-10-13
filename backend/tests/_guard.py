"""
Guarda de segurança dos testes.

Impede que qualquer teste (ou migration executada por teste) toque num banco que
não seja descartável. Regras: o nome do banco deve terminar em ``_test`` e o host
deve ser local. Este módulo NÃO importa nada de ``app`` de propósito: ele precisa
rodar antes de qualquer import que crie o engine da aplicação.
"""

from sqlalchemy.engine import make_url

ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}

# URL padrão do PostgreSQL descartável (docker-compose.test.yml).
DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:55432/gti_test"


class UnsafeTestDatabaseError(RuntimeError):
    """A URL informada não aponta para um banco descartável."""


def assert_safe_test_url(url: str) -> str:
    """Valida a URL e a devolve; levanta UnsafeTestDatabaseError se for insegura."""
    parsed = make_url(url)
    database = parsed.database or ""
    if not database.endswith("_test"):
        raise UnsafeTestDatabaseError(
            f"Banco '{database}' recusado: o nome deve terminar em '_test'."
        )
    if (parsed.host or "") not in ALLOWED_HOSTS:
        raise UnsafeTestDatabaseError(
            f"Host '{parsed.host}' recusado: use apenas {sorted(ALLOWED_HOSTS)}."
        )
    return url
