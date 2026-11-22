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
                                         ticket_ref, created_at, conversation_id FROM tickets WHERE id = %s""",
                (ticket_id,),
            ).fetchone()
        if not row:
            return None
        keys = ("id", "tenant_id", "status", "subject", "body", "ticket_ref", "created_at",  # created_at -> dedupe
                "conversation_id")
        return dict(zip(keys, row, strict=True))

    def tenant(self, tenant_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT row_to_json(t) FROM tenants t WHERE tenant_id = %s", (tenant_id,)
            ).fetchone()
        return row[0] if row else None

    def save_progress(self, ticket_id: str, **fields) -> None:
        allowed = {"agent_status", "route", "route_reason", "classification", "team", "language",
                   "duplicate_of_ref", "jira_key", "incident_id", "conversation_id", "route_rule", "answer_tier"}
        fields = {
            k: (json.dumps(v) if k == "classification" else v) for k, v in fields.items() if k in allowed
        }
        if not fields:
            return
        sets = ", ".join(f"{k} = %s" for k in fields)
        with self._conn() as conn:
            conn.execute(f"UPDATE tickets SET {sets} WHERE id = %s", (*fields.values(), ticket_id))

    def conversation(self, conversation_id: str, ticket_id: str, limit: int = 4) -> list[dict]:
        """Earlier turns of this chat (masked), oldest first: the question, its route and our last reply."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT t.id::text, coalesce(t.masked_body, ''), t.route,
                          (SELECT body_masked FROM sent_replies s WHERE s.ticket_id = t.id
                            ORDER BY draft_version DESC LIMIT 1), t.tenant_id, t.team
                   FROM tickets t
                   WHERE t.conversation_id = %s AND t.id <> %s AND t.status = 'masked'
                     AND t.created_at <= (SELECT created_at FROM tickets WHERE id = %s)
                   ORDER BY t.created_at DESC LIMIT %s""",
                (conversation_id, ticket_id, ticket_id, limit)).fetchall()
        return [{"ticket_id": i, "text": b, "route": r, "reply": rep, "tenant_id": tn, "team": tm}
                for i, b, r, rep, tn, tm in reversed(rows)]

    # ---- phase 7: recent tickets, incidents, Jira ------------------------------------
    def recent_tickets(self, tenant_id, created_at, exclude_id, hours: int = 72):
        from agent.dedupe import Recent

        with self._conn() as conn:
            rows = conn.execute("""SELECT id::text, ticket_ref, created_at, coalesce(subject_masked, '') || ' ' ||
                                          coalesce(masked_body, ''), incident_id::text, duplicate_of_ref
                                   FROM tickets WHERE tenant_id = %s AND id <> %s AND status = 'masked'
                                     AND created_at BETWEEN %s - make_interval(hours => %s) AND %s
                                   ORDER BY created_at DESC LIMIT 500""",
                                (tenant_id, exclude_id, created_at, hours, created_at)).fetchall()
        return [Recent(*r) for r in rows]

    def open_incidents(self, tenant_id):
        with self._conn() as conn:
            rows = conn.execute("""SELECT id::text, signature, opened_at FROM incidents
                                   WHERE tenant_id = %s AND status = 'open'""", (tenant_id,)).fetchall()
        return [{"id": i, "signature": s, "opened_at": o} for i, s, o in rows]

    def open_incident(self, incident_id, tenant_id, team, signature, opened_at, member_ids):
        with self._conn() as conn, conn.transaction():
            conn.execute("""INSERT INTO incidents (id, tenant_id, team, signature, opened_at, ticket_count)
                            VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                         (incident_id, tenant_id, team, signature, opened_at, len(member_ids)))
            conn.execute("UPDATE tickets SET incident_id = %s WHERE id = ANY(%s::uuid[])", (incident_id, member_ids))

    def attach_incident(self, ticket_id, incident_id):
        with self._conn() as conn:
            conn.execute("UPDATE tickets SET incident_id = %s WHERE id = %s", (incident_id, ticket_id))
            conn.execute("UPDATE incidents SET ticket_count = (SELECT count(*) FROM tickets WHERE incident_id = %s) "
                         "WHERE id = %s", (incident_id, incident_id))

    def open_jira(self, tenant_id):
        with self._conn() as conn:
            rows = conn.execute("""SELECT key, summary_masked, resolution_note_masked FROM jira_issues
                                   WHERE %s = ANY(customer_ids)""", (tenant_id,)).fetchall()
        return [{"key": k, "summary": s or "", "resolution_note": r or ""} for k, s, r in rows]

    # ---- review (minimal console) -----------------------------------------------------
    def create_review(self, ticket_id, draft_version, draft, reason, kind="reply", kb_ids=None):
        tid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"review:{ticket_id}:{draft_version}:{kind}"))
        with self._conn() as conn:
            conn.execute("""INSERT INTO review_tasks (id, ticket_id, draft, route_reason, sources, kind)
                            VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
                         (tid, ticket_id, draft, reason, json.dumps(kb_ids or []), kind))
        return tid

    def list_reviews(self, status="open"):
        with self._conn() as conn:
            rows = conn.execute("""SELECT r.id::text, r.ticket_id::text, r.draft, r.route_reason, r.created_at,
                                          t.tenant_id, t.team, t.language, t.masked_body, r.kind
                                   FROM review_tasks r JOIN tickets t ON t.id = r.ticket_id
                                   WHERE r.status = %s ORDER BY r.created_at""", (status,)).fetchall()
        keys = ("id", "ticket_id", "draft", "route_reason", "created_at", "tenant_id", "team", "language", "body",
                "kind")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def decide_review(self, task_id, decision, body=None, reviewer=None):
        with self._conn() as conn, conn.transaction():
            kind = conn.execute("SELECT kind FROM review_tasks WHERE id = %s AND status = 'open'",
                                (task_id,)).fetchone()
            if kind is None:
                return None
            if decision == "approve" and kind[0] == "knowledge" and not (body or "").strip():
                raise ValueError("write the answer before approving")
            row = conn.execute("""UPDATE review_tasks SET status = %s, decision = %s, assignee = %s,
                                         draft = coalesce(%s, draft), decided_at = now()
                                  WHERE id = %s AND status = 'open' RETURNING ticket_id::text, draft, sources""",
                               ("approved" if decision == "approve" else "rejected", decision, reviewer, body,
                                task_id)).fetchone()
            if row is None:
                return None
            ticket_id, draft, sources = row
            if decision == "approve" and kind[0] == "knowledge":
                # the approved answer joins the How-To library: every similar question gets it from now on
                conn.execute(
                    """INSERT INTO howto_answers (id, region, language, question, answer, kb_ids, source, approved_by,
                                                 ticket_id)
                       SELECT %s, tn.region, coalesce(t.language, 'en'), coalesce(t.masked_body, ''), %s, %s,
                              'agent_approved', %s, t.id
                       FROM tickets t LEFT JOIN tenants tn ON tn.tenant_id = t.tenant_id WHERE t.id = %s
                       ON CONFLICT (id) DO NOTHING""",
                    (str(uuid.uuid5(uuid.NAMESPACE_URL, f"howto:{task_id}")), draft,
                     [k for k in (sources or []) if isinstance(k, str)], reviewer, ticket_id))
            if decision == "approve":
                version = conn.execute("SELECT coalesce(max(draft_version), 0) + 1 FROM sent_replies WHERE ticket_id = %s",
                                       (ticket_id,)).fetchone()[0]
                conn.execute("INSERT INTO sent_replies (ticket_id, draft_version, body_masked, channel) "
                             "VALUES (%s, %s, %s, 'chat') ON CONFLICT DO NOTHING", (ticket_id, version, draft))
            conn.execute("UPDATE tickets SET agent_status = %s WHERE id = %s",
                         ("replied" if decision == "approve" else "taken_over", ticket_id))
        return ticket_id

    # ---- operations dashboard -----------------------------------------------------------
    def dashboard_data(self, scope: str = "live", days: int = 7) -> dict:
        """Raw rows for agent.dashboard.summarize: masked fields only, capped at 5,000 tickets."""
        with self._conn() as conn:
            if scope == "export":
                where, params = "t.origin = 'export'", ()
            else:
                where, params = "t.origin = 'live' AND t.created_at >= now() - make_interval(days => %s)", (days,)
            rows = conn.execute(
                f"""SELECT t.id::text, coalesce(t.ticket_ref, left(t.id::text, 8)), t.created_at, t.tenant_id,
                           t.team, t.initial_team, t.route, t.route_rule, t.route_reason, t.answer_tier,
                           t.agent_status, t.language, t.classification, t.duplicate_of_ref,
                           t.incident_id::text, t.jira_key, t.reassign_count, t.kb_ids, t.channel, t.status
                    FROM tickets t WHERE {where} ORDER BY t.created_at DESC LIMIT 5000""", params).fetchall()
            keys = ("id", "ref", "created_at", "tenant_id", "team", "initial_team", "route", "route_rule",
                    "route_reason", "answer_tier", "agent_status", "language", "classification", "duplicate_of",
                    "incident_id", "jira_key", "reassign_count", "kb_ids", "channel", "status")
            tickets = [dict(zip(keys, r, strict=True)) for r in rows]
            incidents = [dict(zip(("id", "tenant_id", "team", "signature", "opened_at", "ticket_count", "status",
                                   "jira_key"), r, strict=True)) for r in conn.execute(
                """SELECT id::text, tenant_id, team, left(signature, 120), opened_at, ticket_count, status, jira_key
                   FROM incidents ORDER BY opened_at DESC LIMIT 50""").fetchall()]
            reviews = dict(conn.execute("""SELECT kind || ':' || status, count(*) FROM review_tasks
                                           GROUP BY kind, status""").fetchall())
            library = conn.execute("SELECT count(*) FROM howto_answers WHERE active").fetchone()[0]
        return {"tickets": tickets, "incidents": incidents, "reviews": reviews, "library_size": library}

    # ---- phase B: knowledge import ---------------------------------------------------------
    def import_articles(self, articles, imported_by=None) -> list[dict]:
        """Replace each article's chunks (one transaction per upload); add a title row if the KB lacks one."""
        out = []
        with self._conn() as conn, conn.transaction():
            for a in articles:
                conn.execute("DELETE FROM kb_chunks WHERE kb_id = %s AND source_kind = 'kb_article'", (a.kb_id,))
                had_title = conn.execute("SELECT 1 FROM kb_chunks WHERE chunk_id = %s",
                                         (f"{a.kb_id}#title",)).fetchone() is not None
                if not had_title:
                    conn.execute("""INSERT INTO kb_chunks (chunk_id, kb_id, source_kind, region, topic, language,
                                                           title, content, last_reviewed)
                                    VALUES (%s, %s, 'kb_title', %s, %s, %s, %s, %s, current_date)""",
                                 (f"{a.kb_id}#title", a.kb_id, a.region, a.topic, a.language, a.title,
                                  f"{a.kb_id}: {a.title}"))
                for i, text in enumerate(a.chunks, start=1):
                    conn.execute("""INSERT INTO kb_chunks (chunk_id, kb_id, source_kind, region, topic, language,
                                                           title, content, effective_from, last_reviewed)
                                    VALUES (%s, %s, 'kb_article', %s, %s, %s, %s, %s, NULL, current_date)""",
                                 (f"{a.kb_id}#article{i}", a.kb_id, a.region, a.topic, a.language, a.title, text))
                conn.execute("""INSERT INTO knowledge_imports (kb_id, title, region, language, topic, chunks,
                                                               masked_counts, created_title, imported_by)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (kb_id) DO UPDATE SET title = EXCLUDED.title, region = EXCLUDED.region,
                                  language = EXCLUDED.language, topic = EXCLUDED.topic, chunks = EXCLUDED.chunks,
                                  masked_counts = EXCLUDED.masked_counts, active = true,
                                  created_title = knowledge_imports.created_title OR EXCLUDED.created_title,
                                  imported_by = EXCLUDED.imported_by, imported_at = now()""",
                             (a.kb_id, a.title, a.region, a.language, a.topic, len(a.chunks),
                              json.dumps(a.masked_counts), not had_title, imported_by))
                out.append({"kb_id": a.kb_id, "title": a.title, "chunks": len(a.chunks), "topic": a.topic,
                            "masked": sum(a.masked_counts.values()), "new_title": not had_title})
        return out

    def withdraw_article(self, kb_id) -> bool:
        with self._conn() as conn, conn.transaction():
            row = conn.execute("""UPDATE knowledge_imports SET active = false, imported_at = now()
                                  WHERE kb_id = %s AND active RETURNING created_title""", (kb_id,)).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM kb_chunks WHERE kb_id = %s AND source_kind = 'kb_article'", (kb_id,))
            if row[0]:
                conn.execute("DELETE FROM kb_chunks WHERE chunk_id = %s", (f"{kb_id}#title",))
        return True

    def list_imports(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute("""SELECT kb_id, title, region, language, topic, chunks, masked_counts, imported_at
                                   FROM knowledge_imports WHERE active ORDER BY imported_at DESC""").fetchall()
            lib = conn.execute("SELECT source, count(*) FROM howto_answers WHERE active GROUP BY source").fetchall()
        keys = ("kb_id", "title", "region", "language", "topic", "chunks", "masked_counts", "imported_at")
        return {"articles": [dict(zip(keys, r, strict=True)) for r in rows], "library": dict(lib)}

    def import_answers(self, rows, imported_by=None) -> int:
        with self._conn() as conn, conn.transaction():
            for r in rows:
                conn.execute("""INSERT INTO howto_answers (id, region, language, question, answer, kb_ids, source,
                                                           approved_by)
                                VALUES (%s, %s, %s, %s, %s, %s, 'imported', %s) ON CONFLICT (id) DO UPDATE
                                SET answer = EXCLUDED.answer, active = true""",
                             (str(uuid.uuid5(uuid.NAMESPACE_URL, f"howto-import:{r['language']}:{r['question']}")),
                              r["region"], r["language"], r["question"], r["answer"], r["kb_ids"], imported_by))
        return len(rows)

    def knowledge_stamp(self) -> str:
        """Changes whenever an article is imported or withdrawn: the worker reloads its retriever then."""
        with self._conn() as conn:
            n, last = conn.execute("""SELECT (SELECT count(*) FROM kb_chunks),
                                             (SELECT max(imported_at) FROM knowledge_imports)""").fetchone()
        return f"{n}|{last}"

    def howto_answers(self, region, language) -> list[dict]:
        """Approved How-To answers for this region (or all regions) and language."""
        with self._conn() as conn:
            rows = conn.execute("""SELECT id::text, question, answer, kb_ids, region FROM howto_answers
                                   WHERE active AND language = %s AND (region IS NULL OR region = %s)
                                   ORDER BY created_at DESC LIMIT 1000""", (language, region)).fetchall()
        return [{"id": i, "question": q, "answer": a, "kb_ids": list(k or []), "region": r} for i, q, a, k, r in rows]

    def resolved_examples(self) -> list[dict]:
        """Past tickets where an agent recorded the KB article that solved it (masked question -> article)."""
        with self._conn() as conn:
            rows = conn.execute("""SELECT t.masked_body, t.kb_ids, tn.region FROM tickets t
                                   LEFT JOIN tenants tn ON tn.tenant_id = t.tenant_id
                                   WHERE cardinality(t.kb_ids) > 0 AND t.masked_body IS NOT NULL""").fetchall()
        return [{"question": q, "kb_id": k[0], "region": r} for q, k, r in rows if k]

    def knowledge(self) -> tuple[list[dict], list[dict]]:
        """(kb_chunks, statutory_rules) for the retriever; loaded once at worker start."""
        with self._conn() as conn:
            chunks = [r[0] for r in conn.execute(
                """SELECT json_build_object('chunk_id', chunk_id, 'kb_id', kb_id, 'source_kind', source_kind,
                          'region', region, 'topic', topic, 'language', language, 'title', title,
                          'content', content, 'effective_from', effective_from, 'effective_to', effective_to,
                          'superseded_by', superseded_by) FROM kb_chunks""").fetchall()]
            rules = [r[0] for r in conn.execute(
                """SELECT json_build_object('rule_id', rule_id, 'region', region, 'topic', topic, 'title', title,
                          'effective_from', effective_from, 'old_value', old_value, 'new_value', new_value,
                          'affects_kb_topics', affects_kb_topics, 'source', source) FROM statutory_rules""").fetchall()]
        return chunks, rules

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
            "conversation_id": t.get("conversation_id"),
        }

    def conversation(self, conversation_id, ticket_id, limit=4):
        order = list(self.tickets)
        upto = order[: order.index(ticket_id)] if ticket_id in order else order
        turns = [
            {"ticket_id": i, "text": self.tickets[i].get("masked_body") or "", "route": self.tickets[i].get("route"),
             "tenant_id": self.tickets[i].get("tenant_id"), "team": self.tickets[i].get("team"),
             "reply": next((r["body"] for (t, _v), r in sorted(self.sent.items(), reverse=True) if t == i), None)}
            for i in upto
            if self.tickets[i].get("conversation_id") == conversation_id and self.tickets[i].get("status") == "masked"
        ]
        return turns[-limit:]

    def tenant(self, tenant_id):
        return self.tenants.get(tenant_id)

    # phase 7 (memory): tickets need "created_at" set by the test
    incidents: dict = None
    jira: list = None

    def recent_tickets(self, tenant_id, created_at, exclude_id, hours=72):
        from agent.dedupe import Recent

        out = []
        for tid, t in self.tickets.items():
            c = t.get("created_at")
            if tid != exclude_id and t["tenant_id"] == tenant_id and t["status"] == "masked" and c and c <= created_at:
                out.append(Recent(tid, t.get("ticket_ref"), c, t["masked_body"] or "", t.get("incident_id"),
                                  t.get("duplicate_of_ref")))
        return out

    def open_incidents(self, tenant_id):
        return [i for i in (self.incidents or {}).values() if i["tenant_id"] == tenant_id]

    def open_incident(self, incident_id, tenant_id, team, signature, opened_at, member_ids):
        self.incidents = self.incidents or {}
        self.incidents[incident_id] = {"id": incident_id, "tenant_id": tenant_id, "signature": signature,
                                       "opened_at": opened_at}
        for m in member_ids:
            self.tickets[m]["incident_id"] = incident_id

    def attach_incident(self, ticket_id, incident_id):
        self.tickets[ticket_id]["incident_id"] = incident_id

    def open_jira(self, tenant_id):
        return [j for j in (self.jira or []) if tenant_id in j.get("customer_ids", [tenant_id])]

    reviews: dict = None

    library: list = None
    examples: list = None

    def create_review(self, ticket_id, draft_version, draft, reason, kind="reply", kb_ids=None):
        self.reviews = self.reviews or {}
        rid = f"{ticket_id}:{draft_version}:{kind}"
        self.reviews.setdefault(rid, {"id": rid, "ticket_id": ticket_id, "draft": draft, "route_reason": reason,
                                      "status": "open", "kind": kind, "kb_ids": kb_ids or []})
        return rid

    def howto_answers(self, region, language):
        return [a for a in (self.library or []) if a["language"] == language and a.get("region") in (None, region)]

    kb: list = None
    imports: dict = None

    def import_articles(self, articles, imported_by=None):
        self.kb, self.imports = self.kb or [], self.imports or {}
        out = []
        for a in articles:
            self.kb = [c for c in self.kb if not (c["kb_id"] == a.kb_id and c["source_kind"] == "kb_article")]
            had = any(c["chunk_id"] == f"{a.kb_id}#title" for c in self.kb)
            if not had:
                self.kb.append({"chunk_id": f"{a.kb_id}#title", "kb_id": a.kb_id, "source_kind": "kb_title",
                                "region": a.region, "topic": a.topic, "title": a.title,
                                "content": f"{a.kb_id}: {a.title}"})
            self.kb += [{"chunk_id": f"{a.kb_id}#article{i}", "kb_id": a.kb_id, "source_kind": "kb_article",
                         "region": a.region, "topic": a.topic, "title": a.title, "content": t}
                        for i, t in enumerate(a.chunks, start=1)]
            self.imports[a.kb_id] = {"created_title": not had, "title": a.title, "chunks": len(a.chunks)}
            out.append({"kb_id": a.kb_id, "title": a.title, "chunks": len(a.chunks), "topic": a.topic,
                        "masked": sum(a.masked_counts.values()), "new_title": not had})
        return out

    def withdraw_article(self, kb_id):
        imp = (self.imports or {}).pop(kb_id, None)
        if imp is None:
            return False
        self.kb = [c for c in self.kb if not (c["kb_id"] == kb_id and (c["source_kind"] == "kb_article" or
                                                                          imp["created_title"]))]
        return True

    def knowledge_stamp(self):
        return f"{len(self.kb or [])}|{sorted((self.imports or {}).items())}"

    def knowledge(self):
        return list(self.kb or []), list(getattr(self, "rules", None) or [])

    def list_imports(self):
        return {"articles": [{"kb_id": k, **v} for k, v in (self.imports or {}).items()],
                "library": {"imported": len(self.library or [])}}

    def import_answers(self, rows, imported_by=None):
        self.library = self.library or []
        self.library += [{"id": f"imp-{len(self.library) + i}", **r} for i, r in enumerate(rows)]
        return len(rows)

    def dashboard_data(self, scope="live", days=7):
        tickets = [{"id": i, "ref": t.get("ticket_ref") or i[:8], "created_at": t.get("created_at"),
                    "tenant_id": t.get("tenant_id"), "team": t.get("team"), "initial_team": t.get("initial_team"),
                    "route": t.get("route"), "route_rule": t.get("route_rule"), "route_reason": t.get("route_reason"),
                    "answer_tier": t.get("answer_tier"), "agent_status": t.get("agent_status"),
                    "language": t.get("language"), "classification": t.get("classification"),
                    "duplicate_of": t.get("duplicate_of_ref"), "incident_id": t.get("incident_id"),
                    "jira_key": t.get("jira_key"), "reassign_count": t.get("reassign_count"),
                    "kb_ids": t.get("kb_ids") or [], "channel": t.get("channel"), "status": t.get("status")}
                   for i, t in self.tickets.items() if (t.get("origin") or "live") == scope]
        reviews = {}
        for r in (self.reviews or {}).values():
            k = f"{r.get('kind', 'reply')}:{r['status']}"
            reviews[k] = reviews.get(k, 0) + 1
        incidents = [{**v, "team": v.get("team"), "status": "open", "jira_key": None,
                      "ticket_count": sum(1 for t in self.tickets.values() if t.get("incident_id") == i)}
                     for i, v in (self.incidents or {}).items()]
        return {"tickets": tickets, "incidents": incidents, "reviews": reviews, "library_size": len(self.library or [])}

    def resolved_examples(self):
        return list(self.examples or [])

    def list_reviews(self, status="open"):
        return [dict(r, body=self.tickets[r["ticket_id"]]["masked_body"]) for r in (self.reviews or {}).values()
                if r["status"] == status]

    def decide_review(self, task_id, decision, body=None, reviewer=None):
        r = (self.reviews or {}).get(task_id)
        if not r or r["status"] != "open":
            return None
        if decision == "approve" and r.get("kind") == "knowledge":
            if not (body or "").strip():
                raise ValueError("write the answer before approving")
            t = self.tickets[r["ticket_id"]]
            self.library = self.library or []
            self.library.append({"id": f"lib-{len(self.library) + 1}", "question": t.get("masked_body") or "",
                                 "answer": body, "kb_ids": r.get("kb_ids") or [], "language": t.get("language") or "en",
                                 "region": (self.tenants.get(t["tenant_id"]) or {}).get("region")})
        r["status"] = "approved" if decision == "approve" else "rejected"
        if decision == "approve":
            n = len(self.replies(r["ticket_id"])) + 1
            self.insert_reply(r["ticket_id"], n, body or r["draft"], "chat")
        self.tickets[r["ticket_id"]]["agent_status"] = "replied" if decision == "approve" else "taken_over"
        return r["ticket_id"]

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
