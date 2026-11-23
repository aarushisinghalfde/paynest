"""Knowledge chunks with effective dates, and statutory rules looked up by date.

Only 4 of the 24 KB articles carry text, and all 4 state the rule that changed in Q3
(PF wage ceiling INR 15,000 -> 25,000 from 1 Aug; WPS SIF v2 14 columns -> v3 16 columns
from 15 Jul). So the store holds (build plan, section 8):
  - 24 title chunks, pointing to the right article id;
  - the 4 old excerpts, closed with effective_to = the day before the rule changed and
    superseded_by = the rule's corrected chunk;
  - 4 corrected chunks written from statutory_rules.json, valid from the rule's date;
  - the process documents, one chunk per section, for reviewer-facing guidance.
Retrieval filters on the date the QUESTION is about, never today's date.
"""

import re
from datetime import date, timedelta


def _d(v) -> date | None:
    return date.fromisoformat(v) if isinstance(v, str) and v else v or None


def valid_on(chunk: dict, as_of: date) -> bool:
    start, end = chunk.get("effective_from"), chunk.get("effective_to")
    return (start is None or start <= as_of) and (end is None or as_of <= end)


def chunks_as_of(chunks: list[dict], topic: str, region: str, as_of: date) -> list[dict]:
    """What a question about `topic` for a tenant in `region` may cite, on date `as_of`."""
    return [
        c for c in chunks if c["topic"] == topic and c["region"] in (region, "ALL") and valid_on(c, as_of)
    ]


def rule_chunk_id(rule: dict) -> str:
    return f"{rule['rule_id']}#rule"


def build_chunks(kb_articles: list[dict], rules: list[dict], process_docs: dict[str, str]) -> list[dict]:
    by_topic = {}
    for r in rules:
        for t in r.get("affects_kb_topics") or []:
            by_topic[t] = r
    chunks = []
    for a in kb_articles:
        base = {
            "kb_id": a["id"],
            "title": a["title"],
            "region": a["region"],
            "topic": a["topic"],
            "language": "en",
            "last_reviewed": _d(a.get("last_reviewed")),
            "superseded_by": None,
            "effective_from": None,
            "effective_to": None,
            # the guide's page, when the export carries one (customers get the link with the answer)
            "url": next((a[k] for k in ("url", "link", "confluence_url", "help_url")
                         if str(a.get(k) or "").startswith("https://")), None),
        }
        chunks.append(
            {
                **base,
                "chunk_id": f"{a['id']}#title",
                "source_kind": "kb_title",
                "content": f"{a['id']}: {a['title']}",
            }
        )
        excerpt = (a.get("excerpt") or "").strip()
        if excerpt and "See full article in Confluence" not in excerpt:
            rule = by_topic.get(a["topic"])
            chunk = {
                **base,
                "chunk_id": f"{a['id']}#excerpt",
                "source_kind": "kb_excerpt",
                "content": excerpt,
            }
            if rule:
                chunk["effective_to"] = _d(rule["effective_from"]) - timedelta(days=1)
                chunk["superseded_by"] = rule_chunk_id(rule)
            chunks.append(chunk)
    for r in rules:
        topic = (r.get("affects_kb_topics") or [r["topic"]])[0]
        chunks.append(
            {
                "chunk_id": rule_chunk_id(r),
                "kb_id": None,
                "source_kind": "rule",
                "region": r["region"],
                "topic": topic,
                "language": "en",
                "title": r["title"],
                "last_reviewed": None,
                "effective_from": _d(r["effective_from"]),
                "effective_to": None,
                "superseded_by": None,
                "content": (
                    f"{r['title']}. From {r['effective_from']}: {r['new_value']} "
                    f"(before: {r['old_value']}). Source: {r['source']}. Rule {r['rule_id']}."
                ),
            }
        )
    for name, md in sorted(process_docs.items()):
        stem = name.rsplit("/", 1)[-1].removesuffix(".md")
        doc_title = (re.search(r"^# (.+)$", md, re.M) or [None, stem])[1]
        for section in re.split(r"(?m)^(?=## )", md):
            heading = re.match(r"## (.+)", section)
            if not heading:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", heading.group(1).lower()).strip("-")
            chunks.append(
                {
                    "chunk_id": f"process/{stem}#{slug}",
                    "kb_id": None,
                    "source_kind": "process_doc",
                    "region": "ALL",
                    "topic": f"process_{stem}",
                    "language": "en",
                    "title": f"{doc_title}: {heading.group(1)}",
                    "last_reviewed": None,
                    "effective_from": None,
                    "effective_to": None,
                    "superseded_by": None,
                    "content": section.strip(),
                }
            )
    return chunks


def rule_rows(rules: list[dict]) -> list[dict]:
    return [
        {
            "rule_id": r["rule_id"],
            "region": r["region"],
            "topic": r["topic"],
            "title": r["title"],
            "effective_from": _d(r["effective_from"]),
            "old_value": r["old_value"],
            "new_value": r["new_value"],
            "affects_kb_topics": r.get("affects_kb_topics") or [],
            "source": r.get("source"),
            "status": r.get("status"),
        }
        for r in rules
    ]


def get_rate(rules: list[dict], region: str, topic: str, as_of: date) -> dict | None:
    """The value in force on `as_of` (stand-in for the engine's /statutory/rates API).

    `topic` may be the rule topic (pf_wage_ceiling) or a KB topic it affects (tds).
    Before the rule's effective date the old value is returned, after it the new one.
    """
    matches = [
        r
        for r in rules
        if r["region"] == region and (r["topic"] == topic or topic in (r.get("affects_kb_topics") or []))
    ]
    if not matches:
        return None
    r = max(matches, key=lambda x: x["effective_from"])
    new = as_of >= r["effective_from"]
    return {
        "rule_id": r["rule_id"],
        "value": r["new_value"] if new else r["old_value"],
        "in_force_since": r["effective_from"] if new else None,
        "changes_on": None if new else r["effective_from"],
    }
