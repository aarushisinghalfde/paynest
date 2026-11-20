# Paynest architecture

Status as of **20 Nov 2026, evening**: phases 0 and 1 done; phase 2 (AWS foundation) is
**live in Sydney** at https://whps24ardd.execute-api.ap-southeast-2.amazonaws.com
(the phase 2 gate script is still to come). This file describes what is built, what is planned, and why. Diagrams are
Mermaid and render on GitHub.

Paynest (Payce Support Assist) is a support-ticket assistant for a payroll provider with
India and UAE tenants. Every ticket is PII-masked first, classified and routed by rules,
answered from approved sources, checked by an output guard, and sent to a human reviewer
when the answer is statutory.

---

## 1. Where everything lives

```mermaid
flowchart LR
  subgraph Laptop["Your laptop (phases 0-1)"]
    C["docker compose<br/>postgres, api, worker,<br/>mock-payroll-api, web"]
    S["scripts/cfn.ps1<br/>scripts/put_secrets.ps1"]
  end
  subgraph GitHub["GitHub: aarushisinghalfde/paynest"]
    R["main branch"]
    CI["CI: ruff + pytest,<br/>web build, cfn-lint"]
    IMG["Images workflow<br/>(version tags only)"]
  end
  subgraph AWS["AWS Sydney (ap-southeast-2)"]
    ST["CloudFormation stacks"]
    ECR["ECR images"]
  end
  C -- "git push" --> R
  R --> CI
  R -- "git tag v*" --> IMG
  IMG -- "OIDC, push" --> ECR
  S -- "plan / apply (you approve)" --> ST
```

| Place | What it holds |
| --- | --- |
| Laptop | The full app in Docker Compose for development; the scripts that deploy AWS stacks and secrets. |
| GitHub | Source code, CI checks on every push, and the release workflow that builds images. |
| AWS Sydney | The demo environment, defined entirely in CloudFormation. |

**Rule:** nothing reaches AWS without an explicit human action: `cfn.ps1 apply` after a
reviewed change set, `put_secrets.ps1`, or pushing a version tag.

---

## 2. The application (phase 1, runs locally today)

| Service | Code | Role |
| --- | --- | --- |
| `api` | `api/main.py` (FastAPI) | `/health` (region), `/ready` (checks Postgres, Redis, queue; 503 if any fails). Runs `scripts/migrate.py` before starting. |
| `worker` | `worker/main.py` | Long-polls SQS every 20 s, processes a message, deletes it only on success, retries queue outages with backoff. LangGraph arrives in phase 5. |
| `postgres` | `pgvector/pgvector:pg17` | Database with `vector` (meaning search) and `pg_trgm` (fuzzy/code matching). Plain SQL migrations in `db/migrations/`. |
| `mock-payroll-api` | `mock-payroll-api/app.py` | Stand-in payroll system; the agent will call it as a tool. |
| `web` | `web/` (React + Vite, nginx) | Dashboard shell; nginx proxies `/api/` to the API. |

External services used locally: **Upstash Redis** (cache) and the **dev SQS queue** in
Sydney (`paynest-dev-tickets-in` + DLQ), or **ElasticMQ** offline
(`docker compose --profile local-queue`). Gate: `scripts/check_phase1.py`, 6/6 in both
queue modes.

---

## 3. AWS architecture (live in Sydney)

```mermaid
flowchart TB
  U["Browser"] -->|HTTPS| AG["API Gateway HTTP API<br/>(live)"]
  U -.->|"later, after account verification"| CF["CloudFront<br/>(blocked for now)"]
  subgraph VPC["VPC 10.20.0.0/16 (no NAT)"]
    subgraph PUB["Public subnets x2"]
      EC2["EC2 t4g.small + Elastic IP<br/>web, api, worker, mock payroll<br/>(live)"]
    end
    subgraph PRIV["Private subnets x2 (no internet route)"]
      RDS["RDS PostgreSQL 17.11<br/>(live)"]
    end
  end
  AG -->|"VPC Link, private, :80"| EC2
  CF -.->|"HTTP :80, CloudFront IPs only"| EC2
  EC2 -->|":5432, EC2 SG only"| RDS
  EC2 --> SQS["SQS tickets-in + DLQ"]
  EC2 --> SSM["SSM secrets"]
  EC2 --> S3["S3 data bucket<br/>(masked/, kb/, rules/)"]
  EC2 --> ECR["ECR app + web"]
  EC2 -.-> EXT["OpenRouter, Upstash<br/>(through the internet gateway)"]
  KMS["KMS key alias/paynest-demo"] -. encrypts .-> SQS
  KMS -. encrypts .-> SSM
  KMS -. encrypts .-> S3
  KMS -. encrypts .-> RDS
```

### Stacks (`infra/cfn/`, deployed with `scripts\cfn.ps1`)

| # | Stack | Resources | Status |
| --- | --- | --- | --- |
| 1 | `network` | VPC `10.20.0.0/16`, 2 public + 2 private subnets in 2 AZs, internet gateway, route tables. No NAT. | Deployed |
| 2 | `security` | EC2 security group (port 80 from the CloudFront prefix list only, no SSH); RDS security group (5432 from the EC2 group only, no egress); KMS key `alias/paynest-demo` with rotation. | Deployed |
| 3 | `data` | S3 bucket `paynest-demo-data-<account>` (KMS, versioned, private, HTTPS-only, retained on delete); SQS `paynest-demo-tickets-in` + DLQ (KMS, 3 tries); ECR `paynest-demo/app`, `paynest-demo/web` (scan on push, keep 5). | Deployed |
| 4 | `iam` | EC2 role + instance profile (least privilege); GitHub OIDC provider; GitHub deploy role (push to ECR only). | Deployed |
| 5 | `rds` | PostgreSQL 17.11 `db.t4g.micro`, private, KMS, password managed by AWS in Secrets Manager, 1-day backups, final snapshot on delete. | Deployed |
| 6 | `ec2` | t4g.small (AL2023 arm64), Elastic IP, encrypted disk, IMDSv2; boot script installs Docker and a `paynest` systemd service; grants read access to the DB secret. | Deployed |
| 7a | `apigw` | Public HTTPS URL via an API Gateway HTTP API; a VPC Link (private subnets) plus Cloud Map reaches the EC2 private IP on port 80; rate limit 20 req/s. Limits: 30 s per request, no WebSockets. | **Deployed** (live URL) |
| 7b | `cloudfront` | Distribution `https://<id>.cloudfront.net` in front of the EC2 (WebSockets, edge caching of `/assets/*`). | Written; **blocked** until AWS verifies the account |

Every template has a `Rules` check: `params/india.json` and `params/uae.json`
(`Deployable=false`) can be validated but never deployed. Stacks share values through
exports (`paynest-demo-VpcId`, ...), so CloudFormation refuses to delete a stack that
another still uses; delete newest first.

### How the EC2 starts the app

1. Boot script installs Docker and Docker Compose, writes non-secret settings to
   `/opt/paynest/settings`, the production compose file, and the `paynest` systemd unit.
2. On every start, `paynest.service`:
   - reads `/paynest/demo/*` from SSM and the DB password from Secrets Manager into
     `/run/paynest/app.env` (memory only, wiped at every stop);
   - logs in to ECR, pulls `app:latest` and `web:latest`;
   - runs `docker compose up -d` (api runs migrations first; web listens on port 80).
3. If the images are not in ECR yet, it retries every minute.

---

## 4. Request flow (live)

```mermaid
sequenceDiagram
  participant B as Browser
  participant CF as API Gateway
  participant W as nginx (web)
  participant A as API
  participant DB as RDS
  participant Q as SQS
  participant K as Worker
  B->>CF: HTTPS request
  CF->>W: HTTP :80 via VPC Link
  W->>A: /api/... (proxy)
  A->>DB: save ticket
  A->>Q: send ticket ID only
  A-->>B: 202 received
  K->>Q: long-poll (20 s)
  Q-->>K: ticket ID
  K->>DB: read ticket, run pipeline, save results
  K->>Q: delete message (only on success)
```

After 3 failed attempts a message moves to the DLQ, so one bad ticket never blocks the queue.

---

## 5. Data flow

```mermaid
flowchart LR
  subgraph Bulk["Bulk files (loaded once)"]
    F["data/raw files"] --> S3R["S3 raw/<br/>(loader only)"]
    S3R --> L["Loader job<br/>masks PII first"]
    L --> S3M["S3 masked/"]
    L --> PG["Postgres<br/>tickets, rules, KB + embeddings"]
  end
  subgraph Live["Live tickets (one at a time)"]
    CH["/chat or replay script"] --> API["API"]
    API --> PG2["Postgres (ticket)"]
    API --> Q["SQS: ticket ID only"]
    Q --> WK["Worker reads by ID"]
  end
```

- **Files never go through SQS.** SQS carries only a ticket ID (claim-check pattern), so
  wiping the queue loses no data and messages stay tiny.
- **Masking happens before anything else** reads ticket text. The EC2 role cannot read
  `raw/`.
- **Demo traffic is replayed through the API**, so the demo exercises the real path.

### PII gate (phase 3, `pii/`)

```mermaid
flowchart LR
  subgraph P["Presidio pipeline"]
    R["PaynestRecognizer<br/>regex + checksums"]
    S["spaCy en_core_web_sm<br/>PERSON"]
  end
  T["Ticket body"] --> N["Normalise digits<br/>٧ / ७ -> 7"]
  N --> P
  P --> NM["Name rules<br/>sender, intros, sign-offs"]
  NM --> TK["Tokeniser<br/>value -> IBAN_1"]
  TK --> M["Masked ticket -> worker, agents"]
  TK --> V["Vault: DynamoDB + KMS<br/>3b-2, planned"]
```

- **Our recognisers are the gate.** Aadhaar (Verhoeff), Emirates ID (Luhn), IBAN (mod-97),
  PAN, IFSC, UAN, phones, emails and unknown long numbers. They give the same result with
  or without Presidio, and the 60-ticket leak test (English, Hinglish, Hindi, Arabic) must
  show 0 raw values.
- **Mid-sentence names** are found by a capitalised-name rule (two or more capitalised words
  that are not common or payroll words, e.g. "Ananya Iyer") and by spaCy (`en_core_web_sm`)
  through Presidio. The first CI run showed spaCy alone missed 3 of 12 Indian names and
  tagged "Email" as a person, so the rule is part of the gate; 12 extra seeded tickets
  test it.
- **Single first names** ("Gaurav will send it", "Kal Zubair ne bola", "مع سلطان") are found
  by context cues (ask/with/said/'s, Hinglish ne/ka/ko/ji) and a list of common Indian and
  Arab first names in Latin, Devanagari and Arabic script (`pii/names.py`). Names that are
  also everyday words (निधि as in भविष्य निधि, مبارك, عمر "age") are excluded, and a
  precision test checks that ordinary sentences in all four languages come back unchanged.
- **Same value, same token** within a ticket (`<NAME_1>` everywhere), so agents can still
  follow the conversation.
- `PII_NER=auto|required|off` controls the Presidio layer (`required` in the worker image).
- **Known limit, and the standard fix:** checksum rules for IDs are industry practice; the
  first-name list and cues are a stop-gap because `en_core_web_sm` is English-only and weak
  on Indian names. Planned 3c: a multilingual transformer NER in Presidio as the main name
  detector (list kept as backup), chosen by measured recall vs RAM. Amazon Comprehend PII
  is English/Spanish only, so it cannot cover Hindi or Arabic.

### Ticket intake and the gate (phase 3b, `api/`, `intake/`, `worker/`)

```mermaid
flowchart TD
  C["POST /api/tickets"] --> API["API: validate"]
  API --> IN["Postgres: tickets (received)<br/>+ ticket_inbox (raw, short-lived)"]
  API --> Q["SQS: {ticket_id} only"]
  Q --> W["Worker: PII gate"]
  IN --> W
  W --> MK["mask_ticket"]
  MK --> RS{"Re-scan masked text"}
  RS -->|"hit"| BL["status pii_blocked<br/>inbox kept for review, nothing vaulted"]
  RS -->|"clean"| V["Vault put (append-only)<br/>DynamoDB + KMS"]
  V --> SV["tickets: masked_body, pii_counts, sender tokens<br/>inbox row deleted (same transaction)"]
```

- **Raw text lives in one place, briefly.** `ticket_inbox` holds the body and sender
  fields until the worker masks them; the same transaction that saves `masked_body`
  deletes the inbox row. `GET /tickets/{id}` never returns raw text and shows the body
  only once the gate has passed it.
- **Re-scan before release.** The masked text is checked three ways: no vaulted value
  survives (whole-word, so `علي` inside `عليه` is not a hit), the sender's email or phone
  is not left in the text, and a second masking pass finds nothing. Any hit quarantines
  the ticket as `pii_blocked` with reasons that name kinds only (`second_pass:PHONE`).
- **Sender tokens.** `HMAC-SHA256(PII_HMAC_KEY, tenant | kind | normalised value)`: the
  same sender in one tenant always gets the same `em_...` / `ph_...` token, different
  tenants get different tokens, and the key lives in SSM. The raw sender fields go to the
  vault as `<SENDER_NAME>`, `<SENDER_EMAIL>`, `<SENDER_PHONE>` for replies.
- **Vault (decided 20 Nov: DynamoDB, not Postgres).** One item per value (`ticket_id`,
  `token`), each encrypted with the vault KMS key and the encryption context
  `{ticket_id, token, tenant_id}`, so KMS itself refuses a reveal for the wrong ticket.
  Writes are conditional (append-only). TTL removes values after `VAULT_TTL_DAYS` (30).
  EC2 role: `kms:Encrypt` + `dynamodb:PutItem` only. The `vault-reveal` Lambda (outside the
  VPC, so no KMS endpoint is needed) is the only role with `GetItem` and `kms:Decrypt`.
- **Retries are safe.** Values are vaulted before the masked row is saved; if the vault
  write fails the inbox row stays and SQS redelivers. A redelivered message for a masked
  ticket is skipped.
- **Logs are JSON lines with ids, kinds, counts and timings, never values**
  (`shared/logs.py`). Exceptions are logged as type + file:line only, because exception
  messages can quote data (a Postgres error can include the failing row). Events:
  `ticket_received`, `ticket_masked`, `pii_blocked`, `ticket_skipped`, `message_failed`.
- **Evaluation:** `python scripts/eval_pii.py` reports recall per type and language,
  over-masking (30 clean sentences in `tests/fixtures/pii_clean.json` plus unlabelled
  spans) and latency; `--record` appends rows to `results/gates.csv`. On the synthetic
  seed (rules only): 100% of 408 values, 0/30 clean sentences changed, p50 0.6 ms. This
  proves the plumbing; real recall needs the phase 4 data.

---

## 6. Release flow (images)

```mermaid
flowchart LR
  T["You: git tag v0.x.y<br/>git push origin v0.x.y"] --> GA["GitHub Actions<br/>test, then build on native ARM"]
  GA -->|"OIDC: repo ID + v* tags only"| ECR["ECR: app and web<br/>tags v0.x.y + latest"]
  ECR --> D["You: deploy (planned)<br/>SSM tells EC2 to pull and restart"]
```

- Ordinary pushes run CI only. Images are built **only** for version tags (or a manual run
  from `main`).
- The GitHub deploy role trusts GitHub's immutable subject
  `repo:aarushisinghalfde@319837126/paynest@1464089610:ref:refs/tags/v*` (or `refs/heads/main`),
  so a renamed or re-created repository cannot assume it. No AWS keys are stored in GitHub.
- Images are arm64 to match the Graviton (t4g) EC2. ECR keeps the last 5 per repository.

---

## 7. Security controls

| Control | Where |
| --- | --- |
| No SSH; admin access via SSM Session Manager | `security`, `iam` |
| EC2 reachable only from CloudFront on port 80 | `security` |
| RDS private, reachable only from the EC2 security group | `network`, `security`, `rds` |
| One KMS key for S3, SQS, SSM, RDS and the EC2 disk | `security` |
| Secrets in SSM / Secrets Manager, loaded into memory at start; nothing in git or on disk | `put_secrets.ps1`, `ec2` |
| Least-privilege roles (one queue, one key, own secrets, masked S3 prefixes, ECR pull) | `iam`, `ec2` |
| CI and release separated; release needs a version tag | `.github/workflows/` |
| Placeholder regions cannot be deployed | `Rules` in every template |
| S3 data retained and RDS snapshotted if a stack is deleted | `data`, `rds` |

---

## 8. Cost (demo, Sydney, approximate)

| Item | Running | Stopped |
| --- | --- | --- |
| Foundation (VPC, SGs, S3, SQS, ECR, IAM, SSM) | cents per month | cents per month |
| KMS key | about USD 1 per month | same |
| RDS `db.t4g.micro` + 20 GB | about USD 0.70 per day | storage only (about USD 0.09 per day) |
| EC2 `t4g.small` + 20 GB disk | about USD 0.57 per day | disk only (about USD 0.06 per day) |
| Elastic IP | about USD 0.12 per day | same (charged while stopped) |
| API Gateway (about USD 1 per million requests), VPC Link, Cloud Map | cents per month | same |
| GitHub Actions | free (public repo) | - |

EC2 and RDS are started only for work sessions and demos (start/stop scripts planned).

---

## 9. Key decisions

| Date | Decision | Why |
| --- | --- | --- |
| 19 Nov | Upstash Redis instead of a Redis container; real SQS in Sydney with optional ElasticMQ | Same services locally and in AWS; work offline when needed. |
| 20 Nov | **CloudFormation** instead of Terraform | AWS keeps the state, automatic rollback, team familiarity; everything deployed is AWS. |
| 20 Nov | **Hosting option B: CloudFront -> EC2** (not Vercel) | Free HTTPS without a domain, no CORS, everything in AWS. |
| 20 Nov | **Custom VPC, no NAT** | RDS in private subnets; nothing private needs outbound internet. |
| 20 Nov | **No SSH**, SSM Session Manager only | No open admin port, no keys to manage. |
| 20 Nov | **Files -> S3 -> loader -> Postgres; SQS carries IDs only** | Replayable, auditable, PII contained. |
| 20 Nov | **Images built by GitHub Actions on native ARM, on version tags** | CodeBuild was blocked by a new-account limit; GitHub ARM runners are native and free for public repos. |
| 20 Nov | **API Gateway (HTTP API + VPC Link) as the public entry** | CloudFront is held until AWS verifies the new account; API Gateway gives an AWS HTTPS URL today, keeps the EC2 private, adds rate limiting. Switch to CloudFront later for WebSockets. |
| 20 Nov | **PII: own recognisers as the gate, Presidio + spaCy `en_core_web_sm` for names** | Checksum-validated rules are deterministic and cover IDs Presidio lacks (Emirates ID, UAN, native digits); spaCy finds mid-sentence English and Hinglish names. The small model keeps RAM low on the t4g.small. |
| 20 Nov | **PII vault in DynamoDB + KMS, not Postgres** | Lambda reaches it without a KMS VPC endpoint (about USD 7-8 a month saved); native TTL; the EC2 can write but never read; a dump of the app database leaks only masked text. |
| 20 Nov | **Raw ticket text in a short-lived `ticket_inbox`, deleted when masked** | The worker masks (keeps spaCy out of the API); raw text is never in `tickets`, which everything else reads. |
| 20 Nov | **AgentCore** Gateway + Policy + Observability in phases 5 to 7 | Managed tools and deterministic tool-call rules (tenant isolation). Runtime (zip deployment) under consideration for the agent. |

---

## 10. Operating it

| Task | Command (from the repo root, PowerShell) |
| --- | --- |
| Check a template | `.\scripts\cfn.ps1 validate <stack>` |
| Preview changes (no effect) | `.\scripts\cfn.ps1 plan <stack>` |
| Apply the reviewed change set | `.\scripts\cfn.ps1 apply <stack>` |
| Show outputs / failures | `.\scripts\cfn.ps1 output <stack>`, `.\scripts\cfn.ps1 events <stack>` |
| Delete a stack (asks for its name) | `.\scripts\cfn.ps1 delete <stack>` |
| Store secrets from `.env` in SSM | `.\scripts\put_secrets.ps1` |
| Release images | `git tag v0.x.y` then `git push origin v0.x.y` |
| Start / stop / check EC2 + RDS | `.\scripts\demo.ps1 start`, `stop`, `status` |
| Run locally | `docker compose up -d --build --wait` (see README) |

Deploy order: `network`, `security`, `data`, `iam`, `rds`, `ec2`, `apigw` (or `cloudfront` once allowed). Delete in reverse.

---

## 11. What is next

1. Done: release `v0.1.0`, `rds`, `ec2`, `apigw` (public URL).
2. Done: `scripts/check_phase2.py` gate (11/11). Next: `deploy.ps1` (pinned image versions via SSM).
3. CloudFront once AWS verifies the account (CloudFront, CodeBuild and Bedrock holds filed).
4. Phase 3 in progress: 3a masking done (CI green); 3b-1 intake, worker gate, re-scan,
   sender tokens, JSON logs and `eval_pii.py` written (not deployed). Next 3b-2 (needs
   approval): `vault.yaml` (DynamoDB table, vault KMS key, vault-reveal Lambda), EC2 role
   additions, CloudWatch logs + metric filters + alarms, `check_phase3.py`. Then 3c:
   multilingual NER. **Do not release a new image before 3b-2:** the worker now refuses to
   start without `PII_HMAC_KEY` and `VAULT_BACKEND`.
5. Phase 4 onwards: data loader (S3 -> masking -> Postgres), then the LangGraph agent and
   AgentCore (phase 5).

Open items: free disk space on the laptop; Bedrock support case; `OPENROUTER_API_KEY` into
SSM before phase 6; phase 3/4 data files still to be provided.
