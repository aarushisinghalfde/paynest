"""The PII gate for one ticket. The worker runs this before anything else touches the ticket.

    load raw inbox -> mask -> re-scan masked text -> (clean)   vault raw values, save masked, delete inbox
                                                   -> (hit)     quarantine as pii_blocked, keep inbox

Order matters for retries: values go to the vault before the masked row is saved, so if
the vault write fails the inbox row is still there and SQS redelivers the message. Vault
writes are append-only and masking is deterministic, so a retry writes the same tokens.
"""
import logging
import re
import time
from dataclasses import dataclass

from intake.tokens import sender_token
from pii import mask_ticket, presidio_layer
from pii.normalize import normalize_digits
from shared.logs import log_event

log = logging.getLogger("pii.gate")

SENDER_TOKENS = {"sender_name": "<SENDER_NAME>", "sender_email": "<SENDER_EMAIL>",
                 "sender_phone": "<SENDER_PHONE>"}


@dataclass
class Outcome:
    ticket_id: str
    status: str                 # masked | pii_blocked | skipped
    counts: dict
    reasons: list
    ms: float


def _squash(s: str) -> str:
    return re.sub(r"[\s\-]", "", normalize_digits(s))


def _present(value: str, text: str) -> bool:
    """value appears in text as a whole word (or, for IDs, also with separators removed)."""
    v = normalize_digits(value).strip()
    if len(v) < 2:
        return False
    if re.search(r"(?<!\w)" + re.escape(v) + r"(?!\w)", normalize_digits(text)):
        return True
    sq = _squash(v)
    return sq.isascii() and sq.isalnum() and len(sq) >= 6 and any(c.isdigit() for c in sq) and \
        sq in _squash(text)


def rescan(masked: str, values: dict, inbox) -> list[str]:
    """Reasons the masked text is unsafe; empty means clean. Reasons carry kinds, never values."""
    reasons = set()
    for token, value in values.items():
        if _present(value, masked):
            reasons.add("value_survived:" + token.strip("<>").rsplit("_", 1)[0])
    for field in ("sender_email", "sender_phone"):
        value = getattr(inbox, field)
        if value and _present(value, masked):
            reasons.add("sender_field_in_text:" + field.split("_")[1])
    second = mask_ticket(masked, sender_name=inbox.sender_name)
    for kind in second.counts:
        reasons.add("second_pass:" + kind)
    return sorted(reasons)


def ner_layer_name() -> str:
    return "presidio" if presidio_layer.available() else "rules"


def process_ticket(ticket_id: str, store, vault, hmac_key: bytes, ttl_days: int = 30,
                   now=time.time) -> Outcome:
    t0 = time.perf_counter()
    inbox = store.load_inbox(ticket_id)
    if inbox is None:   # already masked or quarantined (a redelivered message), or unknown id
        log_event(log, "ticket_skipped", ticket_id=ticket_id)
        return Outcome(ticket_id, "skipped", {}, [], 0.0)

    result = mask_ticket(inbox.body, sender_name=inbox.sender_name, sender_email=inbox.sender_email,
                         sender_phone=inbox.sender_phone)
    layer = ner_layer_name()
    reasons = rescan(result.text, result.values, inbox)
    ms = round((time.perf_counter() - t0) * 1000, 1)

    if reasons:
        store.save_blocked(ticket_id, result.counts, reasons, layer)
        log_event(log, "pii_blocked", logging.WARNING, ticket_id=ticket_id, tenant_id=inbox.tenant_id,
                  counts=result.counts, reasons=reasons, ner_layer=layer, ms=ms)
        return Outcome(ticket_id, "pii_blocked", result.counts, reasons, ms)

    values = dict(result.values)
    for field, token in SENDER_TOKENS.items():
        if getattr(inbox, field):
            values[token] = getattr(inbox, field)
    expires_at = int(now()) + ttl_days * 86400
    vault.put(ticket_id, inbox.tenant_id, values, expires_at)
    store.save_masked(ticket_id, result.text, result.counts,
                      sender_token(hmac_key, inbox.tenant_id, "email", inbox.sender_email),
                      sender_token(hmac_key, inbox.tenant_id, "phone", inbox.sender_phone),
                      layer)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    log_event(log, "ticket_masked", ticket_id=ticket_id, tenant_id=inbox.tenant_id, counts=result.counts,
              vaulted=len(values), ner_layer=layer, ms=ms)
    return Outcome(ticket_id, "masked", result.counts, [], ms)
