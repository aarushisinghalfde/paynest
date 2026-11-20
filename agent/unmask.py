"""Phase 10: what the customer sees. Replies are stored masked; tokens are resolved at send.

customer_view(text, reveal) replaces each mask token:
  - with `reveal(token)` when a revealer is configured. In production that is the channel
    adapter calling the audited vault-reveal Lambda under its own role; the EC2 role can
    never decrypt (phase 3), so the demo has no revealer;
  - otherwise with a neutral phrase, so a customer never sees "<NAME_1>".
Storage, logs and the reviewer console keep the masked text.
"""

import re

TOKEN_RE = re.compile(r"<([A-Z_]+)_\d+>")
NEUTRAL = {"NAME": "", "EMAIL": "your email", "PHONE": "your phone number", "IBAN": "your bank account",
           "BANK_ACCOUNT": "your bank account"}


def customer_view(text: str, reveal=None) -> str:
    if not text:
        return text

    def sub(m):
        if reveal is not None:
            value = reveal(m.group(0))
            if value:
                return value
        return NEUTRAL.get(m.group(1), "the details you shared")

    out = TOKEN_RE.sub(sub, text)
    out = re.sub(r"[ \t]+([,.!?])", r"\1", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()
