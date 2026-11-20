"""Vault writes: per-value KMS encryption bound to ticket and token, append-only DynamoDB puts."""
import pytest

from intake import vault as vault_mod
from intake.vault import DynamoKmsVault, MemoryVault


class FakeKms:
    def __init__(self):
        self.calls = []

    def encrypt(self, KeyId, Plaintext, EncryptionContext):  # noqa: N803 - boto3 names
        self.calls.append((KeyId, EncryptionContext))
        return {"CiphertextBlob": b"ct:" + Plaintext[::-1]}


class ConditionalCheckFailedException(Exception):
    pass


class FakeDdb:
    def __init__(self):
        self.items = {}

    def put_item(self, TableName, Item, ConditionExpression):  # noqa: N803
        key = (Item["ticket_id"]["S"], Item["token"]["S"])
        assert ConditionExpression == "attribute_not_exists(ticket_id)"
        if key in self.items:
            raise ConditionalCheckFailedException()
        self.items[key] = Item


def test_each_value_encrypted_with_its_ticket_and_token():
    kms, ddb = FakeKms(), FakeDdb()
    v = DynamoKmsVault("tbl", "alias/vault", ddb, kms)
    assert v.put("t1", "acme-in", {"<IBAN_1>": "AE07...", "<NAME_1>": "Kavya"}, 1900000000) == 2
    assert {c[1]["token"] for c in kms.calls} == {"<IBAN_1>", "<NAME_1>"}
    assert all(c == ("alias/vault", {"ticket_id": "t1", "token": c[1]["token"], "tenant_id": "acme-in"})
               for c in kms.calls)
    item = ddb.items[("t1", "<IBAN_1>")]
    assert item["kind"] == {"S": "IBAN"} and item["expires_at"] == {"N": "1900000000"}
    assert b"AE07" not in item["ciphertext"]["B"]   # only ciphertext is stored


def test_rewrite_is_ignored_not_overwritten():
    kms, ddb = FakeKms(), FakeDdb()
    v = DynamoKmsVault("tbl", "k", ddb, kms)
    v.put("t1", "acme-in", {"<PAN_1>": "ABCPK1234F"}, 1)
    assert v.put("t1", "acme-in", {"<PAN_1>": "EVIL"}, 1) == 0
    assert ddb.items[("t1", "<PAN_1>")]["ciphertext"]["B"] == b"ct:" + b"ABCPK1234F"[::-1]


def test_other_dynamo_errors_propagate():
    class Broken(FakeDdb):
        def put_item(self, **kw):
            raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        DynamoKmsVault("tbl", "k", Broken(), FakeKms()).put("t1", "x", {"<PAN_1>": "A"}, 1)


def test_oversized_value_rejected():
    with pytest.raises(ValueError):
        DynamoKmsVault("tbl", "k", FakeDdb(), FakeKms()).put("t1", "x", {"<NAME_1>": "a" * 5000}, 1)


def test_backend_must_be_chosen_explicitly():
    class S:
        VAULT_BACKEND = ""

    with pytest.raises(RuntimeError):
        vault_mod.from_settings(S())
    S.VAULT_BACKEND = "memory"
    assert isinstance(vault_mod.from_settings(S()), MemoryVault)


def test_memory_vault_is_append_only_too():
    v = MemoryVault()
    assert v.put("t1", "x", {"<PAN_1>": "ABCPK1234F"}, 2**40) == 1
    assert v.put("t1", "x", {"<PAN_1>": "EVIL"}, 2**40) == 0
    assert v.reveal("t1", "<PAN_1>") == "ABCPK1234F"
    v.put("t2", "x", {"<PAN_1>": "OLD"}, 1)
    assert v.reveal("t2", "<PAN_1>") is None          # expired
