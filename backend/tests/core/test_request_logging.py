"""X-Request-ID: devolvido na resposta, aceito só em formato seguro e presente nas linhas de log."""

import logging

import pytest
from httpx import AsyncClient

from app.core.request_logging import LOG_FORMAT, RequestIdFilter, current_request_id

pytestmark = pytest.mark.asyncio

HEALTH = "/api/v1/health"


async def test_response_carries_a_generated_request_id(client: AsyncClient):
    resp = await client.get(HEALTH)
    rid = resp.headers["x-request-id"]
    assert len(rid) == 32 and rid.isalnum()


async def test_each_request_gets_its_own_id(client: AsyncClient):
    first = (await client.get(HEALTH)).headers["x-request-id"]
    second = (await client.get(HEALTH)).headers["x-request-id"]
    assert first != second


async def test_a_safe_client_id_is_kept(client: AsyncClient):
    resp = await client.get(HEALTH, headers={"X-Request-ID": "abc-12345678"})
    assert resp.headers["x-request-id"] == "abc-12345678"


@pytest.mark.parametrize("bad", ["curto", "tem espaco e <script>", "x" * 65, "a\tb-12345678"])
async def test_an_unsafe_client_id_is_replaced(client: AsyncClient, bad: str):
    resp = await client.get(HEALTH, headers={"X-Request-ID": bad})
    assert resp.headers["x-request-id"] != bad
    assert len(resp.headers["x-request-id"]) == 32


async def test_the_id_is_cleared_after_the_request(client: AsyncClient):
    await client.get(HEALTH, headers={"X-Request-ID": "abc-12345678"})
    assert current_request_id() == "-"


async def test_log_lines_show_the_request_id():
    record = logging.LogRecord("app.x", logging.INFO, __file__, 1, "mensagem", None, None)
    assert RequestIdFilter().filter(record) is True
    line = logging.Formatter(LOG_FORMAT).format(record)
    assert "[-]" in line and "mensagem" in line
