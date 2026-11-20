# Solution and approach - Payce Support Assist

**Status:** MVP built (phases 0-9 in code; 0-7 live in AWS Sydney)
**Date:** 2026-11-20
**Client brief:** `Case.md` and `data-room/` in `niti007/paynest-support-discovery`
**Discovery:** [`paynest_Discovery_Note.md`](paynest_Discovery_Note.md) · **PRD:** [`paynest_PRD.md`](paynest_PRD.md) · **Build write-up:** [`build_note.md`](build_note.md)

---

## 1. What we are building

A support assistant for Ramco Payce's India and UAE customers that does the safe things automatically and puts a human on everything risky.

**Primary user:** Priya Nair, Head of Support, and her agents. **Customers:** HR admins such as Deepa (Kestrel Logistics, India) and Hassan (Gulf Horizon, UAE).

**One sentence, in her language:** "Answer the how-to questions straight away, route the rest to the right team first time, and never let a bot give a wrong PF or WPS number."

---

## 2. Why this problem (evidence)

| Evidence | Where | What it means |
|----------|-------|---------------|
| PF 15,000 -> 25,000 from 1 Aug; WPS v2 -> v3 from 15 Jul | `statutory_rules.json`; transcripts 04, 05, 09 | Answers must be dated to the question, not to today |
| 201 / 1,327 customer picks wrong; 111 tickets moved more than once | `tickets_export.json` events | Route by code, not by the dropdown |
| Credits USD 3.9k Jul -> 8.3k Aug -> 7.0k Sep | `sla_breaches_q3.csv`, cost sheet | The August spike follows the PF change |
| How-To is 406 / 1,353 tickets (30%) | final labels | The safe place to automate |
| PII in 103 tickets; May payslip incident | masking run; `security/` | Mask before anything else |
| Vendor pilot: stale TDS, invented gratuity, 19 s p95, USD 41.2k June | `vendor_pilot/` | Grounding, latency, cost cap and handoff are the bar |

**Not in the brief (we ask, we do not invent):** cost of one wrong statutory answer, the share of August reopens that were PF/WPS, the real run-status limits in production.

---

## 3. Ranked shortlist

| Rank | Problem | Build in v1? |
|------|---------|--------------|
| 1 | Statutory answers lag rule changes | Yes: dated rule table + review |
| 2 | Wrong category, bouncing tickets | Yes: keyword + similar-ticket classifier, YAML router |
| 3 | Repeats of known issues and bursts | Yes: dedupe, incidents, Jira links |
| 4 | How-To volume | Yes: cache -> RAG -> chat answer |
| 5 | PII in tickets | Yes: first step of every flow |
| - | Voice bot, headcount target | No (no supporting data) |

---

## 4. MVP boundary

### Build
- Chat page and review console; intake API; queue and DLQ.
- PII gate, sender tokens, vault (DynamoDB + KMS, app cannot decrypt).
- Loader for tickets, tenants, rules, KB and process docs with effective dates.
- LangGraph agent with checkpoints; classifier; dedupe/incidents/Jira; router; injection block.
- How-To flow with answer cache; statutory drafts for review; output guard.

### Do not build
- Any write call to the payroll engine.
- A model call on raw text.
- Auto-sent statutory figures.

### Later
- ElastiCache stack, upload page, X-Ray traces, AgentCore runtime, full evals, demo script (phases 10-13).

---

## 5. Workflow

1. Customer posts a chat message (with a conversation id). The API stores it and queues the id.
2. **PII gate:** mask by format (PAN, Aadhaar, IBAN, Emirates ID, phones, emails, names); raw values to the vault; re-scan; quarantine on a miss.
3. **Normalise:** language, injection rules, greeting / thanks / vague, follow-up context from the same conversation.
4. **Tenant:** India or UAE rules.
5. **Classify:** keywords -> similar tickets -> model on disagreement; how-to phrasing -> How-To.
6. **Dedupe:** duplicate, incident, Jira.
7. **Route:** first matching rule in `config/router.yaml`.
8. **Draft:** greeting / question / acknowledgement templates; How-To: cache -> guides; review routes: all sources + tools (dated rates, run status).
9. **Guard:** 11 checks; a failure goes to review.
10. **Send:** reply (tokens and citation ids hidden from the customer) or wait for the reviewer; How-To answers are cached.

**Auto-reply does not mean a statutory answer.** Auto-sent replies cite guides and run status only.

---

## 6. Taxonomy

Nine teams from the SOP (How-To, Payroll, Statutory, Integration, Leave & Attendance, Access / Login, Reports, Onboarding, Billing). Eight routes: reply, review, queue, block, incident, duplicate, chat, ask.

---

## 7. Where the model stops and code starts

| Step | Code or model | Why |
|------|---------------|-----|
| Masking, re-scan | Code (regex by format + optional Presidio NER) | Deterministic; must run before any model |
| Language, injection, greeting, vague | Code | Cheap, testable in 4 languages |
| Classification | Code first; model only when keywords and similar tickets disagree | Cost and predictability |
| Dedupe, incidents, Jira | Code | Explainable thresholds |
| Routing | Code (YAML rules) | Every decision needs a rule id and reason |
| Statutory value | Code (`get_rate` by date) | A model must never produce a number |
| Draft wording | Model when available; fixed cited fallback otherwise | Language and tone; facts come from code |
| Output guard | Code | Must not depend on the model it checks |

---

## 8. Patterns

### Routing
The YAML router: first match wins, each rule names its facts, the reason is shown to reviewers and in the chat.

### Evaluator (guard)
Every draft is evaluated by deterministic checks; a failed draft is not retried by the model but sent to a human with the problems.

### Cache-augmented generation
How-To answers already given are reused by meaning before retrieval; the cache key includes the KB version so a rule change empties it.

### Checkpointed graph
LangGraph with Postgres checkpoints: resume at the failed step after a crash; idempotency keys and unique reply versions stop double sends.

---

## 9. Two models

| Model | Role |
|-------|------|
| `meta-llama/llama-3.1-8b-instruct` (rung 0) | Classification tie-breaks |
| `google/gemini-2.5-flash` (rung 1) | Drafting the wording of answers from the given sources |

Via OpenRouter while Bedrock is on hold for the account; one client, JSON output, cost ledger, USD 0.50/day cap; classification retries once one rung up.
