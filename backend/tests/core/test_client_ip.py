"""IP do cliente (auditoria, limites, logs): o cliente não pode escolher o próprio IP (Plano de Evolução, S2)."""
import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.models import AuditLog
from app.core.dependencies import client_ip
from app.database import get_db
from app.main import app

NGINX_DIR = Path(__file__).resolve().parents[3] / "nginx"


def _request(peer: str | None, headers: dict[str, str] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": (peer, 1234) if peer else None,
    }
    return Request(scope)


@pytest.mark.parametrize(
    "peer,headers,expected",
    [
        # Vindo do Nginx (rede privada do Docker): vale o que ele escreveu
        ("172.18.0.5", {"X-Real-IP": "198.51.100.7", "X-Forwarded-For": "198.51.100.7"}, "198.51.100.7"),
        ("172.18.0.5", {"X-Forwarded-For": "198.51.100.8, 10.0.0.1"}, "198.51.100.8"),
        ("10.1.2.3", {"X-Real-IP": "2001:db8::1"}, "2001:db8::1"),
        # Do proxy sem cabeçalho válido: "unknown", nunca o IP do proxy (que juntaria todos num balde só)
        ("172.18.0.5", {"X-Real-IP": "<script>", "X-Forwarded-For": "não-é-ip"}, "unknown"),
        ("172.18.0.5", {}, "unknown"),
        # Conexão direta de fora (backend exposto por engano): os cabeçalhos são ignorados
        ("203.0.113.5", {"X-Real-IP": "1.2.3.4", "X-Forwarded-For": "1.2.3.4"}, "203.0.113.5"),
        ("2001:db8::99", {"X-Forwarded-For": "1.2.3.4"}, "2001:db8::99"),
    ],
)
def test_client_ip_only_trusts_headers_from_a_trusted_proxy(peer, headers, expected):
    assert client_ip(_request(peer, headers)) == expected


def test_client_ip_without_connection_info_is_unknown():
    assert client_ip(_request(None, {"X-Forwarded-For": "1.2.3.4"})) == "unknown"


async def test_a_forged_header_from_outside_does_not_reach_the_audit(db_session: AsyncSession):
    """Login falho vindo direto de um IP público com X-Forwarded-For forjado: a auditoria grava o IP real."""

    async def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    try:
        transport = ASGITransport(app=app, client=("203.0.113.5", 4321))
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.post(
                "/api/v1/identity/login",
                data={"username": "ninguem@test.com", "password": "x" * 10},
                headers={"X-Forwarded-For": "8.8.8.8", "X-Real-IP": "8.8.8.8"},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 401
    event = (await db_session.execute(select(AuditLog).where(AuditLog.event_type == "identity.login_failed"))).scalar_one()
    assert event.data["ip"] == "203.0.113.5"


def test_nginx_overwrites_the_client_ip_headers_in_every_proxied_block():
    """Todo bloco que repassa ao backend sobrescreve X-Real-IP e X-Forwarded-For com $remote_addr."""
    for conf in sorted(NGINX_DIR.glob("*.conf")) + sorted(NGINX_DIR.glob("*.template")):
        text = conf.read_text(encoding="utf-8")
        assert "$proxy_add_x_forwarded_for" not in text, f"{conf.name} repassa o X-Forwarded-For do cliente"
        for block in re.findall(r"location[^{]*\{[^}]*\}", text):
            if "proxy_pass" not in block:
                continue
            assert re.search(r"proxy_set_header\s+X-Forwarded-For\s+\$remote_addr;", block), (conf.name, block[:80])
            assert re.search(r"proxy_set_header\s+X-Real-IP\s+\$remote_addr;", block), (conf.name, block[:80])
