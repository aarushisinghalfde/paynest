# Plan v2 - from working MVP to an operable support agent

**Date:** 21 Nov 2026 · **Starting point:** phases 0-9 built (v0.5.0: How-To agent with approved-answer library, past-resolution RAG, learning loop). Region: AWS Sydney only; India/UAE stay placeholders.

**How every phase runs:** build -> unit tests (+ mutation check of the new tests) -> replay on the real Q3 data -> you deploy (tag, restart; `cfn.ps1 plan`/`apply` for infra) -> a live check script -> the result goes to `results/gates.csv`. The next phase starts only when the gate passes.

| Phase | What | Why | Gate (how we verify) |
|---|---|---|---|
| **A. Operations dashboard** | `/dashboard` (admin token): classification (teams, confidence branches, which layer decided, customer pick vs final label), merges (duplicates, incidents, Jira links), resolution (answer tier: library / cache / RAG / template, auto vs review vs handed off, knowledge tasks written, library size), recent tickets with rule and reason. Two views: live agent tickets and the Q3 export. | You can see and explain what the agent does, and how much load it takes off the team | Unit tests on the aggregation; replay shows the Q3 numbers (201 wrong picks, 26 resubmits); `check_dashboard.py` against the live URL |
| **B. Knowledge import** | Admin upload page: KB articles (Confluence export as Markdown/HTML) and approved How-To answers (CSV) -> masked, chunked, versioned; the answer cache empties on a new KB version | The How-To agent gives real steps on day one instead of "see guide X" | Upload a sample article; the same question then answers with its steps; PII in an upload is masked |
| **C. Quality: evals + phase 7 gaps** | Replay the 200-ticket labelled set: classification accuracy and macro-F1 per language, routing, guard; fix dedupe precision (93% -> 95%) and the Meridian burst opening 2 incidents | Numbers you can defend; feeds the dashboard | `scripts/run_evals.py` writes `results/evals.json`; dedupe >= 95%; Meridian = 1 incident |
| **D. Operate it** | `deploy.ps1` (tag -> wait for images -> restart -> health -> checks); switch the cache to ElastiCache Valkey (stack written); OpenTelemetry collector -> X-Ray traces per ticket | One command to release; traces to debug a ticket end to end | One-command release completes; a trace per ticket in X-Ray |
| **E. AgentCore (optional)** | Package the agent graph as an AgentCore Runtime in Sydney (not touching `kioskClassDemo`) | The client's target platform | A ticket processed through the AgentCore endpoint matches the EC2 result |
| **F. Handover** | Update architecture, PRD status, deck results slide, runbook; decision log | Someone else can run it | Docs reviewed; all gates green |

**Not doing:** India/UAE deployment, write actions on the payroll engine, training models on ticket data.
