"""
Utilitários de segurança: hashing de senhas e JWT.

Senhas utilizam bcrypt conforme requisito de hash seguro.
JWT utiliza HS256 com chave configurável.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import get_settings

settings = get_settings()

# bcrypt só considera os primeiros 72 bytes da senha; a partir da versão 5.0
# a biblioteca lança erro em vez de truncar silenciosamente. Truncamos de forma
# explícita e consistente no hash e na verificação.
_BCRYPT_MAX_BYTES = 72


def _encode_password(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """
    Gera hash bcrypt de uma senha.

    Args:
        password: senha em texto puro

    Returns:
        Hash bcrypt da senha
    """
    return bcrypt.hashpw(_encode_password(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica se uma senha corresponde ao hash armazenado.

    Args:
        plain_password: senha fornecida pelo usuário
        hashed_password: hash armazenado no banco

    Returns:
        True se a senha corresponde
    """
    try:
        return bcrypt.checkpw(_encode_password(plain_password), hashed_password.encode("utf-8"))
    except ValueError:
        # Hash armazenado malformado
        return False


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """
    Gera um token JWT.

    Args:
        data: payload do token (deve conter "sub" com o ID do usuário)
        expires_delta: tempo de expiração customizado (padrão: configuração global)

    Returns:
        Token JWT codificado
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRATION_HOURS)

    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """
    Decodifica e valida um token JWT.

    Args:
        token: JWT codificado

    Returns:
        Payload decodificado ou None se inválido/expirado
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError:
        # base de todos os erros do PyJWT: expirado, assinatura inválida, algoritmo não permitido, claim mal
        # formado, token malformado e chave inválida
        return None
