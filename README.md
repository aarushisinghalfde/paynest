# Payce Support Assist

A support-ticket assistant for a payroll provider: mask PII first, classify and route
by rules, draft replies from approved sources, check every reply, and put a human in the
loop for statutory answers. Built phase by phase; each phase ends at a gate recorded in
`results/gates.csv`.

**Docs:**

| Doc | What it covers |
| --- | --- |
| [Discovery note](docs/paynest_Discovery_Note.md) | The problem in the client's words, evidence, cost, ranked shortlist |
| [SPIN sheet](docs/paynest_SPIN_Sheet.md) | Stakeholders, pressures, constraints, success criteria, question funnel |
| [PRD](docs/paynest_PRD.md) | Goals, users, scope, functional and non-functional requirements, metrics, rollout |
| [Solution approach](docs/solution_approach.md) | What we build and why, workflow, where code stops and models start |
| [Architecture](docs/architecture.md) | Diagrams, AWS stacks, request/data/release flows, security, cost, decision log |
| [LLD](docs/lld.md) | Stage-by-stage design, sequence diagram, failure behaviour |
| [Build note](docs/build_note.md) | Code vs model table, patterns, models, cost line, what broke |
| [Presentation](docs/Payce_Support_Assist_build_review.pptx) | Build review deck (11 slides) |
| [Demo script](docs/demo_script.md) | 15-minute walkthrough: prep, scenes with exact messages, fallbacks, likely questions |

**Build region:** Sydney (`ap-southeast-2`), account Agentic Core FDE. Production
regions `ap-south-1` (India) and `me-central-1` (UAE) are kept as placeholder config.
**Models:** OpenRouter stands in until AWS lifts the Bedrock hold on the account
(phase 0 outcome).

## Links

Everything runs in Sydney (`ap-southeast-2`), AWS profile `payce-fde`. No secrets here:
they live in your `.env` and in SSM under `/paynest/demo/`.

**Demo app** (up only while the demo EC2 and RDS are running)

| Page | Link |
| --- | --- |
| Home | https://whps24ardd.execute-api.ap-southeast-2.amazonaws.com |
| Customer chat | https://whps24ardd.execute-api.ap-southeast-2.amazonaws.com/chat |
| Reviewer console | https://whps24ardd.execute-api.ap-southeast-2.amazonaws.com/review (paste `ADMIN_TOKEN` from `.env`) |
| API health | https://whps24ardd.execute-api.ap-southeast-2.amazonaws.com/api/health (the API is under `/api/`) |

**Code**

| What | Link |
| --- | --- |
| Repo | https://github.com/aarushisinghalfde/paynest |
| CI and image builds | https://github.com/aarushisinghalfde/paynest/actions |
| Tags (current release v0.3.0) | https://github.com/aarushisinghalfde/paynest/tags |

**AWS console**

| What | Link |
| --- | --- |
| CloudFormation stacks | https://ap-southeast-2.console.aws.amazon.com/cloudformation/home?region=ap-southeast-2#/stacks |
| Demo EC2 instance | https://ap-southeast-2.console.aws.amazon.com/ec2/home?region=ap-southeast-2#Instances:tag:Name=paynest-demo-server |
| App logs (`/paynest/demo/app`) | https://ap-southeast-2.console.aws.amazon.com/cloudwatch/home?region=ap-southeast-2#logsV2:log-groups/log-group/$252Fpaynest$252Fdemo$252Fapp |
| Alarms | https://ap-southeast-2.console.aws.amazon.com/cloudwatch/home?region=ap-southeast-2#alarmsV2: |
| SSM parameters | https://ap-southeast-2.console.aws.amazon.com/systems-manager/parameters/?region=ap-southeast-2 |
| SSM Run Command history | https://ap-southeast-2.console.aws.amazon.com/systems-manager/run-command/executed-commands?region=ap-southeast-2 |
| API Gateway | https://ap-southeast-2.console.aws.amazon.com/apigateway/main/apis?region=ap-southeast-2 |
| SQS queues | https://ap-southeast-2.console.aws.amazon.com/sqs/v3/home?region=ap-southeast-2#/queues |
| DynamoDB (PII vault) | https://ap-southeast-2.console.aws.amazon.com/dynamodbv2/home?region=ap-southeast-2#tables |
| Vault reveal Lambda | https://ap-southeast-2.console.aws.amazon.com/lambda/home?region=ap-southeast-2#/functions/paynest-demo-vault-reveal |
| RDS | https://ap-southeast-2.console.aws.amazon.com/rds/home?region=ap-southeast-2#databases: |

**Deploy and operate** (PowerShell, from the repo root)

```powershell
# Release: tag a version; images.yml builds the images
git tag vX.Y.Z; git push origin vX.Y.Z
# Secrets from .env into SSM
.\scripts\put_secrets.ps1
# Restart the app on the EC2 (pulls the images, runs migrations)
aws ssm send-command --profile payce-fde --region ap-southeast-2 --instance-ids <id from .\scripts\demo.ps1 status> --document-name AWS-RunShellScript --parameters "commands=['systemctl restart paynest']"
# Load the case data (phase 4) and run the gates
$env:AWS_PROFILE = "payce-fde"; python scripts\run_phase4.py
.\scripts\run_checks.ps1      # every live gate and the evals, into checks_<time>.log
# Infra changes: always plan, review, then apply
.\scripts\cfn.ps1 plan <stack>; .\scripts\cfn.ps1 apply <stack>
# Stop the demo when idle
.\scripts\demo.ps1 stop
```

## What runs where

| Piece | Where | Why |
| --- | --- | --- |
| Postgres + pgvector | Local Docker container | Fast to reset; RDS in Sydney from phase 2 |
| Redis (cache) | **Upstash**, locally and in production | Free tier covers the pilot; same `REDIS_URL` everywhere |
| Queue | **Amazon SQS in Sydney**: `paynest-dev-tickets-in` + `paynest-dev-tickets-dlq` | The real service; free tier covers the pilot |
| Queue, offline (optional) | Local **ElasticMQ** container, same queue names | Work without AWS; same code, only `SQS_ENDPOINT_URL` changes |
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
| `infra/` | `local/elasticmq.conf` (optional local queue); `cfn/` CloudFormation templates from phase 2 | 1–2 |
| `docs/` | `architecture.md`: what is built, diagrams, decisions | 2+ |
| `.github/workflows/` | `CI.yml` (ruff, pytest, web build, cfn-lint on every push); `images.yml` (release images, version tags only) | 1–2 |
| `scripts/create_dev_queues.py` | Creates the dev SQS queues in Sydney | 1 |
| `scripts/migrate.py` | Applies `db/migrations/*.sql`, each once | 1 |
| `scripts/check_phase1.py` | Local smoke test: a ticket goes through the local stack | 1 |
| `scripts/precheck.ps1`, `deploy.ps1`, `run_checks.ps1` | CI checks before a push; release; every live gate | D |
| `scripts/cfn.ps1` | Validate, plan (change set), apply, output, delete a CloudFormation stack | 2 |
| `scripts/put_secrets.ps1` | Copies secrets from `.env` into SSM Parameter Store (encrypted) | 2 |
| `data/` | Case data (git-ignored; the README says why) | 3+ |
| `evals/` | Evaluation sets and how to run every eval; the labelled set itself is git-ignored | 3+ |

## Run it yourself (reviewers)

Two ways to look at Paynest:

1. **Live demo:** open https://whps24ardd.execute-api.ap-southeast-2.amazonaws.com/chat (see **Links** above). It is up only while the demo
   EC2 and RDS are running, so agree a time with the owner.
2. **On your own laptop:** clone the repo and follow **Run it** below with your own
   `.env`. You never need the owner's secrets or AWS account: use your own free Upstash
   Redis URL, and the offline queue (`SQS_ENDPOINT_URL=http://localhost:9324` with
   `--profile local-queue`) instead of Amazon SQS. A step-by-step no-AWS walkthrough will be
   verified and added here before handover.

## Release and operate

One-command release and every gate: `.\scripts\deploy.ps1 v0.8.0`. Traces, the Valkey cache
switch and the gate list: [docs/operate.md](docs/operate.md).

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

**Offline, without AWS:** set `SQS_ENDPOINT_URL=http://localhost:9324` in `.env` and start
with `docker compose --profile local-queue up -d --build --wait`. ElasticMQ creates the same
two queues; browse them at http://localhost:9326. Clear the setting to go back to real SQS.

Stop with `docker compose down` (add `-v` to also wipe the local database). The
containers use your `aws login` session; when it expires, sign in again and run
`docker compose restart api worker`.

## Phase 1 gate

`scripts\check_phase1.py` must print `PHASE 1 GATE: PASS`, the GitHub Actions run must be
green, and a fresh clone must come up with `docker compose up -d --build --wait` in
under 5 minutes (time it with `Measure-Command { docker compose up -d --build --wait }`).

Never commit `.env`: it holds your Upstash URL and, from phase 6, API keys.
