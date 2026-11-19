# Payce Support Assist

A support-ticket assistant for a payroll provider: mask PII first, classify and route
by rules, draft replies from approved sources, check every reply, and put a human in the
loop for statutory answers. Built phase by phase; each phase ends at a gate recorded in
`results/gates.csv`.

**Build region:** Sydney (`ap-southeast-2`), account Agentic Core FDE.
Production regions `ap-south-1` (India) and `me-central-1` (UAE) are kept as
placeholder config. **Models:** OpenRouter stands in until AWS lifts the Bedrock hold
on the account (phase 0 outcome).

## Layout

| Path | What | Phase |
| --- | --- | --- |
| `api/` | FastAPI: `/health`, `/ready` (Postgres + extensions, Valkey, queue) | 1 |
| `worker/` | Reads `tickets-in`; deletes a message only after it is handled | 1 |
| `web/` | React (Vite): `/chat` (customer) and `/review` (reviewer) | 1 |
| `mock-payroll-api/` | Stand-in for the client's read-only payroll API | 1 |
| `shared/` | Settings, queue client, dependency checks | 1 |
| `migrations/` | Alembic; `0001` enables `vector` and `pg_trgm` | 1 |
| `config/regions/` | `demo.yaml` (Sydney, built); `india.yaml`, `uae.yaml` (placeholders) | 1 |
| `config/models.yaml` | Provider and model ladder, cheapest first | 1 |
| `infra/` | `local/elasticmq.conf` now; Terraform in phase 2 | 1–2 |
| `scripts/phase0/` | AWS account and day-1 checks | 0 |
| `scripts/check_phase1.py` | Phase 1 gate | 1 |
| `data/`, `evals/` | Case data (raw is git-ignored) and evaluation sets | 3+ |

## Run it

Needs Docker Desktop and Python 3.12.

```powershell
# One command starts the whole stack (postgres, valkey, elasticmq, api, worker, mock, web)
docker compose up -d --build --wait

# Laptop-side tools for tests and the gate script
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env

ruff check .
pytest
python scripts\check_phase1.py
```

| URL | What |
| --- | --- |
| http://localhost:8000/health and `/ready` | API |
| http://localhost:3000/chat and `/review` | Web |
| http://localhost:8081/health | Mock payroll API |
| http://localhost:9325 | Local queue browser (ElasticMQ) |

Stop with `docker compose down` (add `-v` to also wipe the database).

## Phase 1 gate

`scripts\check_phase1.py` must print `PHASE 1 GATE: PASS`, the GitHub Actions run must be
green, and a fresh clone must come up with `docker compose up -d --build --wait` in
under 5 minutes (time it with `Measure-Command { docker compose up -d --build --wait }`).

Never commit `.env`; it will hold API keys from phase 6.
