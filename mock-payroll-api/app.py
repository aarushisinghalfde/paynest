"""Mock payroll API: stands in for the client's read-only payroll endpoints.

Phase 1: health plus one stub endpoint. Phase 8 adds statutory rates, run status
with rate limiting (429s), and tenant profiles.

Run:  uvicorn app:app --app-dir mock-payroll-api --port 8081
"""
from fastapi import FastAPI

app = FastAPI(title="Mock Payroll API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/runs/{run_id}/status")
def run_status(run_id: str) -> dict:
    return {"run_id": run_id, "status": "completed", "stub": True}
