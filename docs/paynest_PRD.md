# PRD - Payce Support Assist (MVP v1)

## Document control

| Field | Value |
|-------|-------|
| Product | Payce Support Assist (repo: `paynest`) |
| Owner | Aarushi Singhal |
| Client | Ramco Payce Support (Priya Nair, Head of Support) |
| Status | MVP built; phases 0-9 in code, 0-7 live in AWS Sydney |
| Last updated | 2026-11-20 |
| Related | `paynest_Discovery_Note.md`, `paynest_SPIN_Sheet.md`, `solution_approach.md`, `architecture.md`, `lld.md`, `build_note.md` |

---

## 1) Problem statement

Support answers statutory questions from a KB that lags the payroll engine, tickets bounce because customers pick the wrong category (201 of 1,327), and repeats of known issues are worked as new tickets. SLA credits doubled in August (USD 3.9k -> 8.3k) on ~9% more volume. Tickets carry personal data (103 of 1,353), and the previous vendor chatbot failed on stale facts, cost and privacy.

## 2) Objective

Answer and route support tickets safely: mask personal data first, route by code, answer How-To in chat from approved sources, answer statutory questions by the date asked with a human approving, link repeats to incidents and Jira, and keep model spend capped and visible.

## 3) Goals and non-goals

## Goals

- G1. No personal data reaches a model, a log or another tenant.
- G2. Every ticket is routed by explicit rules with a rule id and a reason.
- G3. How-To questions get an answer in chat (cache, then approved guides), in the customer's language.
- G4. Statutory answers use the value in force on the question date and wait for human approval.
- G5. Repeats and bursts are linked (duplicate, incident, Jira) instead of re-worked.
- G6. Every draft passes an output guard before it is sent.
- G7. Model spend has a daily cap and a ledger.

## Non-goals (v1)

- Headcount reduction as a target.
- A voice bot.
- Any write action on the payroll engine (refund, approve, re-run).
- Training models on ticket data.
- Deployment in India or UAE regions (configs only; demo in Sydney).

---

## 4) Users and stakeholders

| User | Need |
|------|------|
| Customer HR admin (Deepa, Hassan) | Quick How-To answers, run status, statutory answers that cite the rule and date, no repeating themselves |
| L1 agent (Farhan) | Correct routing, a draft with sources, no PII copy-paste |
| Reviewer / L2 (Sandeep) | A queue of statutory and flagged drafts with the reason and sources |
| CFO (Anjali) | Cost per ticket, daily spend, a cap, an off switch |
| DPO (Karthik) | Data flow, masking, vault, retention, in-region processing |

## 5) User stories

- As a customer, when I ask "how do I download payslips", I get the right guide in chat at once, in my language.
- As a customer, when I write "payment delayed", I am asked one clarifying question, and my answer is read with my first message.
- As a customer, when I ask about the PF ceiling for July, I get July's value, not today's, and it names the rule.
- As a reviewer, I see each statutory draft with its sources and approve, edit or reject it.
- As the DPO, I can see that tickets are masked before any model call and that the app cannot decrypt the vault.
- As the CFO, I can see model cost per day and know it stops at the cap.

## 6) Scope

## In scope

- Chat page (customer) and review console (reviewer).
- Intake API with idempotency; SQS queue with dead-letter queue.
- PII gate (format-based masking, re-scan, quarantine), HMAC sender tokens, DynamoDB + KMS vault.
- Data loader for the Q3 export, KB, rules and process documents, with effective dates.
- LangGraph agent: classify, dedupe/incidents/Jira, YAML router, injection block.
- How-To flow: answer cache -> RAG over approved guides -> reply -> cache.
- Statutory drafting from the dated rule table; human review.
- Output guard (11 checks); customer view hides tokens and citation ids.
- Arabic, Hindi and Hinglish handling.

## Out of scope

- Voice, WhatsApp and phone channel integration (data loaded, channel not wired).
- Upload page for new data (phase 10).
- ElastiCache stack (phase 10; Redis via `REDIS_URL` today).
- Tracing to X-Ray and AgentCore deployment (phase 11).

---

## 7) Functional requirements

| ID | Requirement |
|----|-------------|
| FR1 | `POST /api/tickets` stores the ticket, keeps raw text only in a short-lived inbox, queues the id; the same Idempotency-Key returns the first ticket. |
| FR2 | The worker masks PII before any other step; a re-scan that finds a value quarantines the ticket with a holding reply. |
| FR3 | Raw values go to the vault encrypted with the ticket's context; the app role cannot decrypt. |
| FR4 | Language is detected (en, hi-Latn, hi, ar); prompt-injection phrasing is detected in all four. |
| FR5 | Classification: keywords -> similar past tickets -> a model only on disagreement; how-to phrasing with no problem signal goes to How-To. |
| FR6 | Dedupe needs an explicit reference, or a resubmit marker with similarity >= 0.8; 5 similar tickets in 3 h open an incident; Jira matches link the issue. |
| FR7 | The router applies `config/router.yaml` in order and records the rule id and reason. |
| FR8 | Greetings get a greeting; messages with too little detail get one clarifying question; follow-ups in the same conversation are read with the earlier turn. |
| FR9 | How-To: answer cache (by meaning, per region, language and KB version) first; on a miss, approved guide titles; the sent answer is cached. |
| FR10 | Statutory and P1 and known-issue routes: draft from all approved sources and tools; a human approves before sending. |
| FR11 | Auto-sent replies never quote a statutory figure. |
| FR12 | Every draft passes the output guard or goes to review with the problems listed. |
| FR13 | The customer never sees mask tokens or citation ids. |
| FR14 | Model calls are logged to a cost ledger; calls stop at the daily cap. |

## 8) Non-functional requirements

- Privacy: masked text only in prompts, logs and checkpoints; vault decrypt only by the audited reveal Lambda.
- Region: all processing in one AWS region; India/UAE placeholders refuse to deploy.
- Reliability: checkpoint after every step; a crashed worker resumes at the failed step; failed messages go to the DLQ after 3 tries.
- Cost: daily model cap (USD 0.50 in the demo); per-ticket cost recorded.
- Latency: chat polls every 2 s; template and cache answers need no model call.
- Operability: infra as CloudFormation, plan before apply; release images built only from version tags.

## 9) Data requirements

| Data | Source | Use |
|------|--------|-----|
| Tickets (3 formats) | `data/tickets_export.json` | final labels, similar tickets, dedupe, evaluation |
| Tenants | `data/customers.csv` | region (IN/UAE), tier |
| Statutory rules | `integrations/statutory_rules.json` | dated values (`get_rate`) |
| KB articles | `data/kb_articles.json` | guide titles; old excerpts closed on the rule date |
| Process docs | `process/*.md` | reviewer-facing guidance |
| Jira | `data/jira_escalations.json` | known-issue links |

## 10) Taxonomy (v1)

Teams: How-To, Payroll, Statutory, Integration, Leave & Attendance, Access / Login, Reports, Onboarding, Billing. Routes: reply, review, queue, block, incident, duplicate, chat, ask.

## 11) Success metrics

## MVP proof metrics

| Metric | Result |
|--------|--------|
| PII leaks after load (14 tables, 903 raw values) | 0 |
| Phase 3 gate in AWS | 12 / 12 |
| Phase 5 gate in AWS (chat -> reply, idempotency, checkpoints, DLQ) | 4 / 4 |
| Output guard on planted drafts | 20 / 20 bad caught, 10 / 10 good passed |
| Chat cases replayed on real knowledge | 9 / 9 |
| Dedupe on real resubmits | 26 / 28 (93%; target 95%) |

## Pilot metrics (post-MVP)

- How-To answered in chat without reopen; first-try routing rate; repeats linked; statutory reopen rate; credits per month; model cost per resolved ticket in peak week.

## 12) Risks and mitigations

- Stale or wrong statutory answer. **Mitigation:** dated rule table, review route, guard checks numbers against sources.
- Personal data leak. **Mitigation:** mask before models, re-scan and quarantine, vault the app cannot read, guard PII check.
- Prompt injection. **Mitigation:** 4-language detector, block route, no write tools.
- Cost spike at peak. **Mitigation:** cache and templates first, model only on disagreement, daily cap and ledger.
- Over-eager dedupe or incidents. **Mitigation:** strict dedupe rule; known gaps tracked (93% precision; Meridian split).

## 13) Assumptions made

- The rule table equals what `/statutory/rates` returns.
- Guide titles are approved for customers; process docs are internal.
- Naive timestamps are IST (proven on event order for all three ticket systems).

### Assumption falsifiers

- Engine and rule table disagree on any value or date.
- Support says a guide is wrong for some tenants.
- An event sequence breaks when read as IST.

## 14) Rollout plan

1. Demo in Sydney with the Q3 data (now).
2. Shadow mode on live tickets: drafts to reviewers only.
3. How-To auto-reply for one region and language, with the guard and cap.
4. Statutory drafts for reviewers; measure reopens.
5. Production in the home regions after the DPIA.

Rollback: switch drafting off (`DRAFTING=off`) to fall back to acknowledgements; the router and masking keep running.

## 15) Acceptance criteria

- All gates in `results/gates.csv` pass for the release.
- `scripts/check_chat.py` passes 8 / 8 against the live URL.
- No statutory figure in any auto-sent reply in the replay.
- DPO walkthrough of the data flow completed.
