"""The PII gate for one ticket, end to end with in-memory store and vault (no Docker, no AWS)."""
import json
import logging
from pathlib import Path

import pytest

from intake import pipeline
from intake.pipeline import process_ticket, rescan
from intake.store import Inbox, MemoryTicketStore
from intake.tokens import sender_token
from intake.vault import MemoryVault, kind_of
from pii import MaskResult

KEY = b"test-key-not-a-secret"
SEED = json.loads((Path(__file__).parent / "fixtures" / "pii_seeded.json").read_text(encoding="utf-8"))


def _submit(store, t):
    return store.create("acme-in" if t["tenant_region"] == "IN" else "gulfco-ae", "web", t["body"],
                        t["sender_name"], t["sender_email"], t["sender_phone"])


@pytest.mark.parametrize("t", SEED, ids=[t["id"] for t in SEED])
def test_seeded_ticket_is_masked_vaulted_and_inbox_deleted(t):
    store, vault = MemoryTicketStore(), MemoryVault()
    tid = _submit(store, t)
    out = process_ticket(tid, store, vault, KEY)
    assert out.status == "masked", out.reasons
    row = store.get(tid)
    assert row["status"] == "masked" and tid not in store.inbox      # raw text is gone
    for value in t["raw_values"]:
        assert value not in row["masked_body"]
    # every token in the masked text can be revealed, for this ticket only
    for token in {tok for tok in vault.items if tok[0] == tid}:
        assert vault.reveal(tid, token[1]) is not None
        assert vault.reveal("another-ticket", token[1]) is None


def test_sender_fields_are_vaulted_and_tokenised():
    store, vault = MemoryTicketStore(), MemoryVault()
    tid = store.create("acme-in", "email", "Salary not credited.", "Kavya Kulkarni",
                       "Kavya.K@Outlook.com", "+91 98765 43210")
    process_ticket(tid, store, vault, KEY)
    assert vault.reveal(tid, "<SENDER_EMAIL>") == "Kavya.K@Outlook.com"
    assert vault.reveal(tid, "<SENDER_NAME>") == "Kavya Kulkarni"
    t = store.tickets[tid]
    assert t["sender_email_token"] == sender_token(KEY, "acme-in", "email", "kavya.k@outlook.com")
    assert t["sender_phone_token"].startswith("ph_")


def test_redelivered_message_is_skipped_not_reprocessed():
    store, vault = MemoryTicketStore(), MemoryVault()
    tid = store.create("acme-in", "web", "PAN ABCPK1234F please fix", None, None, None)
    assert process_ticket(tid, store, vault, KEY).status == "masked"
    assert process_ticket(tid, store, vault, KEY).status == "skipped"


def test_vault_failure_keeps_the_inbox_for_redelivery():
    class DownVault(MemoryVault):
        def put(self, *a, **k):
            raise ConnectionError("vault down")

    store = MemoryTicketStore()
    tid = store.create("acme-in", "web", "PAN ABCPK1234F please fix", None, None, None)
    with pytest.raises(ConnectionError):
        process_ticket(tid, store, DownVault(), KEY)
    assert store.tickets[tid]["status"] == "received" and tid in store.inbox


def test_leak_after_masking_is_quarantined(monkeypatch):
    """If masking ever lets a value through, the re-scan blocks the ticket."""
    calls = []

    def leaky_mask(body, **kw):
        calls.append(body)
        if len(calls) > 1:                            # the re-scan's second pass sees nothing
            return MaskResult(text=body, values={}, counts={})
        return MaskResult(text="IBAN AE070331234567890123456 is wrong",
                          values={"<IBAN_1>": "AE070331234567890123456"}, counts={"IBAN": 1})

    monkeypatch.setattr(pipeline, "mask_ticket", leaky_mask)
    store, vault = MemoryTicketStore(), MemoryVault()
    tid = store.create("gulfco-ae", "web", "IBAN AE070331234567890123456 is wrong", None, None, None)
    out = process_ticket(tid, store, vault, KEY)
    assert out.status == "pii_blocked"
    assert out.reasons == ["value_survived:IBAN"]
    assert store.tickets[tid]["masked_body"] is None and store.get(tid)["masked_body"] is None
    assert vault.items == {}                          # nothing vaulted for a blocked ticket
    assert tid in store.inbox                         # kept for human review


def test_second_pass_catches_what_the_first_pass_missed():
    """A phone left in the 'masked' text is found by running the recognisers again."""
    inbox = Inbox("t", "acme-in", "please call 98765 43210")
    assert rescan("please call 98765 43210", {}, inbox) == ["second_pass:PHONE"]


def test_sender_email_left_in_text_is_caught():
    inbox = Inbox("t", "acme-in", "", sender_email="a.b@x.com")
    assert rescan("reply to a.b@x.com", {}, inbox) == sorted(
        ["sender_field_in_text:email", "second_pass:EMAIL"])


def test_short_name_inside_a_longer_word_is_not_a_leak():
    """علي (a name) inside عليه (a word) must not quarantine the ticket."""
    inbox = Inbox("t", "gulfco-ae", "")
    assert rescan("يرجى إرسال شهادة الراتب عليه ختم الشركة", {"<NAME_1>": "علي"}, inbox) == []


def test_logs_never_contain_raw_values(caplog):
    store, vault = MemoryTicketStore(), MemoryVault()
    caplog.set_level(logging.DEBUG)
    for t in SEED[:20] + SEED[-10:]:
        process_ticket(_submit(store, t), store, vault, KEY)
    text = "\n".join(r.getMessage() + json.dumps(getattr(r, "fields", {}), ensure_ascii=False)
                     for r in caplog.records)
    assert "ticket_masked" in text
    for t in SEED[:20] + SEED[-10:]:
        for v in t["raw_values"] + [t["sender_email"] or "@@", t["body"][:40]]:
            assert v not in text


def test_kind_of_token():
    assert kind_of("<IBAN_2>") == "IBAN" and kind_of("<SENDER_EMAIL>") == "SENDER_EMAIL"
    assert kind_of("<EMIRATES_ID_1>") == "EMIRATES_ID"
    with pytest.raises(ValueError):
        kind_of("IBAN_1")


def test_store_delete_removes_ticket_and_inbox():
    store = MemoryTicketStore()
    tid = store.create("acme-in", "web", "x")
    store.delete(tid)
    assert store.tickets == {} and store.inbox == {}
