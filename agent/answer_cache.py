"""How-To answer cache: reuse answers already given, before any retrieval or model call.

The flow for a How-To question: cache -> (miss) RAG over approved sources -> answer, and the
answer is cached for the next person who asks the same thing in other words.

  key      region + language + knowledge-base version. A new KB version (a rule changes, an
           article is added) starts an empty bucket, so a stale answer is never reused.
  match    by meaning, not exact text: stemmed-word overlap >= 0.6 or character-trigram
           overlap >= 0.75 with a cached question (agent.retrieval word/trigram helpers).
  stored   the masked question, the answer, its citations and the cited chunks, so the
           output guard re-checks a cached answer exactly like a fresh one.
  backends Redis (ElastiCache Valkey in AWS, any REDIS_URL locally) or memory for tests.
A cache failure is a miss, never an error: the RAG path still answers.
"""

import hashlib
import json
import logging
import time

from agent.retrieval import trigrams, words
from shared.logs import log_event, safe_error

log = logging.getLogger("answer_cache")
TTL_SECONDS = 7 * 24 * 3600
MAX_ENTRIES = 500
WORDS_MIN, GRAMS_MIN = 0.6, 0.75


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def similarity(q1: str, q2: str) -> float:
    return max(_jaccard(set(words(q1)), set(words(q2))) / WORDS_MIN * GRAMS_MIN,
               _jaccard(trigrams(q1), trigrams(q2)))


def _bucket(kb_version: str, region: str | None, language: str) -> str:
    return f"howto:{kb_version}:{region or 'ALL'}:{language}"


def _field(question: str) -> str:
    return hashlib.sha256(" ".join(sorted(set(words(question)))).encode()).hexdigest()[:16]


def _best(entries: list[dict], question: str) -> dict | None:
    best, score = None, 0.0
    for e in entries:
        s = similarity(question, e["question"])
        if s > score:
            best, score = e, s
    return {**best, "similarity": round(score, 3)} if best and score >= GRAMS_MIN else None


class MemoryAnswerCache:
    def __init__(self):
        self.buckets: dict[str, dict[str, dict]] = {}

    def get(self, question, region, language, kb_version):
        return _best(list(self.buckets.get(_bucket(kb_version, region, language), {}).values()), question)

    def put(self, question, region, language, kb_version, answer, citations, hits):
        b = self.buckets.setdefault(_bucket(kb_version, region, language), {})
        if len(b) < MAX_ENTRIES:
            b[_field(question)] = {"question": question, "answer": answer, "citations": citations, "hits": hits,
                                   "cached_at": int(time.time())}


class RedisAnswerCache:
    def __init__(self, client):
        self.r = client

    def get(self, question, region, language, kb_version):
        try:
            raw = self.r.hgetall(_bucket(kb_version, region, language))
            return _best([json.loads(v) for v in raw.values()], question)
        except Exception as exc:  # noqa: BLE001 - a cache problem is a miss
            log_event(log, "answer_cache_error", logging.WARNING, op="get", **safe_error(exc))
            return None

    def put(self, question, region, language, kb_version, answer, citations, hits):
        key = _bucket(kb_version, region, language)
        try:
            if self.r.hlen(key) >= MAX_ENTRIES:
                return
            entry = {"question": question, "answer": answer, "citations": citations, "hits": hits,
                     "cached_at": int(time.time())}
            self.r.hset(key, _field(question), json.dumps(entry, ensure_ascii=False, default=str))
            self.r.expire(key, TTL_SECONDS)
        except Exception as exc:  # noqa: BLE001
            log_event(log, "answer_cache_error", logging.WARNING, op="put", **safe_error(exc))
