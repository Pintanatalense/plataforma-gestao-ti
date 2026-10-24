"""
Provedor Evolution API do canal WhatsApp (ADR-019). NÃO é oficial: o número fica pareado por sessão (QR code)
e pode cair ou ser banido; por isso a configuração é opt-in e o e-mail continua em paralelo nas regras.

Endereço e chave vêm do servidor (`EVOLUTION_BASE_URL`, `EVOLUTION_API_KEY`), não do cadastro do canal.
Rotas usadas (conferidas no código da v2.3.7; o formato exato dos erros ainda precisa de homologação, C5):

  POST   /instance/create                    {instanceName, integration, qrcode}
  GET    /instance/connect/{instance}        -> {pairingCode, code, base64, count} (ou o estado, se já conectada)
  GET    /instance/connectionState/{inst}    -> {instance: {instanceName, state: open|connecting|close}}
  GET    /instance/fetchInstances?instanceName=  -> [{ownerJid, profileName, ...}]
  DELETE /instance/logout/{instance}
  POST   /message/sendText/{instance}        {number, text, linkPreview}  -> 201 {key: {id}}

Autenticação: cabeçalho `apikey` com a chave global.

Configuração em `channel_configs['whatsapp']` com provider='evolution':
  config = {provider, instance_name, display_phone, app_base_url}
"""
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.notifications.channels.base import DeliveryResult, Message

for _noisy in ("httpx", "httpcore"):  # a URL carrega o nome da instância; o cabeçalho, a chave
    logging.getLogger(_noisy).setLevel(logging.WARNING)

DEFAULT_INSTANCE = "gestao-ti"
INSTANCE_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MAX_TEXT = 4000
CLOSED_HINTS = ("connection closed", "not connected", "instance is not", "does not exist", "not found", "timed out", "timeout")


def http_client(timeout: float = 15.0) -> httpx.AsyncClient:
    """Ponto único de criação do cliente (os testes o substituem por um transporte falso)."""
    return httpx.AsyncClient(timeout=timeout)


def is_configured() -> bool:
    return bool(get_settings().EVOLUTION_API_KEY and get_settings().EVOLUTION_BASE_URL)


async def evolution_call(
    method: str, path: str, payload: dict[str, Any] | None = None, params: dict[str, str] | None = None, timeout: float = 15.0
) -> tuple[int, Any]:
    """Chama a Evolution. Devolve (status HTTP, corpo JSON). Erros de rede viram status 0."""
    settings = get_settings()
    url = f"{settings.EVOLUTION_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    try:
        async with http_client(timeout) as client:
            response = await client.request(method, url, json=payload, params=params, headers={"apikey": settings.EVOLUTION_API_KEY})
    except httpx.HTTPError as exc:
        return 0, {"message": f"{type(exc).__name__}: {exc}"}
    try:
        body = response.json()
    except ValueError:
        body = {"message": response.text[:200]}
    return response.status_code, body


def error_text(body: Any) -> str:
    """Extrai uma mensagem legível de formatos variados de erro (mensagem, lista, objeto aninhado)."""
    if isinstance(body, dict):
        for key in ("message", "error", "response"):
            if body.get(key):
                return error_text(body[key])
        return ""
    if isinstance(body, list):
        return "; ".join(filter(None, (error_text(item) for item in body)))[:300]
    return str(body)[:300]


def instance_path(prefix: str, instance: str) -> str:
    return f"{prefix}/{quote(instance, safe='')}"


def _lacks_whatsapp(body: Any) -> bool:
    """A Evolution responde `exists: false` para número que não tem WhatsApp (em qualquer nível do corpo)."""
    if isinstance(body, dict):
        return body.get("exists") is False or any(_lacks_whatsapp(v) for v in body.values())
    if isinstance(body, list):
        return any(_lacks_whatsapp(v) for v in body)
    return False


def classify(status: int, body: Any) -> DeliveryResult:
    """Traduz a resposta da Evolution para a política de retentativa do hub."""
    if status in (200, 201) and isinstance(body, dict) and (body.get("key") or {}).get("id"):
        return DeliveryResult("ok", provider_message_id=str(body["key"]["id"]))
    detail = f"{status or 'rede'} {error_text(body)}".strip()
    lowered = detail.lower()
    if status == 0 or status >= 500:
        return DeliveryResult("retryable", error=detail)
    if status == 429:
        return DeliveryResult("retryable", error=detail, retry_after_seconds=60)
    if status in (401, 403):
        return DeliveryResult("retryable", error=f"chave da Evolution recusada (EVOLUTION_API_KEY): {detail}")
    if status == 404 or any(hint in lowered for hint in CLOSED_HINTS):
        # instância inexistente ou sessão caída: resolve ao reconectar, então vale tentar de novo depois
        return DeliveryResult("retryable", error=f"WhatsApp desconectado ou instância ausente: {detail}")
    if _lacks_whatsapp(body):
        detail = f"{detail} (número sem WhatsApp)".strip()
    # 400 com outro motivo: número sem WhatsApp, destinatário inválido...
    return DeliveryResult("permanent", error=detail)


def render_text(message: Message, base_url: str | None) -> str:
    """Texto do WhatsApp: título em negrito, corpo e link (sem janela de 24 h nem template neste provedor)."""
    parts = [f"*{message.title}*" if message.title else "", message.body_text]
    if message.link and base_url:
        parts.append(f"Abrir no sistema: {base_url.rstrip('/')}{message.link}")
    text = "\n\n".join(p for p in parts if p)
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


async def send_text(instance: str, number: str, text: str) -> DeliveryResult:
    status, body = await evolution_call(
        "POST", instance_path("message/sendText", instance), {"number": number, "text": text, "linkPreview": False}
    )
    return classify(status, body)


async def connection_state(instance: str) -> tuple[str, str]:
    """(estado, detalhe). Estado: open, connecting, close, missing (instância não criada), unconfigured ou error."""
    if not is_configured():
        return "unconfigured", "EVOLUTION_API_KEY não está definida no servidor."
    status, body = await evolution_call("GET", instance_path("instance/connectionState", instance))
    if status == 200 and isinstance(body, dict):
        return str((body.get("instance") or {}).get("state") or "close"), ""
    if status == 404:
        return "missing", ""
    return "error", f"{status or 'rede'} {error_text(body)}".strip()


async def ensure_instance(instance: str) -> tuple[bool, str]:
    """Cria a instância se não existir. Devolve (ok, erro)."""
    state, detail = await connection_state(instance)
    if state in ("unconfigured", "error"):
        return False, detail
    if state != "missing":
        return True, ""  # já existe (aberta, conectando ou fechada)
    status, body = await evolution_call(
        "POST", "instance/create", {"instanceName": instance, "integration": "WHATSAPP-BAILEYS", "qrcode": True}
    )
    if status in (200, 201):
        return True, ""
    return False, f"{status or 'rede'} {error_text(body)}".strip()


async def connect(instance: str) -> dict[str, Any]:
    """Prepara a conexão: devolve {state, qr_base64, pairing_code, count, detail}."""
    ok, error = await ensure_instance(instance)
    if not ok:
        return {"state": "error", "detail": error}
    status, body = await evolution_call("GET", instance_path("instance/connect", instance))
    if status != 200 or not isinstance(body, dict):
        return {"state": "error", "detail": f"{status or 'rede'} {error_text(body)}".strip()}
    if body.get("error"):
        return {"state": "error", "detail": error_text(body) or "A Evolution recusou o pedido de conexão."}
    if (body.get("instance") or {}).get("state") == "open":
        return {"state": "open", "detail": ""}
    return {
        "state": "connecting" if body.get("base64") or body.get("code") else "close",
        "qr_base64": body.get("base64"),
        "pairing_code": body.get("pairingCode"),
        "count": body.get("count"),
        "detail": "",
    }


async def logout(instance: str) -> tuple[bool, str]:
    status, body = await evolution_call("DELETE", instance_path("instance/logout", instance))
    if status in (200, 201):
        return True, ""
    if status == 400 and "not connected" in error_text(body).lower():
        return True, ""  # já estava desconectada
    return False, f"{status or 'rede'} {error_text(body)}".strip()


async def owner_phone(instance: str) -> str | None:
    """Telefone do número pareado (só dígitos), quando a Evolution informa."""
    status, body = await evolution_call("GET", "instance/fetchInstances", params={"instanceName": instance})
    if status != 200 or not isinstance(body, list) or not body:
        return None
    jid = str(body[0].get("ownerJid") or "")
    digits = re.sub(r"\D", "", jid.split("@")[0])
    return digits or None
