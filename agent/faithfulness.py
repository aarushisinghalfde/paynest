"""Plan v2 C2: faithfulness of model-written drafts - is every claim backed by the sources it was given?

Our version, built for this agent:
  - only drafts the MODEL wrote are judged. Fixed-wording drafts are assembled from the sources
    field by field, so they are faithful by construction (the guard already checks their numbers);
  - the judge sees exactly what the drafter saw (retrieved passages + tool facts, masked) and the
    draft, and splits the draft into claims. Greetings, offers of help and questions back to the
    customer are not claims;
  - a claim counts as supported only if the judge points to the source id that backs it AND that
    id was in the drafter's sources, so a judge cannot "support" a claim from its own knowledge;
  - the judge runs on a different rung than the drafter where the ladder allows, and the gate is
    reported with its sample size, because a model grading model output is noisy.
"""

import json

from agent.models import BudgetExceeded, ModelError

JUDGE = """You check a customer-support answer against the sources it was written from.
Split the ANSWER into factual claims (statements about rules, values, dates, product behaviour,
statuses or steps). Ignore greetings, offers of further help and questions to the customer.
For each claim, say whether the SOURCES state it, and give the id of the source that does.
A claim is supported only if a source says it; general knowledge does not count.
Return JSON: {"claims": [{"claim": "...", "supported": true|false, "source": "<id or null>"}]}"""


def sources_text(sources: dict) -> tuple[str, set[str]]:
    hits = sources.get("hits") or []
    facts = sources.get("facts") or []
    lines = [f"[{h.get('chunk_id')}] {h.get('title') or ''}\n{(h.get('content') or '')[:900]}" for h in hits]
    lines += [f"[{f.get('source')}] {json.dumps({k: v for k, v in f.items() if k not in ('source',)}, default=str)}"
              for f in facts]
    ids = {h.get("chunk_id") for h in hits} | {f.get("source") for f in facts}
    return "\n".join(lines) or "(none)", {i for i in ids if i}


def judge(draft: str, sources: dict, model, rung: int = 1) -> dict | None:
    """{"claims": n, "supported": k, "unsupported": [claim, ...]} or None if the judge failed."""
    text, ids = sources_text(sources)
    try:
        res = model.json_call(JUDGE, f"SOURCES:\n{text}\n\nANSWER:\n{draft}", rung=rung, purpose="judge",
                              max_tokens=700)
    except (BudgetExceeded, ModelError):
        return None
    claims = [c for c in res.data.get("claims") or [] if isinstance(c, dict) and c.get("claim")]
    ok = [c for c in claims if c.get("supported") is True and c.get("source") in ids]
    return {"claims": len(claims), "supported": len(ok),
            "unsupported": [str(c["claim"])[:160] for c in claims if c not in ok]}


def summarize(results: list[dict]) -> dict:
    judged = [r for r in results if r]
    claims = sum(r["claims"] for r in judged)
    supported = sum(r["supported"] for r in judged)
    return {"drafts_judged": len(judged), "claims": claims, "supported": supported,
            "score": round(supported / claims, 3) if claims else None,
            "examples_unsupported": [u for r in judged for u in r["unsupported"]][:8]}
