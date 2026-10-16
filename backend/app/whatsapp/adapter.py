"""
MOD-15 — WhatsApp Integration (Adapters)

Implementação do padrão Adapter para provedores de mensageria:
- WhatsAppProviderAdapter (Interface Base)
- MockWhatsAppAdapter (Ambiente de desenvolvimento e testes)
- EvolutionApiAdapter (Provedor Open-Source / Auto-hospedado)
- MetaCloudApiAdapter (Provedor Oficial Meta Business)
"""

from abc import ABC, abstractmethod
import logging
import httpx
from typing import Any

from app.whatsapp.models import WhatsAppConfig

logger = logging.getLogger(__name__)


class WhatsAppProviderAdapter(ABC):
    @abstractmethod
    async def send_message(self, to_phone: str, text: str) -> bool:
        """Envia mensagem de texto para o número especificado."""
        pass

    async def send_presence(self, to_phone: str, presence: str = "composing", delay_ms: int = 2000) -> bool:
        """Envia sinal de presença (ex: 'composing' para 'digitando...') para humanizar a interação."""
        return True

    async def send_menu(self, to_phone: str, title: str, options: list[str]) -> bool:
        """Envia menu de opções numeradas."""
        lines = [title, ""]
        for idx, opt in enumerate(options, 1):
            lines.append(f"[{idx}] {opt}")
    async def check_connection_state(self) -> dict[str, Any]:
        """Verifica o estado da conexão com o WhatsApp/Provedor."""
        return {"state": "open", "message": "Provedor operacional"}

    async def get_qr_code(self) -> dict[str, Any]:
        """Obtém o QR Code ou código de pareamento para conectar o WhatsApp."""
        return {"qrcode": None, "pairingCode": None, "message": "Provedor não requer pareamento via QR Code"}


class MockWhatsAppAdapter(WhatsAppProviderAdapter):
    """Adapter de simulação em memória para desenvolvimento e suíte de testes."""
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, Any]] = []
        self.presence_events: list[dict[str, Any]] = []

    async def send_message(self, to_phone: str, text: str) -> bool:
        self.sent_messages.append({
            "to_phone": to_phone,
            "text": text
        })
        logger.info("[MockWhatsApp] Mensagem para %s: %s", to_phone, text)
        return True

    async def send_presence(self, to_phone: str, presence: str = "composing", delay_ms: int = 2000) -> bool:
        self.presence_events.append({
            "to_phone": to_phone,
            "presence": presence,
            "delay_ms": delay_ms
        })
        logger.info("[MockWhatsApp] Presença '%s' simulada para %s (%dms)", presence, to_phone, delay_ms)
        return True

    def clear(self) -> None:
        self.sent_messages.clear()
        self.presence_events.clear()


class EvolutionApiAdapter(WhatsAppProviderAdapter):
    """Adapter para Evolution API v1/v2 (Open-source, self-hosted via Docker)."""
    def __init__(self, api_url: str, api_key: str, instance_name: str) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.instance_name = instance_name

    async def send_message(self, to_phone: str, text: str) -> bool:
        clean_phone = "".join(ch for ch in to_phone if ch.isdigit())
        endpoint = f"{self.api_url}/message/sendText/{self.instance_name}"
        headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "number": clean_phone,
            "text": text
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
                if resp.status_code in (200, 201):
                    return True
                logger.error("[EvolutionAPI] Falha ao enviar mensagem (status %d): %s", resp.status_code, resp.text)
                return False
        except Exception as exc:
            logger.exception("[EvolutionAPI] Erro de rede ou comunicação: %s", exc)
            return False

    async def send_presence(self, to_phone: str, presence: str = "composing", delay_ms: int = 2000) -> bool:
        clean_phone = "".join(ch for ch in to_phone if ch.isdigit())
        endpoint = f"{self.api_url}/chat/sendPresence/{self.instance_name}"
        headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "number": clean_phone,
            "presence": presence,
            "delay": delay_ms
        }
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
                return resp.status_code in (200, 201)
        except Exception as exc:
            logger.debug("[EvolutionAPI] Erro ao enviar presença (ignorado): %s", exc)
            return False

    async def check_connection_state(self) -> dict[str, Any]:
        """Consulta o estado da instância na Evolution API (open, close, connecting)."""
        endpoint = f"{self.api_url}/instance/connectionState/{self.instance_name}"
        headers = {"apikey": self.api_key}
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(endpoint, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    # Formatos comuns da Evolution API: {"instance": {"state": "open"}} ou {"state": "open"}
                    state = "unknown"
                    if isinstance(data, dict):
                        if "instance" in data and isinstance(data["instance"], dict):
                            state = data["instance"].get("state", "unknown")
                        else:
                            state = data.get("state", "unknown")
                    return {"state": state, "data": data}
                elif resp.status_code == 404:
                    return {"state": "not_found", "message": f"Instância '{self.instance_name}' não encontrada na Evolution API"}
                return {"state": "error", "status_code": resp.status_code, "message": resp.text}
        except Exception as exc:
            logger.warning("[EvolutionAPI] Falha ao verificar estado de conexão: %s", exc)
            return {"state": "unreachable", "error": str(exc)}

    async def get_qr_code(self) -> dict[str, Any]:
        """Obtém QR Code ou status de pareamento da Evolution API."""
        endpoint = f"{self.api_url}/instance/connect/{self.instance_name}"
        headers = {"apikey": self.api_key}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(endpoint, headers=headers)
                if resp.status_code in (200, 201):
                    data = resp.json()
                    qrcode = data.get("base64") or data.get("qrcode", {}).get("base64")
                    code = data.get("code") or data.get("pairingCode")
                    return {"qrcode": qrcode, "pairingCode": code, "data": data}
                return {"qrcode": None, "error": f"Evolution API retornou status {resp.status_code}", "detail": resp.text}
        except Exception as exc:
            logger.warning("[EvolutionAPI] Falha ao buscar QR Code: %s", exc)
            return {"qrcode": None, "error": str(exc)}


class MetaCloudApiAdapter(WhatsAppProviderAdapter):
    """Adapter para WhatsApp Business Cloud API Oficial (Meta)."""
    def __init__(self, api_url: str, api_key: str, phone_number_id: str) -> None:
        self.api_url = api_url.rstrip("/") or "https://graph.facebook.com/v20.0"
        self.api_key = api_key
        self.phone_number_id = phone_number_id

    async def send_message(self, to_phone: str, text: str) -> bool:
        clean_phone = "".join(ch for ch in to_phone if ch.isdigit())
        endpoint = f"{self.api_url}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": clean_phone,
            "type": "text",
            "text": {"body": text}
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
                return resp.status_code in (200, 201)
        except Exception as exc:
            logger.exception("[MetaCloudAPI] Erro de envio: %s", exc)
            return False

    async def send_presence(self, to_phone: str, presence: str = "composing", delay_ms: int = 2000) -> bool:
        # Meta Cloud API não possui endpoint separado para presença em contas padrão
        return True



class DisabledWhatsAppAdapter(WhatsAppProviderAdapter):
    """Integração desativada/não configurada: nada é enviado e o envio é reportado como falha."""

    async def send_message(self, to_phone: str, text: str) -> bool:
        logger.warning("[WhatsApp] Envio ignorado: integração desativada ou provedor não configurado.")
        return False


# Singletons
default_mock_adapter = MockWhatsAppAdapter()
disabled_adapter = DisabledWhatsAppAdapter()


def get_whatsapp_adapter(config: WhatsAppConfig | None) -> WhatsAppProviderAdapter:
    """Factory de adapters conforme o provedor configurado no banco de dados."""
    if not config or not config.is_enabled:
        return disabled_adapter

    if config.provider == "MOCK":
        return default_mock_adapter

    if config.provider == "EVOLUTION_API":
        return EvolutionApiAdapter(
            api_url=config.api_url,
            api_key=config.api_key,
            instance_name=config.instance_name
        )
    elif config.provider == "META_CLOUD_API":
        return MetaCloudApiAdapter(
            api_url=config.api_url,
            api_key=config.api_key,
            phone_number_id=config.instance_name
        )

    return disabled_adapter
