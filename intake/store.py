"""Ticket storage: Postgres in every environment, plus an in-memory store for tests.

Only two methods ever see raw text: create() (the API writes the inbox row) and
load_inbox() (the worker reads it to mask). get() returns masked fields only.
"""
import json
import uuid
from dataclasses import dataclass, field


@dataclass
class Inbox:
    ticket_id: str
    tenant_id: str
    body: str
    sender_name: str | None = None
    sender_email: str | None = None
    sender_phone: str | None = None


PUBLIC_FIELDS = ("id", "tenant_id", "channel", "status", "masked_body", "pii_counts",
                 "pii_block_reasons", "ner_layer", "created_at", "masked_at")


class PgTicketStore:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _conn(self):
        import psycopg

        return psycopg.connect(self.dsn, connect_timeout=5)

    def create(self, tenant_id: str, channel: str, body: str, sender_name=None, sender_email=None,
               sender_phone=None) -> str:
        ticket_id = str(uuid.uuid4())
        with self._conn() as conn, conn.transaction():
            conn.execute("INSERT INTO tickets (id, tenant_id, channel) VALUES (%s, %s, %s)",
                         (ticket_id, tenant_id, channel))
            conn.execute("""INSERT INTO ticket_inbox
                                (ticket_id, body, sender_name, sender_email, sender_phone)
                            VALUES (%s, %s, %s, %s, %s)""",
                         (ticket_id, body, sender_name, sender_email, sender_phone))
        return ticket_id

    def delete(self, ticket_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM tickets WHERE id = %s", (ticket_id,))

    def load_inbox(self, ticket_id: str) -> Inbox | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT t.id::text, t.tenant_id, i.body, i.sender_name, i.sender_email, i.sender_phone
                   FROM ticket_inbox i JOIN tickets t ON t.id = i.ticket_id
                   WHERE i.ticket_id = %s AND t.status = 'received'""", (ticket_id,)).fetchone()
        return Inbox(*row) if row else None

    def save_masked(self, ticket_id: str, masked_body: str, counts: dict, email_token, phone_token,
                    ner_layer: str) -> None:
        with self._conn() as conn, conn.transaction():
            conn.execute("""UPDATE tickets SET status = 'masked', masked_body = %s, pii_counts = %s,
                                   sender_email_token = %s, sender_phone_token = %s, ner_layer = %s,
                                   masked_at = now()
                            WHERE id = %s""",
                         (masked_body, json.dumps(counts), email_token, phone_token, ner_layer, ticket_id))
            conn.execute("DELETE FROM ticket_inbox WHERE ticket_id = %s", (ticket_id,))

    def save_blocked(self, ticket_id: str, counts: dict, reasons: list[str], ner_layer: str) -> None:
        with self._conn() as conn:
            conn.execute("""UPDATE tickets SET status = 'pii_blocked', pii_counts = %s,
                                   pii_block_reasons = %s, ner_layer = %s
                            WHERE id = %s""", (json.dumps(counts), reasons, ner_layer, ticket_id))

    def get(self, ticket_id: str) -> dict | None:
        with self._conn() as conn:
            cur = conn.execute(f"SELECT id::text, {', '.join(PUBLIC_FIELDS[1:])} FROM tickets WHERE id = %s",
                               (ticket_id,))
            row = cur.fetchone()
        return dict(zip(PUBLIC_FIELDS, row, strict=True)) if row else None


@dataclass
class MemoryTicketStore:
    tickets: dict = field(default_factory=dict)
    inbox: dict = field(default_factory=dict)

    def create(self, tenant_id, channel, body, sender_name=None, sender_email=None, sender_phone=None) -> str:
        ticket_id = str(uuid.uuid4())
        self.tickets[ticket_id] = {"id": ticket_id, "tenant_id": tenant_id, "channel": channel,
                                   "status": "received", "masked_body": None, "pii_counts": {},
                                   "pii_block_reasons": [], "ner_layer": None, "created_at": None,
                                   "masked_at": None, "sender_email_token": None, "sender_phone_token": None}
        self.inbox[ticket_id] = Inbox(ticket_id, tenant_id, body, sender_name, sender_email, sender_phone)
        return ticket_id

    def delete(self, ticket_id):
        self.tickets.pop(ticket_id, None)
        self.inbox.pop(ticket_id, None)

    def load_inbox(self, ticket_id):
        t = self.tickets.get(ticket_id)
        return self.inbox.get(ticket_id) if t and t["status"] == "received" else None

    def save_masked(self, ticket_id, masked_body, counts, email_token, phone_token, ner_layer):
        self.tickets[ticket_id].update(status="masked", masked_body=masked_body, pii_counts=counts,
                                       sender_email_token=email_token, sender_phone_token=phone_token,
                                       ner_layer=ner_layer, masked_at="now")
        self.inbox.pop(ticket_id, None)

    def save_blocked(self, ticket_id, counts, reasons, ner_layer):
        self.tickets[ticket_id].update(status="pii_blocked", pii_counts=counts,
                                       pii_block_reasons=reasons, ner_layer=ner_layer)

    def get(self, ticket_id):
        t = self.tickets.get(ticket_id)
        return {k: t[k] for k in PUBLIC_FIELDS} if t else None
