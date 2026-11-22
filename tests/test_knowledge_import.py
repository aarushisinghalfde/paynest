"""Phase B: uploaded articles and answers become How-To knowledge in the database."""

from datetime import UTC, datetime

import pytest

from agent import knowledge_import as ki
from agent.nodes import Deps
from agent.retrieval import Retriever
from agent.runner import MemoryCheckpoints, run
from agent.store import MemoryAgentStore
from agent.unmask import customer_view
from intake.vault import MemoryVault
from tests.test_drafting import CHUNKS, PAYSLIP, RULES, TENANTS

ARTICLE = """---
id: KB-0105
title: Downloading payslips in bulk
region: ALL
---
# Downloading payslips in bulk

1. Open Payroll > Payslips.
2. Pick the payroll month.
3. Select all employees and choose Download as ZIP.

Questions? Write to payroll.help@example.com or call +91 98765 43210.
"""


def test_parse_masks_pii_and_keeps_the_steps():
    a = ki.parse_article("anything.md", ARTICLE)
    assert (a.kb_id, a.title, a.region, a.topic) == ("KB-0105", "Downloading payslips in bulk", "ALL", "howto")
    text = "\n".join(a.chunks)
    assert "Download as ZIP" in text and "example.com" not in text and "98765" not in text
    assert "[email removed]" in text and "<EMAIL" not in text
    assert a.masked_counts.get("EMAIL") == 1 and "# Downloading payslips in bulk" not in text


def test_id_from_file_name_html_and_validation():
    a = ki.parse_article("KB-0301 Leave carry forward.html", "<h1>Leave carry forward</h1><p>Go to Leave &gt; Policies.</p>")
    assert a.kb_id == "KB-0301" and a.title == "Leave carry forward" and "Leave > Policies" in a.chunks[0]
    with pytest.raises(ValueError, match="no valid article id"):
        ki.parse_article("notes.md", "# Something\n\ntext")
    with pytest.raises(ValueError, match="region"):
        ki.parse_article("KB-0001.md", "---\nregion: EU\n---\ntext")


def test_statutory_articles_are_tagged_and_never_used_for_auto_howto():
    a = ki.parse_article("KB-0900.md", "# PF ceiling changes\n\nFrom August the EPF wage ceiling is INR 25,000.")
    assert a.topic == "statutory:pf_wage_ceiling"
    store = MemoryAgentStore(TENANTS)
    store.import_articles([a])
    chunks, _ = store.knowledge()
    r = Retriever([*CHUNKS, *chunks], RULES)
    from datetime import date

    assert not [h for h in r.howto_articles("PF ceiling changes", "IN", date(2026, 9, 1)) if h["kb_id"] == "KB-0900"]


def test_long_articles_are_split_into_parts():
    body = "\n\n".join(f"Step {i}: " + "do the thing carefully. " * 12 for i in range(12))
    parts = ki.chunk(body)
    assert len(parts) > 1 and all(len(p) <= ki.CHUNK for p in parts)


def _ask(store, text, cid):
    chunks, _ = store.knowledge()
    deps = Deps(store, MemoryVault(), b"k", retriever=Retriever([*CHUNKS, PAYSLIP, *chunks], RULES))
    tid = store.create("C-1001", "chat", text, None)
    store.save_progress(tid, conversation_id=cid, created_at=datetime.now(UTC))
    return tid, run(tid, deps, MemoryCheckpoints())


def test_after_import_the_agent_answers_with_the_steps_and_learns_nothing_new():
    store = MemoryAgentStore(TENANTS)
    store.import_articles([ki.parse_article("x.md", ARTICLE)])
    tid, st = _ask(store, "How do I download payslips for all employees?", "conv-k0000001")
    reply = customer_view(store.replies(tid)[0]["body"])
    assert st["guard"]["ok"] and st["sent"] and "Download as ZIP" in reply and "KB-0105" in reply
    assert not st.get("learn_kb") and not [t for t in store.list_reviews() if t["kind"] == "knowledge"]


def test_withdraw_removes_the_steps_again():
    store = MemoryAgentStore(TENANTS)
    store.import_articles([ki.parse_article("x.md", ARTICLE)])
    assert store.withdraw_article("KB-0105") and not store.withdraw_article("KB-0105")
    tid, _ = _ask(store, "How do I download payslips for all employees?", "conv-k0000002")
    assert "Download as ZIP" not in store.replies(tid)[0]["body"]


def test_answers_csv_goes_into_the_library_masked():
    rows = ki.parse_answers_csv(
        "question,answer,language,region,kb_ids\n"
        "How do I reset an employee password?,Go to Settings > Users and click Reset. Mail help@example.com.,en,ALL,KB-0110\n")
    assert rows[0]["region"] is None and rows[0]["kb_ids"] == ["KB-0110"] and "example.com" not in rows[0]["answer"]
    store = MemoryAgentStore(TENANTS)
    store.import_answers(rows)
    tid, st = _ask(store, "how can I reset a password for an employee", "conv-k0000003")
    assert st["draft_mode"] == "library" and "click Reset" in store.replies(tid)[0]["body"]
    with pytest.raises(ValueError, match="line 2"):
        ki.parse_answers_csv("question,answer\nonly a question,\n")


def test_worker_reloads_knowledge_when_the_database_changes():
    from worker.main import knowledge_reloader

    store = MemoryAgentStore(TENANTS)
    deps = Deps(store, MemoryVault(), b"k", retriever=Retriever([], RULES))
    now = {"t": 0.0}
    reload = knowledge_reloader(deps, store, every=60, clock=lambda: now["t"])
    v0 = deps.retriever.version
    store.import_articles([ki.parse_article("x.md", ARTICLE)])
    reload()
    assert deps.retriever.version == v0  # checked at most once a minute
    now["t"] = 61
    reload()
    assert deps.retriever.version != v0 and any(c["kb_id"] == "KB-0105" for c in deps.retriever.chunks)
