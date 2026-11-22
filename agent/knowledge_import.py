"""Phase B: turn uploaded support articles and approved answers into agent knowledge.

Articles (Markdown, HTML or plain text, e.g. a Confluence export) may start with front matter:

    ---
    id: KB-0105
    title: Downloading payslips in bulk
    region: ALL            # IN | UAE | ALL
    language: en           # en | hi-Latn | hi | ar
    ---

Without it, the id comes from the file name (KB-0105 ...) and the title from the first heading.
Every article is masked (same masker as tickets; the raw values are dropped, not vaulted, and the
tokens become neutral words such as "[email removed]", because knowledge is shared across customers),
split into chunks of at most ~900 characters, and tagged statutory when it talks about PF,
WPS, TDS or gratuity: statutory articles are used only on the human-review route, never in
an auto-sent How-To reply.

Approved answers come as CSV with the columns question, answer and optionally language,
region and kb_ids (separated by ;). They go straight into the How-To answer library.
"""

import csv
import html
import io
import re
from dataclasses import dataclass, field

from agent.tools import RATE_TRIGGERS
from pii import masker

KB_ID_RE = re.compile(r"\b([A-Z]{2,5}-[A-Z0-9]{2,12}(?:-[A-Z0-9]{1,8})?)\b")
VALID_ID = re.compile(r"^[A-Z]{2,5}-[A-Z0-9]{2,12}(?:-[A-Z0-9]{1,8})?$")
REGIONS, LANGUAGES = {"IN", "UAE", "ALL"}, {"en", "hi-Latn", "hi", "ar"}
MAX_BODY, CHUNK = 60_000, 900


@dataclass
class Article:
    kb_id: str
    title: str
    region: str
    language: str
    topic: str
    chunks: list[str]
    masked_counts: dict = field(default_factory=dict)


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def _front_matter(text: str) -> tuple[dict, str]:
    m = re.match(r"^﻿?---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.split("#", 1)[0].strip()
    return meta, text[m.end():]


def chunk(body: str, size: int = CHUNK) -> list[str]:
    """Split on headings and blank lines, packing paragraphs into chunks of at most `size` chars."""
    parts = [p.strip() for p in re.split(r"\n\s*\n|\n(?=#{1,6} )", body) if p.strip()]
    out, cur = [], ""
    for p in parts:
        while len(p) > size:  # a very long paragraph: cut at a sentence end
            cut = max(p.rfind(". ", 0, size), size // 2)
            out.append((cur + "\n" + p[:cut + 1]).strip() if cur else p[:cut + 1])
            cur, p = "", p[cut + 1:].strip()
        if len(cur) + len(p) + 1 > size and cur:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur}\n{p}".strip()
    if cur:
        out.append(cur)
    return out


TOKEN_RE = re.compile(r"<([A-Z_]+)_\d+>")


def _scrub(text: str) -> tuple[str, dict]:
    """Mask PII, then turn the tokens into neutral words: knowledge is reused across customers,
    so it must not carry tokens (the output guard rejects tokens that are not the customer's)."""
    m = masker.mask_ticket(text)
    return TOKEN_RE.sub(lambda t: f"[{t.group(1).lower().replace('_', ' ')} removed]", m.text), dict(m.counts)


def parse_article(filename: str, text: str) -> Article:
    if len(text) > MAX_BODY:
        raise ValueError(f"{filename}: larger than {MAX_BODY:,} characters")
    meta, body = _front_matter(text)
    if filename.lower().endswith((".html", ".htm")) or re.search(r"(?i)<(p|div|h1|ul)\b", body):
        h1 = re.search(r"(?is)<(h1|title)[^>]*>(.*?)</\1>", body)
        if h1 and not meta.get("title"):
            meta["title"] = html.unescape(re.sub(r"<[^>]+>", "", h1.group(2))).strip()
            body = body[:h1.start()] + body[h1.end():]
        body = _strip_html(body)
    kb_id = (meta.get("id") or meta.get("kb_id") or "").upper()
    if not kb_id:
        m = KB_ID_RE.search(filename.upper())
        kb_id = m.group(1) if m else ""
    if not VALID_ID.match(kb_id):
        raise ValueError(f"{filename}: no valid article id (add 'id: KB-0123' front matter or put it in the file name)")
    title = meta.get("title") or ""
    h = re.search(r"^\s*#{1,3}\s+(.+)$", body, re.M)
    if not title:
        title = h.group(1).strip() if h else re.sub(r"\.(md|txt|html?)$", "", filename, flags=re.I)
        title = re.sub(rf"^{re.escape(kb_id)}[\s_:-]*", "", title, flags=re.I) or title
    if h and h.group(1).strip() == title:  # the heading is the title: do not repeat it in the body
        body = body[:h.start()] + body[h.end():]
    region = (meta.get("region") or "ALL").upper()
    language = meta.get("language") or "en"
    if region not in REGIONS:
        raise ValueError(f"{filename}: region must be IN, UAE or ALL")
    if language not in LANGUAGES:
        raise ValueError(f"{filename}: language must be one of {sorted(LANGUAGES)}")
    clean, counts = _scrub(f"{title}\n\n{body}")
    m_title, _, m_body = clean.partition("\n\n")
    statutory = [topic for rx, _rg, topic in RATE_TRIGGERS if rx.search(clean)]
    pieces = chunk(m_body)
    if not pieces:
        raise ValueError(f"{filename}: no text after the front matter")
    return Article(kb_id=kb_id, title=m_title.strip()[:200], region=region, language=language,
                   topic=f"statutory:{statutory[0]}" if statutory else "howto", chunks=pieces,
                   masked_counts=counts)


def parse_answers_csv(text: str) -> list[dict]:
    rows = []
    for i, r in enumerate(csv.DictReader(io.StringIO(text.lstrip("﻿"))), start=2):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        if not r.get("question") or not r.get("answer"):
            raise ValueError(f"line {i}: question and answer are required")
        language = r.get("language") or "en"
        region = (r.get("region") or "").upper() or None
        if language not in LANGUAGES or (region and region not in REGIONS):
            raise ValueError(f"line {i}: bad language or region")
        (q, qc), (a, ac) = _scrub(r["question"]), _scrub(r["answer"])
        rows.append({"question": q, "answer": a, "language": language,
                     "region": None if region in (None, "ALL") else region,
                     "kb_ids": [k.strip().upper() for k in (r.get("kb_ids") or "").split(";") if k.strip()],
                     "masked": sum(qc.values()) + sum(ac.values())})
    return rows
