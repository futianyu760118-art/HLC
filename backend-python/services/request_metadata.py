"""Pseudonymous request metadata derived at the Flask trust boundary."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
from typing import Any

from flask import current_app, request


def _secret() -> bytes:
    value = current_app.config.get('SECRET_KEY') or current_app.config.get('JWT_SECRET_KEY')
    return str(value or 'request-metadata-fallback').encode('utf-8')


def opaque_digest(value: Any, *, purpose: str, prefix: str, hex_length: int = 40) -> str:
    raw = str(value).encode('utf-8', errors='surrogatepass')
    digest = hmac.new(
        _secret(),
        purpose.encode('utf-8') + b'\0' + raw,
        hashlib.sha256,
    ).hexdigest()[:hex_length]
    return f'{prefix}{digest}'


def request_id_for_client(value: Any = None) -> str:
    """Return one bounded opaque ID; every non-empty client value is HMACed."""

    if value is not None and str(value).strip():
        return opaque_digest(value, purpose='client-request-id-v1', prefix='rid_')
    return f'rid_{secrets.token_hex(20)}'


def sanitize_request_id(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if len(text) == 44 and text.startswith('rid_') and all(char in '0123456789abcdef' for char in text[4:]):
        return text
    return request_id_for_client(text)


def validated_remote_address() -> str | None:
    """Read only ProxyFix/framework-resolved ``remote_addr`` and validate it."""

    value = request.remote_addr
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def remote_address_digest() -> str | None:
    value = validated_remote_address()
    if value is None:
        return None
    return opaque_digest(value, purpose='remote-address-v1', prefix='ip_')


def enterprise_source_fingerprint(user_agent: Any) -> str:
    remote = validated_remote_address() or 'unknown'
    agent = str(user_agent or '')[:512]
    return opaque_digest(
        f'{remote}\n{agent}',
        purpose='enterprise-source-fingerprint-v1',
        prefix='fp_',
        hex_length=60,
    )


def enterprise_idempotency_digest(raw_key: str, fingerprint_hash: str) -> str:
    return opaque_digest(
        f'{fingerprint_hash}\n{raw_key}',
        purpose='enterprise-idempotency-v1',
        prefix='idem_',
        hex_length=64,
    )
