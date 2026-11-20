"""What the agent reads and writes (masked data only). Postgres in AWS, memory in tests."""

import json
import threading
import uuid

from intake.store import MemoryTicketStore, PgTicketStore


class PgAgentStore(PgTicketStore):
    def create_idempotent(
        self,
        tenant_id,
        channel,
        body,
        sender_name=None,
        sender_email=None,
        sender_phone=None,
        idempotency_key=None,
    ) -> tuple[str, bool]:
        """(ticket_id, created). The unique index makes 20 parallel posts create one ticket."""
        if not idempotency_key:
            return self.create(tenant_id, channel, body, sender_name, sender_email, sender_phone), True
        ticket_id = str(uuid.uuid4())
        with self._conn() as conn, conn.transaction():
            row = conn.execute(
                """INSERT INTO tickets (id, tenant_id, channel, idempotency_key) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING
                   RETURNING id::text""",
                (ticket_id, tenant_id, channel, idempotency_key),
            ).fetchone()
            if row is None:
                existing = conn.execute(
                    "SELECT id::text FROM tickets WHERE tenant_id = %s AND idempotency_key = %s",
                    (tenant_id, idempotency_key),
                ).fetchone()
                return existing[0], False
            conn.execute(
                """INSERT INTO ticket_inbox (ticket_id, body, sender_name, sender_email, sender_phone)
                            VALUES (%s, %s, %s, %s, %s)""",
                (ticket_id, body, sender_name, sender_email, sender_phone),
            )
        return ticket_id, True

    def masked(self, ticket_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT id::text, tenant_id, status, coalesce(subject_masked, ''), masked_body,
                                         ticket_ref, created_at FROM tickets WHERE id = %s""",
                (ticket_id,),
            ).fetchone()
        if not row:
            return None
        keys = ("id", "tenant_id", "status", "subject", "body", "ticket_ref", "created_at")
        return dict(zip(keys, row, strict=True))

    def tenant(self, tenant_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT row_to_json(t) FROM tenants t WHERE tenant_id = %s", (tenant_id,)
            ).fetchone()
        return row[0] if row else None

    def save_progress(self, ticket_id: str, **fields) -> None:
        allowed = {"agent_status", "route", "route_reason", "classification", "team", "language"}
        fields = {
            k: (json.dumps(v) if k == "classification" else v) for k, v in fields.items() if k in allowed
        }
        if not fields:
            return
        sets = ", ".join(f"{k} = %s" for k in fields)
        with self._conn() as conn:
            conn.execute(f"UPDATE tickets SET {sets} WHERE id = %s", (*fields.values(), ticket_id))

    def insert_reply(self, ticket_id: str, draft_version: int, body: str, channel: str) -> bool:
        """True if this call sent it; False if (ticket, version) was already sent."""
        with self._conn() as conn:
            row = conn.execute(
                """INSERT INTO sent_replies (ticket_id, draft_version, body_masked, channel)
                                  VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING ticket_id""",
                (ticket_id, draft_version, body, channel),
            ).fetchone()
        return row is not None

    def replies(self, ticket_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT draft_version, body_masked, sent_at FROM sent_replies
                                   WHERE ticket_id = %s ORDER BY draft_version""",
                (ticket_id,),
            ).fetchall()
        return [{"draft_version": v, "body": b, "sent_at": s} for v, b, s in rows]


class MemoryAgentStore(MemoryTicketStore):
    def __init__(self, tenants: dict | None = None):
        super().__init__()
        self.tenants = tenants or {}
        self.sent: dict[tuple[str, int], dict] = {}
        self.keys: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def create_idempotent(
        self,
        tenant_id,
        channel,
        body,
        sender_name=None,
        sender_email=None,
        sender_phone=None,
        idempotency_key=None,
    ):
        with self._lock:
            if idempotency_key and (tenant_id, idempotency_key) in self.keys:
                return self.keys[(tenant_id, idempotency_key)], False
            tid = self.create(tenant_id, channel, body, sender_name, sender_email, sender_phone)
            if idempotency_key:
                self.keys[(tenant_id, idempotency_key)] = tid
            return tid, True

    def masked(self, ticket_id):
        t = self.tickets.get(ticket_id)
        if not t:
            return None
        return {
            "id": ticket_id,
            "tenant_id": t["tenant_id"],
            "status": t["status"],
            "subject": "",
            "body": t["masked_body"],
            "ticket_ref": t.get("ticket_ref"),
            "created_at": None,
        }

    def tenant(self, tenant_id):
        return self.tenants.get(tenant_id)

    def save_progress(self, ticket_id, **fields):
        self.tickets[ticket_id].update(fields)

    def insert_reply(self, ticket_id, draft_version, body, channel):
        with self._lock:
            if (ticket_id, draft_version) in self.sent:
                return False
            self.sent[(ticket_id, draft_version)] = {"body": body, "channel": channel}
            return True

    def replies(self, ticket_id):
        return [
            {"draft_version": v, "body": r["body"], "sent_at": None}
            for (t, v), r in sorted(self.sent.items())
            if t == ticket_id
        ]
