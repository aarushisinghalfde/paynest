# Payce Support Assist

A support-ticket assistant for a payroll provider: mask PII first, classify and route
by rules, draft replies from approved sources, check every reply, and put a human in the
loop for statutory answers. Built phase by phase; each phase ends at a gate recorded in
`results/gates.csv`.

**Build region:** Sydney (`ap-southeast-2`), account Agentic Core FDE. Production
regions `ap-south-1` (India) and `me-central-1` (UAE) are kept as placeholder config.
**Models:** OpenRouter stands in until AWS lifts the Bedrock hold on the account
(phase 0 outcome).

## What runs where

| Piece | Where | Why |
| --- | --- | --- |
| Postgres + pgvector | Local Docker container | Fast to reset; RDS in Sydney from phase 2 |
| Redis (cache) | **Upstash**, locally and in production | Free tier covers the pilot; same `REDIS_URL` everywhere |
| Queue | **Amazon SQS in Sydney**: `paynest-dev-tickets-in` + `paynest-dev-tickets-dlq` | The real service; free tier covers the pilot |
| API, worker, mock payroll API, web | Local Docker containers | Deployed to AWS in phase 2 |

## Layout

| Path | What | Phase |
| --- | --- | --- |
| `api/` | FastAPI: `/health`, `/ready` (Postgres + extensions, Redis, queue) | 1 |
| `worker/` | Reads the tickets queue; deletes a message only after it is handled | 1 |
| `web/` | React (Vite): `/chat` (customer) and `/review` (reviewer) | 1 |
| `mock-payroll-api/` | Stand-in for the client's read-only payroll API | 1 |
| `shared/` | Settings, SQS client, dependency checks | 1 |
| `db/migrations/` | Plain SQL files, applied in order by `scripts/migrate.py` | 1+ |
| `config/regions/` | `demo.yaml` (Sydney, built); `india.yaml`, `uae.yaml` (placeholders) | 1 |
| `config/models.yaml` | Provider and model ladder, cheapest first | 1 |
| `infra/` | Terraform from phase 2 | 2 |
| `scripts/phase0/` | AWS account and day-1 checks | 0 |
| `scripts/create_dev_queues.py` | Creates the dev SQS queues in Sydney | 1 |
| `scripts/migrate.py` | Applies `db/migrations/*.sql`, each once | 1 |
| `scripts/check_phase1.py` | Phase 1 gate | 1 |
| `data/`, `evals/` | Case data (raw is git-ignored) and evaluation sets | 3+ |

## Run it

Needs Docker Desktop, Python 3.12, AWS CLI 2.32+ and a free Upstash Redis database.

```powershell
# 1. Settings: copy, then put your Upstash URL in REDIS_URL
copy .env.example .env
notepad .env

# 2. Laptop-side tools
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Sign in to AWS (Agentic Core FDE) and create the dev queues once
aws login --profile payce-fde --remote
python scripts\create_dev_queues.py

# 4. One command starts the stack (postgres, api, worker, mock payroll API, web)
docker compose up -d --build --wait

# 5. Checks
ruff check .
pytest
python scripts\check_phase1.py
```

| URL | What |
| --- | --- |
| http://localhost:8000/health and `/ready` | API |
| http://localhost:3000/chat and `/review` | Web |
| http://localhost:8081/health | Mock payroll API |

Stop with `docker compose down` (add `-v` to also wipe the local database). The
containers use your `aws login` session; when it expires, sign in again and run
`docker compose restart api worker`.

## Phase 1 gate

`scripts\check_phase1.py` must print `PHASE 1 GATE: PASS`, the GitHub Actions run must be
green, and a fresh clone must come up with `docker compose up -d --build --wait` in
under 5 minutes (time it with `Measure-Command { docker compose up -d --build --wait }`).

Never commit `.env`: it holds your Upstash URL and, from phase 6, API keys.
