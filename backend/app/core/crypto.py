"""Cifra simétrica (Fernet) para segredos guardados no banco (senhas SMTP, tokens de canais)."""

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class SecretDecryptionError(RuntimeError):
    """O valor cifrado não pôde ser lido (chave diferente da usada na gravação)."""


def _fernet() -> Fernet:
    return Fernet(get_settings().APP_ENCRYPTION_KEY.encode())


def encrypt_json(data: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str) -> dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as exc:
        raise SecretDecryptionError(
            "Não foi possível decifrar o segredo: APP_ENCRYPTION_KEY difere da usada ao gravá-lo."
        ) from exc
