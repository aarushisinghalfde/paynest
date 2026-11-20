"""Mock payroll API: stands in for the client's read-only payroll endpoints.

Phase 8: run status by run id, the path from integrations/payroll_api_openapi.yaml.
Deterministic: the same run id always gives the same status. A run id ending in -429
returns HTTP 429, so the agent's rate-limit handling can be shown.

Run:  uvicorn app:app --app-dir mock-payroll-api --port 8081
"""

import hashlib

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Mock Payroll API", version="0.2.0")
STATES = [("completed", "paid"), ("processing", "bank_file_generated"), ("processing", "approval_pending"),
          ("failed", "bank_file_rejected")]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _status(run_id: str) -> dict:
    if run_id.upper().endswith("-429"):
        raise HTTPException(429, "rate limited", headers={"Retry-After": "2"})
    status, stage = STATES[int(hashlib.sha256(run_id.encode()).hexdigest(), 16) % len(STATES)]
    return {"run_id": run_id, "status": status, "stage": stage, "mock": True}


@app.get("/payroll-runs/{run_id}/status")
def payroll_run_status(run_id: str) -> dict:
    return _status(run_id)


@app.get("/runs/{run_id}/status")  # phase 1 path, kept for older checks
def run_status(run_id: str) -> dict:
    return _status(run_id)
