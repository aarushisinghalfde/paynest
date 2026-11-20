"""Write the dataset to Postgres in one transaction (all or nothing), and read it back.

Re-running a load is safe: rows are upserted by primary key, a ticket's events are replaced,
and record ids are deterministic (uuid5 of the source reference).
"""

import json
from datetime import date

KEYS = {  # table -> primary key, in write order (parents first)
    "tenants": ["tenant_id"],
    "tickets": ["id"],
    "ticket_events": ["ticket_id", "seq"],
    "whatsapp_threads": ["id"],
    "whatsapp_messages": ["thread_id", "seq"],
    "call_notes": ["id"],
    "jira_issues": ["key"],
    "csat_responses": ["survey_id"],
    "sla_breaches": ["breach_id"],
    "agents": ["agent_id"],
    "monthly_costs": ["month"],
    "sla_terms": ["template_version", "tier", "priority"],
    "statutory_rules": ["rule_id"],
    "kb_chunks": ["chunk_id"],
}
JSON_COLUMNS = {"pii_counts", "data"}
DATE_COLUMNS = {"effective_from", "effective_to", "last_reviewed"}


def upsert_sql(table: str, columns: list[str]) -> str:
    keys = KEYS[table]
    updates = [c for c in columns if c not in keys]
    action = (
        ("DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in updates)) if updates else "DO NOTHING"
    )
    return (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) "
        f"ON CONFLICT ({', '.join(keys)}) {action}"
    )


def _adapt(column, value):
    if column in JSON_COLUMNS:
        from psycopg.types.json import Jsonb

        return Jsonb(value)
    return value


def write(conn, tables: dict[str, list[dict]], summary: dict) -> None:
    with conn.transaction():
        ticket_ids = [t["id"] for t in tables.get("tickets", [])]
        if ticket_ids:  # events are replaced as a whole
            conn.execute("DELETE FROM ticket_events WHERE ticket_id = ANY(%s::uuid[])", (ticket_ids,))
        for table in KEYS:
            rows = tables.get(table) or []
            if not rows:
                continue
            columns = list(rows[0])
            with conn.cursor() as cur:
                cur.executemany(
                    upsert_sql(table, columns), [[_adapt(c, r.get(c)) for c in columns] for r in rows]
                )
        conn.execute(
            "INSERT INTO load_runs (finished_at, summary) VALUES (now(), %s)",
            (json.dumps(summary, default=str),),
        )


def read_tables(conn) -> dict[str, list[dict]]:
    """Every loaded table back as dicts (for the verify gates and the leak scan)."""
    out = {}
    for table in KEYS:
        where = " WHERE origin = 'export'" if table == "tickets" else ""
        rows = [r[0] for r in conn.execute(f"SELECT row_to_json(t) FROM {table} t{where}").fetchall()]
        for r in rows:
            for c in DATE_COLUMNS & r.keys():
                if r[c]:
                    r[c] = date.fromisoformat(r[c][:10])
        out[table] = rows
    return out
