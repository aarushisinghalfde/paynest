"""Tenant-scoped HMAC tokens for the sender's email and phone.

The same sender in the same tenant always gets the same token, so tickets can be grouped
by sender ("other tickets from this person") without storing the address. A different
tenant gets a different token for the same address, so tokens cannot be joined across
tenants. Without PII_HMAC_KEY (an SSM SecureString in AWS) a token cannot be reversed or
recomputed by guessing addresses.
"""

import hashlib
import hmac
import re

from pii.normalize import normalize_digits

PREFIX = {"email": "em_", "phone": "ph_"}


def normalize(kind: str, value: str) -> str:
    if kind == "email":
        return value.strip().lower()
    if kind == "phone":
        digits = re.sub(r"\D", "", normalize_digits(value))
        return digits[2:] if digits.startswith("00") else digits  # 00971... == +971...
    raise ValueError(f"unknown kind {kind}")


def sender_token(key: bytes, tenant_id: str, kind: str, value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    if not key:
        raise ValueError("PII_HMAC_KEY is empty")
    msg = "\x1f".join([tenant_id, kind, normalize(kind, value)]).encode("utf-8")
    return PREFIX[kind] + hmac.new(key, msg, hashlib.sha256).hexdigest()[:32]
