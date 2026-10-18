"""Contrato: toda rota da API recusa chamadas sem token, exceto as públicas listadas aqui.

Percorre o OpenAPI (independe de detalhes internos do roteador) e chama cada operação sem
Authorization; qualquer resposta diferente de 401 fora da lista pública reprova o teste.
"""

import re
import uuid

import pytest
from httpx import AsyncClient

from app.main import app

pytestmark = pytest.mark.asyncio

PUBLIC = {
    ("get", "/api/v1/health"),
    ("get", "/api/v1/identity/setup/status"),
    ("post", "/api/v1/identity/setup"),  # só funciona com 0 usuários
    ("post", "/api/v1/identity/login"),
    ("get", "/api/v1/organization/company/public"),  # nome/logo para a tela de login
    # Webhook da Meta: GET = handshake com verify_token; POST = assinatura HMAC (X-Hub-Signature-256).
    # Ficam fora do OpenAPI (include_in_schema=False) e são exercitados em test_whatsapp_meta.py.
}
DOCS = {"/api/v1/docs", "/api/v1/redoc", "/api/v1/openapi.json", "/docs/oauth2-redirect"}


def _operations():
    for path, item in app.openapi()["paths"].items():
        for method in item:
            if method in {"get", "post", "put", "patch", "delete"} and path not in DOCS:
                yield method, path


async def test_every_operation_requires_authentication_unless_public(client: AsyncClient):
    exposed = []
    count = 0
    for method, path in _operations():
        count += 1
        url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
        response = await client.request(method.upper(), url)
        if response.status_code != 401 and (method, path) not in PUBLIC:
            exposed.append(f"{method.upper()} {path} -> {response.status_code}")
    assert count > 80, "OpenAPI deveria listar toda a API"
    assert not exposed, "Rotas acessíveis sem autenticação: " + "; ".join(sorted(exposed))


async def test_public_list_has_no_stale_entries():
    existing = set(_operations())
    assert PUBLIC <= existing
