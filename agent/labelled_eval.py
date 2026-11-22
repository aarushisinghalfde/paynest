"""Plan v2 phase C: the agent graph on the 200-ticket labelled set (scripts/run_evals.py).

Production-like and leak-free: the similar-tickets index and the past-resolution examples are built
from the Q3 tickets that are NOT in the labelled set, exactly as the worker builds them from RDS
(the worker also holds the eval set out, see classifier.similar_from_db).
"""

import time
import uuid
from collections import Counter

from agent import guard, metrics
from agent.classifier import TEAM_LIST, Classifier, SimilarTickets
from agent.nodes import Deps
from agent.retrieval import Retriever
from agent.runner import MemoryCheckpoints, run
from agent.store import MemoryAgentStore
from agent.unmask import customer_view
from intake.vault import MemoryVault
from loader import labelled
from loader.build import build

GATE_OVERALL, GATE_LANGUAGE, GATE_GUARD = 0.90, 0.85, 0.95
SENT_TIERS = ("library", "cache", "model", "fallback")


def build_dataset(raw: dict[str, str]):
    return build(raw, MemoryVault(), b"eval-only-key", "ap-southeast-2", int(time.time()))


def _deps(ds, held_out: set[str]):
    tickets = [t for t in ds.tables["tickets"] if t["ticket_ref"] not in held_out]
    train = [t for t in tickets if t["status"] == "masked" and t["team"] and not t["duplicate_of_ref"]]
    sim = SimilarTickets().fit([f"{t['subject_masked'] or ''} {t['masked_body'] or ''}" for t in train],
                               [t["team"] for t in train])
    regions = {t["tenant_id"]: t["region"] for t in ds.tables["tenants"]}
    examples = [{"question": t["masked_body"], "kb_id": t["kb_ids"][0], "region": regions.get(t["tenant_id"])}
                for t in tickets if t.get("kb_ids") and t.get("masked_body")]
    chunks, rules = ds.tables["kb_chunks"], ds.tables["statutory_rules"]  # what store.knowledge() reads from RDS
    store = MemoryAgentStore({t["tenant_id"]: dict(t) for t in ds.tables["tenants"]})
    deps = Deps(store, MemoryVault(), b"eval-only-key", classifier=Classifier(sim, None),
                retriever=Retriever(chunks, rules, examples=examples))
    return store, deps


def evaluate(ds, n: int = 200) -> dict:
    chosen = labelled.stratified(ds.tables["tickets"], n=n)
    store, deps = _deps(ds, {t["ticket_ref"] for t in chosen})
    rows = []
    for t in chosen:
        text = f"{t['subject_masked'] or ''}. {t['masked_body'] or ''}".strip(". ")
        tid = store.create(t["tenant_id"], "chat", text, None)
        store.save_progress(tid, conversation_id=f"eval-{uuid.uuid4().hex[:12]}", created_at=t["created_at"])
        st = run(tid, deps, MemoryCheckpoints())
        sent = " ".join(r["body"] for r in store.replies(tid))
        rows.append({"ref": t["ticket_ref"], "language": t["language"], "gold": t["team"],
                     "customer_pick": t["initial_team"], "pred": st.get("team"),
                     "branch": (st.get("classification") or {}).get("branch"), "route": st.get("route"),
                     "rule": st.get("route_rule"), "tier": st.get("draft_mode"), "sent": bool(st.get("sent")),
                     "guard_ok": (st.get("guard") or {}).get("ok"), "guard_problems": (st.get("guard") or {}).get("problems"),
                     "sent_text": sent, "masked": text})
    return summarize(rows)


def summarize(rows: list[dict]) -> dict:
    gold = [r["gold"] for r in rows]
    pred = [r["pred"] or "(none)" for r in rows]
    auto = [r for r in rows if r["branch"] == "auto"]
    statutory = [r for r in rows if r["gold"] == "Statutory"]
    stat_auto = [r["ref"] for r in statutory if r["sent"] and r["tier"] in SENT_TIERS]
    dirty = []
    for r in rows:
        if not r["sent"]:
            continue
        kinds = guard.pii_found(r["sent_text"])
        unknown = set(guard.TOKEN_RE.findall(r["sent_text"])) - set(guard.TOKEN_RE.findall(r["masked"]))
        if kinds or unknown:
            dirty.append(r["ref"])
    drafted = [r for r in rows if r["guard_ok"] is not None]
    howto = [r for r in rows if r["gold"] == "How-To"]
    return {
        "n": len(rows),
        "classification": {
            "accuracy": round(metrics.accuracy(gold, pred), 4),
            "macro_f1": round(metrics.macro_f1(gold, pred, TEAM_LIST), 4),
            "customer_pick": round(metrics.accuracy(gold, [r["customer_pick"] for r in rows]), 4),
            "by_language": metrics.by_group(gold, pred, [r["language"] for r in rows]),
            "by_team": metrics.by_group(gold, pred, gold),
            "auto_share": round(len(auto) / len(rows), 4) if rows else 0.0,
            "auto_accuracy": round(metrics.accuracy([r["gold"] for r in auto], [r["pred"] for r in auto]), 4),
            "payroll_vs_statutory": metrics.confusion_between(gold, pred, "Payroll", "Statutory"),
        },
        "routes": dict(Counter(r["route"] for r in rows).most_common()),
        "rules": dict(Counter(r["rule"] for r in rows).most_common()),
        "answer_tiers": dict(Counter(r["tier"] for r in rows).most_common()),
        "statutory": {"n": len(statutory), "answered_without_a_person": stat_auto},
        "sent_dirty": dirty,
        "guard": {"drafts": len(drafted), "passed": sum(1 for r in drafted if r["guard_ok"]),
                  "problems": dict(Counter(p.split(":")[0] for r in drafted for p in r["guard_problems"] or []))},
        "howto": {"n": len(howto), "answered_automatically": sum(1 for r in howto if r["sent"] and r["tier"] in SENT_TIERS)},
        "wrong": [{k: r[k] for k in ("ref", "language", "gold", "pred", "branch")} for r in rows if r["gold"] != r["pred"]],
    }


def gates(ev: dict) -> list[tuple[str, bool, str]]:
    c, g = ev["classification"], ev["guard"]
    worst = min(c["by_language"].items(), key=lambda kv: kv[1]) if c["by_language"] else ("-", 0)
    pass_rate = g["passed"] / g["drafts"] if g["drafts"] else 1.0
    return [
        ("classify_accuracy", c["accuracy"] >= GATE_OVERALL and worst[1] >= GATE_LANGUAGE,
         f"{c['accuracy']:.1%} (customer pick {c['customer_pick']:.1%}), macro-F1 {c['macro_f1']:.3f}; "
         f"lowest language {worst[0]} {worst[1]:.0%}"),
        ("statutory_never_auto", not ev["statutory"]["answered_without_a_person"],
         f"{len(ev['statutory']['answered_without_a_person'])} of {ev['statutory']['n']} Statutory tickets answered "
         f"without a person"),
        ("sent_replies_clean", not ev["sent_dirty"], f"{len(ev['sent_dirty'])} sent replies with PII or unknown tokens"),
        ("guard_pass_rate", pass_rate >= GATE_GUARD,
         f"{g['passed']}/{g['drafts']} drafts passed ({pass_rate:.0%}); problems {g['problems'] or 'none'}"),
    ]


def customer_text(body: str) -> str:
    return customer_view(body)
