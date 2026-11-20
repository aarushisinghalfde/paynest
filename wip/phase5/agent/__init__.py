"""The ticket agent (phase 5 onwards): nodes are plain functions over one state dict.

agent.nodes   the nodes (pure, injected dependencies)
agent.graph   LangGraph wiring with PostgresSaver checkpoints (thread_id = ticket id)
agent.runner  a tiny in-memory runner with the same checkpoint semantics, for tests
"""
