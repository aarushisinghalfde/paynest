"""PII gate: find and mask personal data before anything else reads a ticket.

    from pii import mask_ticket
    result = mask_ticket(body, sender_name=..., sender_email=..., sender_phone=...)
    result.text      # body with <TYPE_n> tokens
    result.values    # {"<IBAN_1>": "AE07...", ...}  -> goes to the encrypted pii_vault, never logged

Pure Python (regular expressions + checksum validators), so it is fast, has no model
downloads and is fully unit-tested. See docs/architecture.md, phase 3.
"""
from pii.masker import MaskResult, mask_ticket

__all__ = ["MaskResult", "mask_ticket"]
