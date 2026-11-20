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
    route: str  # reply | queue | block
    route_reason: str
    draft: str | None
    draft_version: int
    guard: dict
    sent: bool
    steps: list[str]  # node names run, in order (for tests and the "why" timeline)
    meta: dict[str, Any]
