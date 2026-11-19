"""API endpoints, with the dependency checks replaced by stubs."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from shared import deps  # noqa: E402

client = TestClient(app)


def test_health_is_200_and_names_the_region():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["aws_region"] == "ap-southeast-2"


def test_ready_when_all_dependencies_answer(monkeypatch):
    ok = {"postgres": lambda: "ok", "valkey": lambda: "ok", "queue": lambda: "ok"}
    monkeypatch.setattr(deps, "CHECKS", ok)
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_not_ready_names_the_failing_dependency(monkeypatch):
    def down():
        raise ConnectionError("refused")

    monkeypatch.setattr(deps, "CHECKS", {"postgres": lambda: "ok", "valkey": down})
    resp = client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["valkey"]["ok"] is False
    assert "refused" in resp.json()["checks"]["valkey"]["detail"]
