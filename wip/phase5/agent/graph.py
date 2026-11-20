"""The ticket graph in LangGraph, checkpointed in Postgres (thread_id = ticket id).

The worker calls run(ticket_id). If a previous run died mid-way (crash, out of memory,
redeploy), LangGraph finds the thread's last checkpoint and continues from the node that
had not finished: pii_gate is never re-run for a ticket that is already past it.
"""

from functools import partial

from agent.nodes import NODE_FUNCS, Deps
from agent.state import NODES, TicketState


def build(deps: Deps, checkpointer):
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(TicketState)
    for name in NODES:
        g.add_node(name, partial(NODE_FUNCS[name], deps=deps))
    g.add_edge(START, NODES[0])
    for a, b in zip(NODES, NODES[1:], strict=False):
        g.add_edge(a, b)
    g.add_edge(NODES[-1], END)
    return g.compile(checkpointer=checkpointer)


def run(graph, ticket_id: str) -> dict:
    config = {"configurable": {"thread_id": ticket_id}}
    snapshot = graph.get_state(config)
    if snapshot and snapshot.values:  # resume: continue from the unfinished node
        if not snapshot.next:
            return snapshot.values  # already finished (a redelivered message)
        return graph.invoke(None, config)
    return graph.invoke({"ticket_id": ticket_id, "steps": []}, config)


def postgres_checkpointer(dsn: str):
    """PostgresSaver on its own autocommit connection; creates its tables on first use."""
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row

    conn = psycopg.connect(dsn, autocommit=True, prepare_threshold=0, row_factory=dict_row)
    saver = PostgresSaver(conn)
    saver.setup()
    return saver
