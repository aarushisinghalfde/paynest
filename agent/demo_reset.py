"""Clear the demo's LIVE traffic so the control room starts from fresh tickets (runs on the server).

    python -m agent.demo_reset              # counts only, changes nothing
    python -m agent.demo_reset --yes        # delete

Deletes only what live tickets created: tickets with origin = 'live' and their review tasks, sent
replies, model-cost rows, checkpoints and incidents; How-To answers approved during testing and the
"#approved-" guide parts they added; the Redis answer cache, incident and dedupe keys. Keeps the Q3
export, tenants, contracts, statutory rules, the knowledge base and imported articles.
Prints RESET_JSON={...} for scripts/reset_demo.py.
"""
import argparse
import json

import psycopg

from shared import settings

COUNTS = {
    "live_tickets": "SELECT count(*) FROM tickets WHERE origin = 'live'",
    "review_tasks": "SELECT count(*) FROM review_tasks r JOIN tickets t ON t.id = r.ticket_id WHERE t.origin = 'live'",
    "sent_replies": "SELECT count(*) FROM sent_replies s JOIN tickets t ON t.id = s.ticket_id WHERE t.origin = 'live'",
    "cost_rows": "SELECT count(*) FROM cost_ledger WHERE ticket_id IN (SELECT id FROM tickets WHERE origin = 'live')",
    "learned_answers": "SELECT count(*) FROM howto_answers WHERE source = 'agent_approved'",
    "learned_guide_parts": "SELECT count(*) FROM kb_chunks WHERE chunk_id LIKE '%#approved-%'",
    "export_tickets_kept": "SELECT count(*) FROM tickets WHERE origin = 'export'",
}
DELETE = [
    "DELETE FROM review_tasks WHERE ticket_id IN (SELECT id FROM tickets WHERE origin = 'live')",
    "DELETE FROM sent_replies WHERE ticket_id IN (SELECT id FROM tickets WHERE origin = 'live')",
    "DELETE FROM cost_ledger WHERE ticket_id IN (SELECT id FROM tickets WHERE origin = 'live')",
    "DELETE FROM howto_answers WHERE source = 'agent_approved'",
    "DELETE FROM kb_chunks WHERE chunk_id LIKE '%#approved-%'",
    "DELETE FROM incidents WHERE id NOT IN (SELECT incident_id FROM tickets WHERE origin <> 'live' AND incident_id IS NOT NULL)",
    "DELETE FROM tickets WHERE origin = 'live'",  # ticket_inbox and ticket_events cascade
]
CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")
REDIS_PREFIXES = ("howto:", "incident:", "worker:", "review:", "statutory:")


def counts(conn) -> dict:
    return {k: conn.execute(q).fetchone()[0] for k, q in COUNTS.items()}


def reset(conn) -> dict:
    with conn.transaction():
        ids = [r[0] for r in conn.execute("SELECT id::text FROM tickets WHERE origin = 'live'").fetchall()]
        for table in CHECKPOINT_TABLES:  # LangGraph keeps one thread per ticket id
            if conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]:
                conn.execute(f"DELETE FROM {table} WHERE thread_id = ANY(%s)", (ids,))
        for q in DELETE:
            conn.execute(q)
    return {"redis_keys_deleted": _clear_redis()}


def _clear_redis() -> int:
    if not settings.REDIS_URL:
        return 0
    import redis

    r, n = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=5), 0
    for prefix in REDIS_PREFIXES:
        for key in r.scan_iter(f"{prefix}*", count=500):
            n += r.delete(key)
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="delete (without it: counts only)")
    args = ap.parse_args()
    with psycopg.connect(settings.DATABASE_URL, autocommit=False) as conn:
        before = counts(conn)
        out = {"before": before, "deleted": False}
        if args.yes:
            out.update(reset(conn), deleted=True, after=counts(conn))
    print("RESET_JSON=" + json.dumps(out, default=str))


if __name__ == "__main__":
    main()
