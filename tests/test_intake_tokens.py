"""Sender tokens: stable per tenant, different across tenants, never the raw value."""
import pytest

from intake.tokens import sender_token

KEY = b"k1"


def test_same_sender_same_token_despite_formatting():
    a = sender_token(KEY, "acme-in", "email", " Kavya.K@Outlook.com ")
    assert a == sender_token(KEY, "acme-in", "email", "kavya.k@outlook.com")
    assert sender_token(KEY, "acme-in", "phone", "+971 50 123 4567") == \
        sender_token(KEY, "acme-in", "phone", "00971501234567")
    assert sender_token(KEY, "acme-in", "phone", "+91 ९८७६५ ४३२१०") == \
        sender_token(KEY, "acme-in", "phone", "+919876543210")


def test_tenant_and_key_change_the_token():
    t = sender_token(KEY, "acme-in", "email", "a@b.com")
    assert t != sender_token(KEY, "other-in", "email", "a@b.com")
    assert t != sender_token(b"k2", "acme-in", "email", "a@b.com")
    assert t.startswith("em_") and "a@b.com" not in t and len(t) == 35


def test_missing_value_has_no_token_and_empty_key_fails():
    assert sender_token(KEY, "acme-in", "email", None) is None
    assert sender_token(KEY, "acme-in", "email", "  ") is None
    with pytest.raises(ValueError):
        sender_token(b"", "acme-in", "email", "a@b.com")
