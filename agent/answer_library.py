"""Approved How-To answers: written once by support, reused for every similar question.

The library lives in Postgres (`howto_answers`, migration 007) so it survives restarts and
cache flushes; the Redis answer cache stays the fast layer for generated answers. An answer
enters the library when a reviewer approves a "knowledge" task (agent.store.decide_review).
Matching is by meaning, with the same word/trigram similarity as the answer cache.
"""

from agent.answer_cache import GRAMS_MIN, similarity  # noqa: F401 - similarity re-exported


def best(question: str, entries: list[dict], threshold: float = GRAMS_MIN) -> dict | None:
    scored = [(similarity(question, e["question"]), e) for e in entries]
    scored = [(s, e) for s, e in scored if s >= threshold]
    if not scored:
        return None
    s, e = max(scored, key=lambda x: x[0])
    return {**e, "similarity": round(s, 3)}


def as_source(entry: dict) -> dict:
    """The approved answer as a citable source, so the output guard checks it like any other."""
    return {"chunk_id": f"ANS-{entry['id'][:8]}#approved", "kb_id": None, "source_kind": "approved_answer",
            "region": entry.get("region") or "ALL", "topic": "howto", "title": "Approved answer",
            "content": entry["answer"], "effective_from": None, "effective_to": None, "superseded_by": None}
