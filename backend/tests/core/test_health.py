"""Testes do healthcheck e configurações base."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_healthcheck(client: AsyncClient) -> None:
    """Verifica que o endpoint de healthcheck retorna 200."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert "version" in data
    assert "timestamp" in data
    assert "components" in data


@pytest.mark.asyncio
async def test_healthcheck_contains_version(client: AsyncClient) -> None:
    """Verifica que o healthcheck retorna a versão da aplicação."""
    response = await client.get("/api/v1/health")
    data = response.json()
    assert data["version"] == "0.1.0"
