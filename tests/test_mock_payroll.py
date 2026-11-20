import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "mock_payroll_app", Path(__file__).resolve().parent.parent / "mock-payroll-api" / "app.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
client = TestClient(module.app)


def test_health():
    assert client.get("/health").status_code == 200


def test_run_status_is_deterministic_and_on_the_openapi_path():
    a = client.get("/payroll-runs/PR-202609/status").json()
    assert a == client.get("/payroll-runs/PR-202609/status").json()
    assert a["run_id"] == "PR-202609" and a["status"] in {"completed", "processing", "failed"}
    assert client.get("/runs/PR-202609/status").json() == a  # phase 1 path still works


def test_run_status_rate_limit():
    r = client.get("/payroll-runs/PR-1-429/status")
    assert r.status_code == 429 and r.headers["retry-after"] == "2"
