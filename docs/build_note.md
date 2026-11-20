# Build note - Payce Support Assist MVP

**Max length:** two pages
**Written after the MVP exists** (phases 0-9 built; 0-7 live in AWS Sydney; v0.4.2). Discovery note: [`paynest_Discovery_Note.md`](paynest_Discovery_Note.md).

---

## Problem we built for

Statutory answers lag the payroll engine, tickets bounce because customers pick the wrong category, and repeats of known issues are re-worked, so SLA credits doubled in August on ~9% more volume, while tickets carry personal data that must never reach a model.

## Code vs model table

| Step | Code or model? | Why | Model / temp | Schema |
|------|----------------|-----|--------------|--------|
| 1. Mask PII, re-scan | Code | Must run before any model; deterministic | - | `MaskResult` (text, values, counts) |
| 2. Language, injection, greeting/vague, how-to | Code | Cheap and testable in 4 languages | - | state fields |
| 3. Classify | Code; model only when keywords and similar tickets disagree | Cost and predictability | llama-3.1-8b, temp 0 | `{team, confidence, second, is_injection}` validated |
| 4. Dedupe, incident, Jira | Code | Explainable thresholds | - | `Recent`, incident rows |
| 5. Route | Code (YAML) | Rule id + reason for every decision | - | `{route, rule, reason, queue}` |
| 6. Statutory value | Code (`get_rate` by date) | A model must never produce a number | - | rule row |
| 7. How-To answer | Cache, then retrieval (code); wording by model or fallback | Repeat questions cost nothing | gemini-2.5-flash, temp 0 | `{reply, citations, answerable}` |
| 8. Guard | Code | Must not depend on the model it checks | - | `{ok, problems[]}` |

## Patterns used

| Pattern | Where in the workflow | What breaks without it |
|---------|----------------------|------------------------|
| Routing | `config/router.yaml` after classify/dedupe | Statutory answers auto-sent; injections answered; repeats re-worked |
| Evaluator | `agent/guard.py` on every draft | A wrong number, a leaked ID or a promise reaches a customer |
| Prompt chaining | classify -> route -> retrieve -> draft -> guard | One prompt doing everything cannot be tested or capped |
| Cache-augmented generation | answer cache before RAG (How-To) | Every repeat question pays for retrieval and a model call |

## Two-model split

| Model | Role | Justification |
|-------|------|---------------|
| Cheap: `meta-llama/llama-3.1-8b-instruct` | Classification tie-breaks only | USD 0.02 in / 0.04 out per M tokens (cheapest provider); called only on disagreement |
| Stronger: `google/gemini-2.5-flash` | Wording of drafts from given sources, in 4 languages | USD 0.30 in / 2.50 out per M tokens; multilingual; JSON output |

Both via OpenRouter while Bedrock is on hold for the account (phase 0 outcome). Switching is the `provider` line in `config/models.yaml`.

## Temperatures

| Task type | Temperature | Why |
|-----------|-------------|-----|
| Classification | 0 | Same input, same answer |
| Customer-facing draft | 0 | Facts come from sources; no creativity wanted |

## Cost line

| Item | Value |
|------|-------|
| Draft call (gemini-2.5-flash): ~1,500 in + ~250 out tokens | 1,500 × 0.30/1M + 250 × 2.50/1M ≈ **USD 0.0011** |
| Classifier tie-break (llama-3.1-8b at the dearest listed provider, USD 0.22/M): ~600 in + ~60 out | ≈ **USD 0.00015** |
| Worst case per ticket (tie-break + its retry + draft) | ≈ **USD 0.0025** |
| Volume (all customers) | ~15,000 tickets a month (cost sheet: 14,520-15,841 in Q3) |
| Peak window (25th-3rd), assumed 60% of the month | ~9,000 tickets × 0.0025 ≈ **USD 23** |
| Month at worst case | ~15,800 × 0.0025 ≈ **USD 40** |
| AWS demo infrastructure | ~USD 1.40/day running (EC2 + RDS + EIP) plus ~USD 4/month fixed (see `architecture.md` §8) |
| Assumptions | Every ticket worst case; greetings, clarifying questions, cache hits and templates actually make no model call; prices as listed on OpenRouter, Nov 2026 |

Next to ~USD 90k a month of support cost, model spend is a rounding error; the real cost lever is fewer reopens, bounces and credits. The cap (USD 0.50/day in the demo) stops calls, and the system falls back to cited templates.

## Structured output & failure

- Schema validation: JSON mode plus `agent.classifier.validate` and drafter field checks; citations must be retrieved ids.
- When validation fails: classification retries once one rung up, then keeps the keyword and similar-ticket answer; drafting falls back to the cited fallback or a template; never an uncited answer.
- When the system cannot answer: "Thanks for contacting Payce Support. Your ticket {ref} is with our {team} team..." (template), or a clarifying question for vague messages; a statutory draft waits in `/review`.

## Real-shaped input

- The real Q3 export: 1,353 tickets in three formats with mixed time zones, 4 languages (156 Hinglish, 64 Hindi, 76 Arabic), 103 with personal data, 26 resubmits, 65 partner tickets with only a company name.
- `tests/fixtures/guard_cases.json`: 20 planted bad drafts and 10 good ones.
- `scripts/check_chat.py`: 8 live chat cases including Arabic and an injection.

## Code layout reminder

- UI: `web/` (React: `/chat`, `/review`)
- API and intake: `api/`, `intake/`; worker: `worker/`
- Agent (graph, classifier, router, retrieval, tools, drafter, guard, cache): `agent/`
- PII: `pii/`; data loader: `loader/`; infra: `infra/cfn/`; checks: `scripts/`

## The thing that broke that we did not expect

Real IDs fail their checksums. The first masking gate validated PAN and Aadhaar by checksum, as the textbooks say, and all 38 PANs in the real export leaked. We now mask by format and use checksums only to pick the label. Second surprise: the export's top-level category is the final label, not the customer's pick; the pick is on the first event (201 of 1,327 wrong). Third: How-To questions such as "how do I download payslips" tie How-To and Payroll on keywords and fell to the triage queue; a how-to phrasing rule fixed it.

## What we would build next

- ElastiCache (Valkey) for the answer cache, and an upload page for new data (phase 10).
- One-command deploy, X-Ray traces, AgentCore runtime (phase 11).
- Full evals on the relabelled 200-ticket set (phase 12); demo script (phase 13).
- Fix the two known gaps: dedupe precision 93% vs 95%; the Meridian burst opened 2 incidents instead of 1.
- From the client: the cost of one wrong statutory answer, `/statutory/rates` access, and the DPIA for production regions.
