"""Phase 9 output guard: every draft is checked before it can reach a customer.

A failed check never sends: the draft goes to a human reviewer with the list of problems.
Checks (each returns a short problem code):
  empty / too_long           schema
  pii_leak                   a raw email, phone, PAN, IBAN, Aadhaar, Emirates ID... in the draft
  unknown_token              a mask token that is not in this ticket (from another ticket, or invented)
  bad_citation               a cited id that was not retrieved for this ticket
  ungrounded_number          a number that is in no cited source, fact or the ticket itself
  uncited_answer             numbers or a rule stated with no citation at all
  wrong_region               India terms in a UAE reply or the other way round
  superseded_source          cites a chunk not valid on the question date
  instruction_leak           talks about its prompt/instructions, or echoes an injection
  promise                    guarantees an outcome, a date or a refund
  wrong_language             Devanagari/Arabic ticket answered in another script, or the reverse
"""

import re
from datetime import date

from pii import masker

MAX_CHARS = 1500
TOKEN_RE = re.compile(r"<[A-Z_]+_\d+>")
CITE_RE = re.compile(r"\[([^\[\]\s]{2,80})\]")
NUMBER_RE = re.compile(r"(?<![\w<])\d[\d,]*(?:\.\d+)?(?![\w>])")
INDIA_TERMS = re.compile(r"\b(EPF|PF|ESI|ESIC|TDS|UAN|PAN|INR|Rs\.?|₹|professional tax|Form 16)\b", re.I)
UAE_TERMS = re.compile(r"\b(WPS|SIF|MOHRE|AED|dirham|Emirates ID|EDR|gratuity)\b", re.I)
LEAK_RE = re.compile(
    r"(system prompt|my instructions|i was told to|as an ai\b|language model|ignore (all |any )?(previous|prior)"
    r"|developer mode|jailbreak|here (is|are) (my|the) (rules|instructions))", re.I)
PROMISE_RE = re.compile(
    r"\b(guarantee[ds]?|100\s?%|definitely|certainly will|will be refunded|refund (will|is) (be )?(processed|issued)"
    r"|we promise|no later than|by tomorrow|within \d+ (hours|days))\b", re.I)
DEVANAGARI, ARABIC = re.compile(r"[ऀ-ॿ]"), re.compile(r"[؀-ۿ]")


def _script(text: str) -> str:
    dev, ar = len(DEVANAGARI.findall(text)), len(ARABIC.findall(text))
    letters = max(len(re.findall(r"\w", text)), 1)
    if dev / letters > 0.3:
        return "hi"
    if ar / letters > 0.3:
        return "ar"
    return "latin"


def _valid(chunk: dict, as_of: date) -> bool:
    """loader.knowledge.valid_on for chunks whose dates may be ISO strings (checkpointed state)."""
    day = as_of.isoformat()
    start, end = chunk.get("effective_from"), chunk.get("effective_to")
    return (not start or str(start)[:10] <= day) and (not end or day <= str(end)[:10])


def _norm_num(s: str) -> str:
    return s.replace(",", "").rstrip(".")


def pii_found(text: str) -> list[str]:
    without_tokens = TOKEN_RE.sub(" ", text)
    spans = masker._structured_spans(masker.normalize_digits(without_tokens))
    return sorted({s.kind for s in spans})


def check(draft: str, *, ticket_text: str, region: str | None, language: str, hits: list[dict] | None = None,
          facts: list[dict] | None = None, as_of: date | None = None, ref: str = "") -> dict:
    hits, facts = hits or [], facts or []
    problems: list[str] = []
    if not isinstance(draft, str) or not draft.strip():
        return {"ok": False, "problems": ["empty"]}
    if len(draft) > MAX_CHARS:
        problems.append("too_long")

    kinds = pii_found(draft)
    if kinds:
        problems.append("pii_leak:" + ",".join(kinds))

    ticket_tokens = set(TOKEN_RE.findall(ticket_text or ""))
    if set(TOKEN_RE.findall(draft)) - ticket_tokens:
        problems.append("unknown_token")

    by_id = {h["chunk_id"]: h for h in hits} | {f["source"]: f for f in facts}
    cited = [c for c in CITE_RE.findall(draft) if not TOKEN_RE.fullmatch(f"<{c}>")]
    if any(c not in by_id for c in cited):
        problems.append("bad_citation")

    cited_text = " ".join(
        (by_id[c].get("content") or "") + " " + " ".join(str(v) for v in by_id[c].values())
        for c in cited if c in by_id
    )
    grounding = _norm_num(" ".join([cited_text, ticket_text or "", ref]))
    grounded = {_norm_num(n) for n in NUMBER_RE.findall(grounding)}
    body = TOKEN_RE.sub(" ", draft)
    if ref:
        body = body.replace(ref, " ")
    body = CITE_RE.sub(" ", body)
    numbers = [_norm_num(n) for n in NUMBER_RE.findall(body)]
    # A number the customer wrote ("PR-202609") is an echo, not a claim: it needs no citation. Live
    # check: "Payroll run PR-202609 is processing" without an inline [id] was parked as uncited.
    asked = {_norm_num(n) for n in NUMBER_RE.findall(_norm_num(ticket_text or ""))}
    claims = [n for n in numbers if n not in asked]
    if claims and not cited:
        problems.append("uncited_answer")
    elif any(n not in grounded for n in numbers):
        problems.append("ungrounded_number")

    if region == "IN" and UAE_TERMS.search(draft):
        problems.append("wrong_region")
    if region == "UAE" and INDIA_TERMS.search(TOKEN_RE.sub(" ", draft)):
        problems.append("wrong_region")

    if as_of:
        for c in cited:
            h = by_id.get(c)
            if h and "chunk_id" in h and not _valid(h, as_of):
                problems.append("superseded_source")
                break

    if LEAK_RE.search(draft):
        problems.append("instruction_leak")
    if PROMISE_RE.search(draft):
        problems.append("promise")

    want = {"hi": "hi", "ar": "ar"}.get(language, "latin")
    if _script(draft) != want:
        problems.append("wrong_language")
    return {"ok": not problems, "problems": problems}
