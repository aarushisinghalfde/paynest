"""vault-reveal Lambda: reveals one value for the right ticket only, audits every call."""
import json

import pytest

from lambdas.vault_reveal import handler as h

TID = "11111111-2222-4333-8444-555555555555"


class FakeDdb:
    def __init__(self, items):
        self.items = items

    def get_item(self, TableName, ConsistentRead, Key):  # noqa: N803 - boto3 names
        return {"Item": self.items[(Key["ticket_id"]["S"], Key["token"]["S"])]} \
            if (Key["ticket_id"]["S"], Key["token"]["S"]) in self.items else {}


class FakeKms:
    """Decrypts only with the exact context used to encrypt, like KMS."""

    def decrypt(self, KeyId, CiphertextBlob, EncryptionContext):  # noqa: N803
        ctx, value = json.loads(CiphertextBlob)
        if ctx != EncryptionContext:
            raise type("InvalidCiphertextException", (Exception,), {})()
        return {"Plaintext": value.encode()}


def item(ticket_id, token, value, expires=2**40, tenant="acme-in"):
    ctx = {"ticket_id": ticket_id, "token": token, "tenant_id": tenant}
    return {"tenant_id": {"S": tenant}, "ciphertext": {"B": json.dumps([ctx, value])},
            "expires_at": {"N": str(expires)}}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TABLE", "tbl")
    monkeypatch.setenv("KEY_ARN", "arn:key")


def call(event, items, capsys=None):
    return h.handler({"requested_by": "aarushi", "reason": "check_phase3 gate", **event}, None,
                     ddb=FakeDdb(items), kms=FakeKms())


def test_right_ticket_reveals_and_audit_has_no_value(capsys):
    out = call({"ticket_id": TID, "token": "<PAN_1>"}, {(TID, "<PAN_1>"): item(TID, "<PAN_1>", "ABCPK1234F")})
    assert out == {"status": "ok", "value": "ABCPK1234F"}
    log = capsys.readouterr().out
    assert '"result": "revealed"' in log and '"kind": "PAN"' in log and "ABCPK1234F" not in log


def test_unknown_ticket_or_token_is_not_found():
    items = {(TID, "<PAN_1>"): item(TID, "<PAN_1>", "X")}
    other = "99999999-2222-4333-8444-555555555555"
    assert call({"ticket_id": other, "token": "<PAN_1>"}, items)["status"] == "not_found"
    assert call({"ticket_id": TID, "token": "<IBAN_1>"}, items)["status"] == "not_found"


def test_ciphertext_copied_to_another_ticket_does_not_decrypt():
    """Even if an item were planted under another ticket, KMS context binding refuses it."""
    other = "99999999-2222-4333-8444-555555555555"
    items = {(other, "<PAN_1>"): item(TID, "<PAN_1>", "ABCPK1234F")}
    assert call({"ticket_id": other, "token": "<PAN_1>"}, items) == {"status": "denied"}


def test_expired_value_is_not_revealed_before_ttl_deletes_it():
    items = {(TID, "<PAN_1>"): item(TID, "<PAN_1>", "X", expires=1)}
    assert call({"ticket_id": TID, "token": "<PAN_1>"}, items)["status"] == "not_found"


@pytest.mark.parametrize("event", [
    {"ticket_id": "not-a-uuid", "token": "<PAN_1>"},
    {"ticket_id": TID, "token": "PAN_1"},
    {"ticket_id": TID, "token": "<PAN_1>", "reason": ""},
    {"ticket_id": TID, "token": "<PAN_1>", "requested_by": ""},
])
def test_bad_requests_are_refused(event):
    assert call(event, {})["status"] == "bad_request"


def test_sender_token_kind():
    items = {(TID, "<SENDER_EMAIL>"): item(TID, "<SENDER_EMAIL>", "a@b.com")}
    assert call({"ticket_id": TID, "token": "<SENDER_EMAIL>"}, items)["value"] == "a@b.com"
