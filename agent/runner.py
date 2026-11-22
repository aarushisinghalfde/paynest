"""A minimal runner with LangGraph's checkpoint semantics, for tests and local runs.

After each node the state and the next node are saved under the ticket id (thread id).
If a node raises, the saved checkpoint is untouched, so the next run resumes AT that
node, not from the start. agent.graph does the same with LangGraph + PostgresSaver.
"""

from agent.nodes import NODE_FUNCS, Deps
from agent.state import NODES
from shared.tracing import span


class MemoryCheckpoints:
    def __init__(self):
        self.saved: dict[str, dict] = {}

    def get(self, thread_id):
        return self.saved.get(thread_id)

    def put(self, thread_id, next_node, state):
        self.saved[thread_id] = {"next": next_node, "state": dict(state)}


def run(ticket_id: str, deps: Deps, checkpoints: MemoryCheckpoints, nodes=None) -> dict:
    with span("ticket", ticket_id=ticket_id):  # one trace per ticket; the nodes are its children
        return _run(ticket_id, deps, checkpoints, nodes)


def _run(ticket_id, deps, checkpoints, nodes):
    order = nodes or NODES
    cp = checkpoints.get(ticket_id)
    state = dict(cp["state"]) if cp else {"ticket_id": ticket_id, "steps": []}
    start = order.index(cp["next"]) if cp and cp["next"] else (len(order) if cp else 0)
    for i in range(start, len(order)):
        state.update(NODE_FUNCS[order[i]](state, deps))
        checkpoints.put(ticket_id, order[i + 1] if i + 1 < len(order) else None, state)
    return state
