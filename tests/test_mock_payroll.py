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


def test_run_status_stub():
    body = client.get("/runs/RUN-1/status").json()
    assert body == {"run_id": "RUN-1", "status": "completed", "stub": True}
