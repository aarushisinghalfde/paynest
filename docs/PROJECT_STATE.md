# Project state - Paynest / Payce Support Assist

The one status file. Updated 23 Nov 2026. Plan history: [plan_v2.md](plan_v2.md). How to run things: [operate.md](operate.md). Why it is built this way: [architecture.md](architecture.md).

## Current status
- **v0.9.0 released; all gates passed at 00:35 IST** (data 8/8, chat 8/8, console and dashboard, knowledge import, phases 6/7/9 live 5/5, evals).
- **Live URL down since the `ec2` stack update (00:56).** The update replaced the server (new id `i-07979c18f1d440d30`, new private IP), but API Gateway still points at the old IP. Fix: `cfn.ps1 plan/apply apigw`, then `run_checks.ps1` (P0 below).
- Tests: 447 pass locally, 8 skipped (FastAPI, LangGraph and Presidio are not installed here). CI runs all of them, and CI was green for v0.9.0.

## Architecture (short)
- **Public entry:** API Gateway (HTTPS) → VPC Link → one EC2 `t4g.small` running Docker compose:
  - `api` (FastAPI)
  - `worker` (LangGraph ticket graph)
  - `web` (React)
  - `mock-payroll-api`
  - `otel-collector`
- **Services:** RDS Postgres (private subnets), SQS, Redis (Upstash; Valkey optional), PII vault (DynamoDB + KMS, the server can write but never read).
- **Images:** built by GitHub Actions on `v*` tags and stored in ECR.
- **Ticket path:** mask PII → normalise → tenant → classify (keywords + similar past tickets, model only when they disagree) → dedupe / incident / Jira → route (`config/router.yaml`) → draft (library → cache → RAG → template, plus tool facts) → 12 output checks → send, or wait for a person.
- **Models:**
  - OpenRouter, masked text only;
  - Bedrock client ready but the account is blocked;
  - AgentCore runtime for the model steps, stack written but not applied.
- **Region:** Sydney only. India and UAE are placeholders that refuse to deploy.

## MVP checklist (the support workflow)
| Stage | State |
|---|---|
| Ticket intake (chat/API, idempotency key, conversations) | Working, live |
| Input validation | Working (size limits, tenant check, injection block) |
| PII detection and masking (10 types, 4 languages, vault) | Working, live; recall 100% on the eval |
| Ticket storage | Working (RDS; raw text only briefly in an inbox, then deleted) |
| Classification | Working: 100% on the labelled set, 99.2% on the time split |
| Routing (13 rules, statutory always reviewed) | Working |
| Context retrieval (approved library, answer cache, BM25 RAG, dated rules, payroll API) | Working |
| AI response drafting (model or fixed wording) | Working; falls back to fixed wording on model failure |
| Response validation (12 checks) | Working; 200/200 on the eval |
| Human review, approve/edit/reject | Working (`/review`; named reviewer tokens; "English + why" shows the translation, confidence, rule and sources) |
| Response delivery | Working (chat) |
| Audit tracking | Working: decision record per ticket, review outcome, sent replies, cost ledger, vault reveal log |
| Support-lead console (outcomes, confidence, answer path, translation) | Working, live in v0.9.0 |
| Traces (X-Ray) | Built; the collector is on the new server; `check_traces.py` not passed yet |
| AgentCore model steps | Built; stack not applied |
| Bedrock models | Blocked (account hold) |
| Faithfulness score | Built; not run (`run_evals.py --with-model`) |

## In progress
Restoring the live URL after the server replacement. Then the steps under Next action.

## Blockers
- **Bedrock:** every model returns "Operation not allowed" on account 665651551863. An AWS Support reply is drafted; this needs AWS or the account owner.
- **CloudFront:** waiting on account verification (API Gateway is used instead).

## Important decisions
- The model only ever sees masked text. Statutory figures always go to a person. A failed model draft falls back to fixed wording.
- AgentCore hosts the model steps only (PUBLIC mode, no database access). The graph, database and vault stay in the VPC.
- The provider is switched with SSM `MODEL_PROVIDER` (openrouter, bedrock or agentcore) plus a restart, with no release.
- Releases go through `deploy.ps1` only: it waits for the images, then for the version in health, then runs the gates.
- Scripts find the server by its Name tag, never by instance ID. The `ec2` update replaced the server.

## Deferred improvements (backlog)
**P0**
- The live URL is down after the server replacement: re-apply the `apigw` stack.

**P1 (before a real pilot)**
- **Reviewer identity: done in code.** Named reviewer tokens (`REVIEWER_TOKENS`): each approval is recorded under the token's owner. Full SSO (Cognito) is P2.
- **Fixed in code:** the `ec2` stack keeps the running server's AMI (`auto:current-ami`). `cfn.ps1 plan` warns in red before any replacement of the server, database, cache or vault table, and `apply ec2` says when `apigw` must be re-applied.
- **Fixed in code, apply with `cfn.ps1 plan/apply rds`:** RDS keeps 7 days of backups (was 1). This modifies the instance in place, with no downtime for this change.
- **Alarms: needs your email.** Set `AlarmEmail` in `params/demo.json`, then `cfn.ps1 apply observability` (see operate.md).

**P2**
- Valkey instead of Upstash (stack written).
- CloudFront once the account is verified.
- Embedding retrieval, if the faithfulness score shows misses.
- One live check per review action.

**P3**
- Write actions on the payroll engine.
- India and UAE deployments.
- Cross-account Bedrock.
- Richer console analytics.

## Evidence

<!-- evidence:start -->

Latest result of each gate (75/76 passing), written by `scripts/evidence.py` from `results/gates.csv`.

| Phase | Gate | Result | When (UTC) | Detail |
|---|---|---|---|---|
| 0 Foundations | embedding_model_decided | PASS | 2026-11-19T11:13 | multilingual-e5 on the EC2 (no in-region Bedrock embedding passed) |
| 0 Foundations | guardrails_checked | PASS | 2026-11-19T11:13 | works: all seeded IDs masked in EN/HI/AR, injection blocked, benign passed |
| 0 Foundations | model_ladder_decided | **FAIL** | 2026-11-19T11:13 | DECIDE: no rung works in-region. Rungs that leave the region: none |
| 0 Foundations | services_available | PASS | 2026-11-19T11:13 | ec2,rds,valkey,sqs,kms,xray |
| 1 Infra | api_health | PASS | 2026-11-19T23:40 | ap-southeast-2 |
| 1 Infra | api_ready | PASS | 2026-11-19T23:40 | postgres, redis, queue |
| 1 Infra | migrations_extensions | PASS | 2026-11-19T23:40 | extensions pg_trgm, vector |
| 1 Infra | mock_payroll_health | PASS | 2026-11-19T23:40 | health 200 |
| 1 Infra | web_pages | PASS | 2026-11-19T23:40 | /chat and /review load |
| 1 Infra | worker_receives_message | PASS | 2026-11-19T23:40 | message cfb40fd1 processed |
| 2 Intake | aws_account | PASS | 2026-11-20T13:04 | 665651551863 |
| 2 Intake | ec2_not_public | PASS | 2026-11-20T13:04 | 13.211.69.24:80 refuses direct traffic; no SSH; no 0.0.0.0/0 |
| 2 Intake | encrypted_at_rest | PASS | 2026-11-20T13:04 | queue KMS, bucket aws:kms |
| 2 Intake | images_released | PASS | 2026-11-20T13:04 | app and web v0.1.0 |
| 2 Intake | no_nat_gateway | PASS | 2026-11-20T13:04 | none in vpc-06fcc5ff34d6ef5c4 |
| 2 Intake | public_api_ready | PASS | 2026-11-20T13:04 | postgres, redis, production queue ok |
| 2 Intake | public_home | PASS | 2026-11-20T13:04 | https://whps24ardd.execute-api.ap-southeast-2.amazonaws.com |
| 2 Intake | rds_private | PASS | 2026-11-20T13:04 | private, encrypted, PostgreSQL 17.11, available |
| 2 Intake | secrets_in_ssm | PASS | 2026-11-20T13:04 | REDIS_URL |
| 2 Intake | stacks_complete | PASS | 2026-11-20T13:04 | 7 stacks complete |
| 2 Intake | worker_in_aws | PASS | 2026-11-20T13:04 | message ea96ff67 processed on the EC2 |
| 3 PII | admin_cannot_decrypt | PASS | 2026-11-20T14:37 | AccessDenied for your admin role (only vault-reveal can decrypt) |
| 3 PII | alarms_exist | PASS | 2026-11-20T14:37 | pii-blocked=OK, pii-ner-off=OK, tickets-dlq-not-empty=OK, worker-failures=OK |
| 3 PII | aws_account | PASS | 2026-11-20T14:37 | 665651551863 |
| 3 PII | ec2_cannot_read_vault | PASS | 2026-11-20T14:37 | GetItem and Decrypt both AccessDenied on the EC2 |
| 3 PII | inbox_deleted | PASS | 2026-11-20T14:37 | 0 raw inbox rows for the 2 tickets |
| 3 PII | leak_seeded_local | PASS | 2026-11-20T14:37 | 0 raw values in 72 seeded tickets |
| 3 PII | logs_have_no_values | PASS | 2026-11-20T14:37 | ticket_masked logged; 0 events contain raw values |
| 3 PII | presidio_layer_on | PASS | 2026-11-20T14:37 | presidio |
| 3 PII | public_ticket_masked | PASS | 2026-11-20T14:37 | 2 tickets masked; first: {'PAN': 1, 'IFSC': 1, 'NAME': 1, 'ACCOUNT': 1} |
| 3 PII | reveal_right_ticket | PASS | 2026-11-20T14:37 | 4 tokens + sender email revealed for the right ticket |
| 3 PII | reveal_wrong_ticket | PASS | 2026-11-20T14:37 | unknown ticket not_found; other ticket gives not_found, never this ticket's value |
| 3 PII | stacks_complete | PASS | 2026-11-20T14:37 | vault, observability complete |
| 4 Data | labelled_set_saved | PASS | 2026-11-22T19:18 | 200 tickets, 9 teams, languages ['ar', 'en', 'hi', 'hi-Latn']; relabel pending |
| 4 Data | leak_scan_all_tables | PASS | 2026-11-22T19:18 | 903 raw values, 14 tables, leaks 0; 0 tickets quarantined |
| 4 Data | pf_wage_ceiling_by_date | PASS | 2026-11-22T19:18 | day before 2026-08-01: ['kb_excerpt']; from 2026-08-01: ['rule']; get_rate INR 15,000 per month -> INR 25,000 per month |
| 4 Data | routing_tables | PASS | 2026-11-22T19:18 | demo -> ['ap-southeast-2']; production -> India ap-south-1, UAE me-central-1: True |
| 4 Data | tenants_tagged | PASS | 2026-11-22T19:18 | 60 tenants with a home region; 0 untagged; 0 ticket tenants missing |
| 4 Data | ticket_count | PASS | 2026-11-22T19:18 | 1353 unique tickets (expected 1353) |
| 4 Data | timestamps_utc | PASS | 2026-11-22T19:18 | 1353/1353 tickets have a UTC creation time |
| 4 Data | wps_file_format_by_date | PASS | 2026-11-22T19:18 | day before 2026-07-15: ['kb_excerpt']; from 2026-07-15: ['rule']; get_rate SIF v2 (14 columns) -> SIF v3 (16 columns, new EDR layout) |
| 5 Agent | chat_to_reply | PASS | 2026-11-20T15:43 | replied in the chat (queue, team How-To) |
| 5 Agent | checkpoints_saved | PASS | 2026-11-20T15:43 | 11 checkpoint rows for thread a1089b7a |
| 5 Agent | idempotent_post | PASS | 2026-11-20T15:43 | 20 posts -> 1 ticket (1 created, 19 repeats) |
| 5 Agent | poison_to_dlq | PASS | 2026-11-20T15:43 | unknown ticket id failed 3 times and moved to tickets-dlq |
| 6 Classify | phase6_classify_live | PASS | 2026-11-22T19:21 | 7/7 to the right team; wrong: none |
| 7 Dedupe/incident | phase7_duplicate_live | PASS | 2026-11-22T19:21 | first: reply; resubmit: duplicate (output guard: uncited_answer) |
| 7 Dedupe/incident | phase7_incident_live | PASS | 2026-11-22T19:21 | routes: ['incident', 'incident', 'incident', 'incident', 'incident'] |
| 8 Chat | chat_arabic_guide | PASS | 2026-11-22T19:18 | route reply · replied · 'أهلاً بك! يمكنك تحميل كشوف الرواتب لجميع الموظفين دفعة واحدة. هل تحاول تنزيل كشوف الرواتب لشهر معين، أم لعدة أ' |
| 8 Chat | chat_greeting | PASS | 2026-11-22T19:18 | route chat · replied · "Hi! I'm the Payce Support assistant. Ask me about payroll runs, payslips, statutory rules or anything else in " |
| 8 Chat | chat_howto_guide | PASS | 2026-11-22T19:18 | route reply · replied · 'The guide for this is “Downloading payslips in bulk” (KB-0105); it has solved 39 similar questions. Which part' |
| 8 Chat | chat_injection_blocked | PASS | 2026-11-22T19:18 | route block · replied · 'Thanks, we have received your message (3085fb72). A specialist will review it and reply.' |
| 8 Chat | chat_pf_september_review | PASS | 2026-11-22T19:18 | route review · waiting_review · '' |
| 8 Chat | chat_run_status | PASS | 2026-11-22T19:18 | route reply · replied · 'The status of payroll run PR-202609 is "processing" and the current stage is "bank_file_generated". Is there a' |
| 8 Chat | chat_thanks | PASS | 2026-11-22T19:18 | route chat · replied · "You're welcome! Anything else I can help with?" |
| 8 Chat | chat_vague_asks_back | PASS | 2026-11-22T19:18 | route ask · replied · "I'd like to help with that. Could you tell me a little more: which payroll month, how many employees are affec" |
| 9 Safety | phase9_pii_never_sent | PASS | 2026-11-22T19:21 | stored masked: True; leaked: none; replied: True |
| 9 Safety | phase9_statutory_review | PASS | 2026-11-22T19:21 | team Statutory, route review, waiting_review |
| A Dashboard | dashboard_live | PASS | 2026-11-22T19:19 | HTTP 200; 150 tickets, rules ['(none)', 'R01-injection', 'R03a-smalltalk', 'R03b-too-vague', 'R04-incident', 'R05-duplicate'], auto-answered |
| A Dashboard | dashboard_needs_token | PASS | 2026-11-22T19:19 | no token -> HTTP 401 |
| A Dashboard | dashboard_q3_history | PASS | 2026-11-22T19:19 | HTTP 200; tickets 1353, wrong picks 201, resubmits 26 (want 1353, 201, 26) |
| B Knowledge | knowledge_import | PASS | 2026-11-22T19:20 | HTTP 200; {'kb_id': 'KB-GATE-1', 'title': 'Exporting the audit trail (gate test article)', 'chunks': 1, 'topic': 'howto', 'masked': 1, 'new_ |
| B Knowledge | knowledge_masked | PASS | 2026-11-22T19:20 | listed True; masked {'EMAIL': 1} |
| B Knowledge | knowledge_used_by_agent | PASS | 2026-11-22T19:20 | reply: "Here's how, from the Payce guide “Exporting the audit trail (gate test article)” (KB-GATE-1):\nTo export the audit trail:\n1. Open R |
| B Knowledge | knowledge_withdraw | PASS | 2026-11-22T19:20 | HTTP 200 |
| C Evals | classify_accuracy | PASS | 2026-11-22T19:21 | 100.0% (customer pick 88.0%), macro-F1 1.000; lowest language ar 100% |
| C Evals | dedupe_precision | PASS | 2026-11-22T19:21 | 26/26 predicted duplicates correct (100%); recall 100% of 26 resubmits |
| C Evals | guard_pass_rate | PASS | 2026-11-22T19:21 | 200/200 drafts passed (100%); problems none |
| C Evals | meridian_incident | PASS | 2026-11-22T19:21 | 1 incident(s) for 33 tickets, opened at ticket 5; 30 attached; 0 other incidents |
| C Evals | sent_replies_clean | PASS | 2026-11-22T19:21 | 0 sent replies with PII or unknown tokens |
| C Evals | statutory_never_auto | PASS | 2026-11-22T19:21 | 0 of 19 Statutory tickets answered without a person |
| G Console | console_approval_record | PASS | 2026-11-22T19:19 | 17 approval tickets; first dc461ef5: rule R07-statutory, answered by model, guard ok True |
| G Console | console_arabic_translated | PASS | 2026-11-22T19:19 | ticket b0c8bbac: How can I download payslips for all employees at once? |
| G Console | console_buckets_add_up | PASS | 2026-11-22T19:19 | HTTP 200; 150 tickets, buckets resolved 32, approval 17, approved 0, human 64, merged 11, chat 26 |
| G Console | console_lead_read_only | PASS | 2026-11-22T19:19 | lead: console HTTP 200, review queue HTTP 401 |
| G Console | console_resolved_record | PASS | 2026-11-22T19:19 | 32 resolved tickets; first 38820849: rule R99-default, answered by model, guard ok True |

Evals (2026-11-22T19:21): classification 1.0 on 200 labelled tickets (customer pick 0.88), macro-F1 1.0; faithfulness not run (needs `--with-model`).

<!-- evidence:end -->

## Next action
1. `.\scripts\cfn.ps1 plan apigw`, then `apply apigw`.
2. `.\scripts\run_checks.ps1`.
3. `python scripts\check_traces.py`.
4. `cfn.ps1 plan/apply agentcore`, then `check_agentcore.py`.
5. `run_evals.py --with-model --record`.
6. The P1 items above.
