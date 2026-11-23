"""FDE engineering view: latency per node, failures, guard blocks, trace ids; admin only."""
from agent import console
from shared import tracing


def _row(i, tm, status="sent", failed=(), trace=None, tier="model"):
    return {"id": f"t{i}", "ref": f"R{i}", "route": "auto_send", "agent_status": status, "first_reply_seconds": 2.0 + i,
            "decision": {"timings_ms": tm, "trace_id": trace, "answer": {"tier": tier},
                         "guard": {"failed": list(failed)}, "classification": {"model_called": i % 2 == 0}}}


def test_engineering_summary():
    rows = [_row(1, {"classify": 10, "draft": 900}, trace="1-abc-def"),
            _row(2, {"classify": 30, "draft": 100}, status="failed", failed=["numbers"]),
            _row(3, {"classify": 20, "draft": 300}, tier="fallback")]
    usage = [{"purpose": "draft", "model": "m", "rung": 0, "calls": 3, "cost_usd": 0.01},
             {"purpose": "draft", "model": "m2", "rung": 1, "calls": 1, "cost_usd": 0.02}]
    e = console.engineering(rows, usage)
    assert e["with_timings"] == 3 and e["traced"] == 1
    assert e["slowest"][0]["id"] == "t1" and e["slowest"][0]["slowest_node"] == "draft"
    assert e["slowest"][0]["trace_id"] == "1-abc-def"
    assert e["failed"]["n"] == 1 and e["guard"]["by_check"] == [{"key": "numbers", "n": 1}]
    assert e["fallback"] == 1 and e["escalations"] == 1 and e["model_calls"] == 4
    nodes = {n["node"]: n for n in e["nodes"]}
    assert nodes["draft"]["p50"] == 300 and nodes["draft"]["share"] > 0.9
    assert "masked_body" not in str(e)  # ids and timings only


def test_engineering_empty():
    e = console.engineering([], [])
    assert e["tickets"] == 0 and e["end_to_end_ms"]["p50"] is None and e["nodes"] == []


def test_trace_id_none_without_span():
    assert tracing.current_trace_id() is None


def test_engineering_endpoint_admin_only(monkeypatch):
    import pytest

    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from api import main
    from shared import settings

    monkeypatch.setattr(settings, "ADMIN_TOKEN", "adm")
    monkeypatch.setattr(settings, "LEAD_TOKEN", "lead")
    c = TestClient(main.app)
    assert c.get("/console/whoami", headers={"X-Admin-Token": "lead"}).json() == {"role": "lead"}
    assert c.get("/console/whoami", headers={"X-Admin-Token": "adm"}).json() == {"role": "admin"}
    assert c.get("/console/engineering", headers={"X-Admin-Token": "lead"}).status_code == 401
