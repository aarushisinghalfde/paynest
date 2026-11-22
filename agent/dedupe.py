"""Duplicates and incidents, per tenant, over a time window (build plan phase 7).

duplicate: the same customer issue again within 72 h, either an explicit reference
           ("following up on my earlier ticket PN-...") or near-identical text.
incident:  a burst of similar tickets for one tenant (5 within 3 h) opens one incident;
           later similar tickets attach to it. The 5th ticket is the one that opens it.
jira:      a ticket similar to an open Jira issue of the same tenant is linked to it.
"""
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from agent.similarity import EXPLICIT_REF, RESUBMIT_MARKER, containment, jaccard, same_issue, shingles, words

DUP_WINDOW = timedelta(hours=72)
DUP_THRESHOLD = 0.8          # near-identical, AND the customer says it is a repeat
INCIDENT_WINDOW = timedelta(hours=3)
INCIDENT_SIZE = 5
INCIDENT_THRESHOLD = 0.25
JIRA_THRESHOLD = 0.5         # half of the issue summary's words appear in the ticket


@dataclass
class Recent:
    id: str
    ref: str | None
    created_at: object
    text: str
    incident_id: str | None = None
    duplicate_of: str | None = None
    _sh: set = field(default=None, repr=False)

    @property
    def sh(self):
        if self._sh is None:
            self._sh = shingles(self.text)
        return self._sh


def find_duplicate(text: str, created_at, recent: list[Recent]) -> tuple[str | None, str]:
    """A repeat of the customer's own earlier ticket. Many different customers use the same
    wording (templates, copy-paste), so similar text alone is NOT a duplicate: the message
    must also say it is a repeat ("following up", "second request", "RE:")."""
    m = EXPLICIT_REF.search(text or "")
    if m and any(r.ref == m.group(1) for r in recent):
        return m.group(1), "explicit reference"
    if not RESUBMIT_MARKER.search(text or ""):
        return None, ""
    sh = shingles(text)
    best = max(((jaccard(sh, r.sh), r) for r in recent
                if r.created_at and created_at - r.created_at <= DUP_WINDOW and not r.duplicate_of),
               default=(0, None), key=lambda x: x[0])
    if best[1] and best[0] >= DUP_THRESHOLD:
        return best[1].ref or best[1].id, f"repeat, {best[0]:.0%} similar"
    return None, ""


def find_incident(text: str, created_at, recent: list[Recent], open_incidents: list[dict]) -> dict:
    """{'incident_id', 'opened': bool, 'members': [ids]} or {} when no burst."""
    sh = shingles(text)
    for inc in open_incidents:
        if (same_issue(text, sh, inc["signature"], shingles(inc["signature"])) >= INCIDENT_THRESHOLD
                and created_at - inc["opened_at"] <= timedelta(hours=24)):
            return {"incident_id": inc["id"], "opened": False, "members": []}
    # similar to a ticket already in an incident (other wording, other language): attach to it
    for r in recent:
        if (r.incident_id and r.created_at and created_at - r.created_at <= timedelta(hours=24)
                and same_issue(text, sh, r.text, r.sh) >= INCIDENT_THRESHOLD):
            return {"incident_id": r.incident_id, "opened": False, "members": []}
    similar = [r for r in recent if r.created_at and created_at - r.created_at <= INCIDENT_WINDOW
               and not r.duplicate_of and same_issue(text, sh, r.text, r.sh) >= INCIDENT_THRESHOLD]
    if len(similar) + 1 >= INCIDENT_SIZE:
        return {"incident_id": str(uuid.uuid4()), "opened": True, "members": [r.id for r in similar],
                "signature": text}
    return {}


def match_jira(text: str, issues: list[dict]) -> str | None:
    """The open issue whose summary is most contained in the ticket (word level)."""
    tw = words(text)
    scored = [(containment(words(i["summary"]), tw), i["key"]) for i in issues]
    best = max(scored, default=(0, None))
    return best[1] if best[0] >= JIRA_THRESHOLD else None
