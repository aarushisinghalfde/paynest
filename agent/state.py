"""The state that travels through the graph and is checkpointed after every node.

Only masked text ever enters the state: pii_gate is the first node, and it replaces the
ticket id with the masked ticket. Raw values stay in the vault.
"""

from typing import Any, TypedDict

NODES = [
    "pii_gate",
    "normalise",
    "resolve_tenant",
    "classify",
    "dedupe",
    "route",
    "draft",
    "output_guard",
    "send",
]


class TicketState(TypedDict, total=False):
    ticket_id: str
    tenant_id: str
    tenant: dict | None
    subject: str
    body: str  # masked
    language: str
    team: str | None
    confidence: float
    classification: dict
    duplicate_of: str | None
    route: str  # reply | review | queue | block | incident | duplicate | chat | ask
    route_reason: str
    route_rule: str
    queue: str | None
    injection_rules: list[str]
    talk: str | None  # greeting | thanks | vague | status (agent/conversation.py, normalise)
    status_of: dict | None  # the earlier ticket an "update?" refers to: {ref, route}
    context: str | None  # the earlier message this one follows up (same conversation)
    context_team: str | None  # team of that earlier turn (How-To: keep the How-To thread)
    history: list[dict]  # last turns of this conversation, masked: [{text, reply}]
    duplicate_reason: str | None
    incident_id: str | None
    incident_size: int
    jira_key: str | None
    waiting_review: bool
    draft: str | None
    draft_version: int
    draft_mode: str  # library | cache | model | fallback | template
    howto: bool  # answered by the How-To agent (library -> cache -> RAG)
    learn_kb: list[str]  # How-To answered with a guide only: ask support to write the steps once
    citations: list[str]
    sources: dict  # {"as_of", "hits", "facts"}: what the draft was allowed to use (phase 8)
    guard: dict
    sent: bool
    steps: list[str]  # node names run, in order (for tests and the "why" timeline)
    meta: dict[str, Any]
