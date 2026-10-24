"""
Canal WhatsApp com dois provedores atrás do mesmo adapter (ADR-019): `evolution` (não oficial, sem custo, padrão
das instalações novas) e `meta` (Cloud API oficial; só instalações já configuradas dependem dele hoje).
O provedor vem de `config['provider']`; configurações antigas, sem o campo, são `meta`.

Provedor Evolution: ver `whatsapp_evolution.py` (texto livre sempre, sem janela de 24 h nem template).

Provedor Meta. Regra da plataforma: dentro de 24 h após a última mensagem DA PESSOA, a empresa pode enviar texto livre;
fora disso só vale mensagem de *template* aprovado. O adapter decide sozinho:

  janela aberta  -> texto livre
  janela fechada -> template configurado (1 variável com o texto), ou falha permanente explicando

Configuração em `channel_configs['whatsapp']`:
  config  = {phone_number_id, graph_version, template_name, template_language, display_phone, app_base_url}
  secrets = {access_token, app_secret, verify_token}
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

import httpx
from sqlalchemy import func, select

from app.notifications.channel_store import StoredChannel, load_channel
from app.notifications.channels import whatsapp_evolution as evolution
from app.notifications.channels.base import (
    AdapterContext,
    Capabilities,
    ChannelHealth,
    DeliveryResult,
    Message,
    Recipient,
)
from app.notifications.models import ConversationSession, Delivery

for _noisy in ("httpx", "httpcore"):  # a URL da Graph API pode carregar ids da conta
    logging.getLogger(_noisy).setLevel(logging.WARNING)

WHATSAPP_CHANNEL = "whatsapp"
PROVIDER_EVOLUTION = "evolution"
PROVIDER_META = "meta"
GRAPH_BASE = "https://graph.facebook.com"
DEFAULT_GRAPH_VERSION = "v21.0"
CUSTOMER_WINDOW = timedelta(hours=24)
MAX_TEXT = 4000  # limite da API: 4096

# Códigos de erro da Cloud API que mudam a política de retentativa.
TOKEN_ERRORS = {190, 102, 10}  # token expirado/inválido/sem permissão: corrigir a configuração resolve
THROTTLE_ERRORS = {4, 80007, 130429, 131048, 131056}  # limites de taxa: tentar de novo mais tarde
WINDOW_CLOSED = 131047  # fora da janela de 24 h: exige template


def http_client(timeout: float = 15.0) -> httpx.AsyncClient:
    """Ponto único de criação do cliente (os testes o substituem por um transporte falso)."""
    return httpx.AsyncClient(timeout=timeout)


async def graph_call(
    token: str, method: str, path: str, payload: dict[str, Any] | None = None, params: dict[str, str] | None = None,
    version: str = DEFAULT_GRAPH_VERSION, timeout: float = 15.0,
) -> tuple[int, dict]:
    """Chama a Graph API. Devolve (status HTTP, corpo JSON). Erros de rede viram status 0."""
    try:
        async with http_client(timeout) as client:
            response = await client.request(
                method, f"{GRAPH_BASE}/{version}/{path}", json=payload, params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        return 0, {"error": {"message": f"{type(exc).__name__}: {exc}"}}
    try:
        body = response.json()
    except ValueError:
        body = {"error": {"message": response.text[:200]}}
    return response.status_code, body


def error_info(body: dict) -> tuple[int | None, str]:
    error = body.get("error") or {}
    return error.get("code"), str(error.get("message") or "")


def classify(status: int, body: dict) -> DeliveryResult:
    """Traduz a resposta da Cloud API para a política de retentativa do hub."""
    if status == 200 and (body.get("messages") or [{}])[0].get("id"):
        return DeliveryResult("ok", provider_message_id=body["messages"][0]["id"])
    code, message = error_info(body)
    detail = f"{status or 'rede'}/{code} {message}".strip()
    if code in TOKEN_ERRORS or status == 401:
        return DeliveryResult("retryable", error=f"token da Meta inválido ou expirado: {detail}")
    if code in THROTTLE_ERRORS or status == 429:
        return DeliveryResult("retryable", error=detail, retry_after_seconds=60)
    if status == 0 or status >= 500:
        return DeliveryResult("retryable", error=detail)
    # 400/403/404 com outros códigos: número sem WhatsApp, fora da lista de teste, parâmetro inválido...
    return DeliveryResult("permanent", error=detail)


def template_text(text: str) -> str:
    """Parâmetros de template não aceitam quebra de linha, tabulação nem 4+ espaços seguidos."""
    flat = re.sub(r"\s*[\r\n\t]+\s*", " | ", text.strip())
    flat = re.sub(r" {2,}", " ", flat)
    return flat[:1000]


def render_text(message: Message, base_url: str | None) -> str:
    parts = [message.title, message.body_text]
    if message.link and base_url:
        parts.append(f"Abrir no sistema: {base_url.rstrip('/')}{message.link}")
    text = "\n\n".join(p for p in parts if p)
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def provider_of(stored: StoredChannel | None) -> str:
    """Configurações antigas (sem o campo) são da Meta, que era o único provedor."""
    provider = (stored.config.get("provider") if stored else None) or PROVIDER_META
    return provider if provider in (PROVIDER_EVOLUTION, PROVIDER_META) else PROVIDER_META


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class WhatsAppAdapter:
    channel: ClassVar[str] = WHATSAPP_CHANNEL
    capabilities: ClassVar[Capabilities] = Capabilities(inbound=True, max_len=MAX_TEXT, rate_per_second=10.0)

    def __init__(self, ctx: AdapterContext) -> None:
        self._session_factory = ctx.session_factory
        self._pacer = evolution.Pacer()  # um adapter por worker: o ritmo vale para o canal inteiro

    async def _load(self, phone: str):
        async with self._session_factory() as session:
            stored = await load_channel(session, WHATSAPP_CHANNEL)
            last = (
                await session.execute(
                    select(ConversationSession.last_interaction_at).where(
                        ConversationSession.channel == WHATSAPP_CHANNEL, ConversationSession.external_id == phone
                    )
                )
            ).scalar_one_or_none()
        return stored, last

    async def send(self, recipient: Recipient, message: Message) -> DeliveryResult:
        stored, last_inbound = await self._load(recipient.address)
        if stored is not None and provider_of(stored) == PROVIDER_EVOLUTION:
            return await self._send_evolution(stored, recipient, message)
        if stored is None or not stored.enabled or not stored.secrets.get("access_token"):
            return DeliveryResult("permanent", error="Canal WhatsApp desabilitado ou sem token.")
        cfg = stored.config
        phone_id, version = cfg.get("phone_number_id"), cfg.get("graph_version") or DEFAULT_GRAPH_VERSION
        if not phone_id:
            return DeliveryResult("permanent", error="Canal WhatsApp sem Phone Number ID.")
        token = stored.secrets["access_token"]
        text = render_text(message, cfg.get("app_base_url"))
        template = cfg.get("template_name")

        window_open = last_inbound is not None and datetime.now(timezone.utc) - _aware(last_inbound) < CUSTOMER_WINDOW
        if window_open:
            status, body = await self._post(token, version, phone_id, recipient.address, self._text_payload(recipient.address, text))
            code, _ = error_info(body)
            if code == WINDOW_CLOSED and template:  # a janela fechou no meio do caminho
                status, body = await self._post(
                    token, version, phone_id, recipient.address, self._template_payload(recipient.address, cfg, text)
                )
            return classify(status, body)

        if not template:
            return DeliveryResult(
                "permanent",
                error="Fora da janela de 24 h e nenhum template aprovado está configurado: "
                "peça à pessoa que envie uma mensagem ao bot ou configure o template.",
            )
        status, body = await self._post(token, version, phone_id, recipient.address, self._template_payload(recipient.address, cfg, text))
        return classify(status, body)

    async def _sent_last_hour(self, address: str) -> int:
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(func.count()).select_from(Delivery).where(
                        Delivery.channel == WHATSAPP_CHANNEL, Delivery.address == address,
                        Delivery.status == "SENT", Delivery.sent_at >= since,
                    )
                )
            ).scalar_one()

    async def _send_evolution(self, stored: StoredChannel, recipient: Recipient, message: Message) -> DeliveryResult:
        if not stored.enabled:
            return DeliveryResult("permanent", error="Canal WhatsApp desabilitado.")
        if not evolution.is_configured():
            return DeliveryResult("retryable", error="Evolution sem EVOLUTION_API_KEY no servidor: corrija o .env e reinicie.")
        cfg = stored.config
        per_hour = cfg.get("max_per_hour", evolution.DEFAULT_MAX_PER_HOUR)
        if per_hour and await self._sent_last_hour(recipient.address) >= per_hour:
            return DeliveryResult(
                "retryable", deferred=True, retry_after_seconds=evolution.HOURLY_DEFER_SECONDS,
                error=f"Limite de {per_hour} mensagens por hora para este número (proteção contra banimento).",
            )
        instance = stored.config.get("instance_name") or evolution.DEFAULT_INSTANCE
        # Sem sessão, a Evolution não responde ao envio e a conexão fica pendurada por 15 s, parando o ciclo do worker
        # (homologação real, C5). Conferir o estado antes custa uma chamada local e devolve o motivo certo na hora.
        # Vem antes do ritmo: sem sessão não se gasta a vez de ninguém.
        offline = await evolution.offline_reason(instance)
        if offline:
            return DeliveryResult("retryable", error=offline)
        wait = self._pacer.reserve(cfg.get("send_interval_seconds", evolution.DEFAULT_INTERVAL_SECONDS))
        if wait > 0:
            return DeliveryResult("retryable", deferred=True, retry_after_seconds=max(int(wait) + 1, 1), error="Aguardando a vez (ritmo do canal).")
        text = evolution.render_text(message, stored.config.get("app_base_url"))
        return await evolution.send_text(instance, recipient.address, text)

    @staticmethod
    def _text_payload(to: str, text: str) -> dict:
        return {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text, "preview_url": False}}

    @staticmethod
    def _template_payload(to: str, cfg: dict, text: str) -> dict:
        return {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": cfg["template_name"],
                "language": {"code": cfg.get("template_language") or "pt_BR"},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": template_text(text)}]}],
            },
        }

    @staticmethod
    async def _post(token: str, version: str, phone_id: str, to: str, payload: dict) -> tuple[int, dict]:
        return await graph_call(token, "POST", f"{phone_id}/messages", payload=payload, version=version)

    async def health(self) -> ChannelHealth:
        async with self._session_factory() as session:
            stored = await load_channel(session, WHATSAPP_CHANNEL)
        if stored is None or not stored.enabled:
            return ChannelHealth(ok=False, detail="Desabilitado.")
        if provider_of(stored) == PROVIDER_EVOLUTION:
            state, detail = await evolution.connection_state(stored.config.get("instance_name") or evolution.DEFAULT_INSTANCE)
            if state == "open":
                return ChannelHealth(ok=True, detail=f"Evolution conectada {stored.config.get('display_phone') or ''}".strip())
            return ChannelHealth(ok=False, detail=detail or f"WhatsApp não está conectado (estado: {state}).")
        token, phone_id = stored.secrets.get("access_token"), stored.config.get("phone_number_id")
        if not token or not phone_id:
            return ChannelHealth(ok=False, detail="Token ou Phone Number ID não configurados.")
        status, body = await graph_call(
            token, "GET", phone_id, params={"fields": "display_phone_number,verified_name"},
            version=stored.config.get("graph_version") or DEFAULT_GRAPH_VERSION,
        )
        if status == 200:
            return ChannelHealth(ok=True, detail=f"{body.get('verified_name', '')} {body.get('display_phone_number', '')}".strip())
        _, message = error_info(body)
        return ChannelHealth(ok=False, detail=f"{status or 'rede'}: {message}")
