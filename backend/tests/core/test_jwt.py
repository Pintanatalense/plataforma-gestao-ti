"""
JWT: criação e validação do token de acesso (PyJWT). Cobre o contrato que o resto do sistema assume.
"""

import base64
import hashlib
import hmac
import json
from datetime import timedelta

import pytest

from app.config import get_settings
from app.core.security import create_access_token, decode_access_token

SECRET = get_settings().SECRET_KEY


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _hs256(payload: dict, key: str = SECRET) -> str:
    """Token HS256 montado à mão: é o que qualquer biblioteca (inclusive a anterior) emite."""
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(key.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


def test_roundtrip_keeps_claims_and_adds_exp_and_iat():
    token = create_access_token({"sub": "u1", "permissions": ["a.b"], "tv": 3})
    payload = decode_access_token(token)
    assert payload["sub"] == "u1" and payload["permissions"] == ["a.b"] and payload["tv"] == 3
    assert payload["exp"] > payload["iat"]


def test_expired_token_is_rejected():
    token = create_access_token({"sub": "u1"}, expires_delta=timedelta(seconds=-5))
    assert decode_access_token(token) is None


def test_token_signed_with_another_key_is_rejected():
    assert decode_access_token(_hs256({"sub": "u1", "exp": 4102444800}, key="outra-chave-" + "x" * 30)) is None


def test_tampered_payload_is_rejected():
    head, _, sig = create_access_token({"sub": "u1"}).split(".")
    forged = _b64(json.dumps({"sub": "admin", "is_admin": True, "exp": 4102444800}).encode())
    assert decode_access_token(f"{head}.{forged}.{sig}") is None


def test_alg_none_token_is_rejected():
    head = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    body = _b64(json.dumps({"sub": "u1", "is_admin": True, "exp": 4102444800}).encode())
    assert decode_access_token(f"{head}.{body}.") is None


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "....", "Bearer x"])
def test_garbage_is_rejected(garbage):
    assert decode_access_token(garbage) is None


def test_token_emitted_by_another_hs256_library_is_still_valid():
    """Quem já está logado (token emitido antes da troca de biblioteca) continua logado."""
    token = _hs256({"sub": "u1", "permissions": [], "exp": 4102444800, "iat": 1700000000})
    assert decode_access_token(token)["sub"] == "u1"
