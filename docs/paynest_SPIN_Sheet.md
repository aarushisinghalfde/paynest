# SPIN discovery sheet - Ramco Payce (support assistant)

## Problem statement

Leadership asked for "a ChatGPT chatbot that cuts support headcount by 30%". The data says the cost is not agent speed: it is statutory answers that lag the payroll engine, tickets that bounce because the category is picked wrong, and repeats of known issues. A chatbot grounded on the current KB would repeat the vendor pilot's failures. The right first build is an assistant that routes by code, answers How-To safely, answers statutory questions by date with a human in the loop, and never lets personal data reach a model.

---

## Decision makers

### S - Who needs to decide or act?

| Person | Decides | What they need to hear |
|--------|---------|------------------------|
| Rohan Mehta, CEO | Sponsor; board narrative | An honest answer to the 30% ask: cost per ticket and credits first, headcount as an outcome |
| Anjali Krishnan, CFO | Budget and the spend cap | Cost per resolved ticket in peak week, a daily spend view, an off switch |
| Priya Nair, Head of Support | Owner of the workflow | Agents keep their jobs; fewer reopens and bounces; proper handoff with the conversation |
| Karthik Subramanian, DPO | DPIA sign-off | What data goes in, where it is processed, what comes out, who sees the logs |
| Meera Iyer, Eng Manager | API access | Read-only, within the 30/min run-status limit, no new work on her team |

---

## Decision pressures

### P + I - What pressure is shaping their choices?

### 1) Statutory change vs a static KB
Rules change on a date (PF 1 Aug, WPS 15 Jul); the KB has one version. Agents and any bot grounded on it give the old number for a month. Implication: reopens, credits, and an employer relying on a wrong figure for a filing (DPO's worst case).

### 2) Peak-week economics
Most of the month's work lands between the 25th and the 3rd. Per-seat or per-message pricing breaks the cap exactly then (CFO: "if your average is two cents but peak is eight, I'm budgeting the eight").

### 3) Trust after two incidents
The May payslip leak and the vendor pilot (wrong TDS slabs, invented gratuity figure, US sub-processor, 90-day logs nobody agreed to). Any proposal is judged against those.

### 4) Operability
Support owns the KB with one person (Arvind); Engineering owns the engine and does not want more work; L2 runs payroll week in Slack.

---

## Boundaries and constraints

### J - What is off-limits in v1?

- Write access to the payroll engine (read-only since May; Meera).
- Personal data reaching a model or leaving the region (DPDP Act 2023, UAE PDPL; Karthik).
- Training or improving a model on ticket data without a contract clause.
- A statutory figure sent to a customer without a human.
- Uncapped or per-seat AI pricing.
- More than 30 run-status calls a minute per tenant.

---

## Success criteria

### N - How will Priya and Anjali judge success?

- How-To questions answered in chat from a cited guide, with no reopen.
- No statutory figure sent without approval; every statutory draft cites the rule and its date ("per the WPS notice effective 15 July" - Hassan).
- First-try routing beats 1,126 / 1,327; repeats link to the open incident or Jira.
- Model spend visible daily, capped, and small next to USD 90k a month.
- The DPO can trace every field from ticket to model to reply.

---

## Time urgency

### S - Why now?

- The Q4 board meeting (CEO's deadline).
- August credits doubled; another rule change (TDS, ESI, PT) is always coming.
- The vendor contract is gone, so the CFO's "next proposal" bar applies now.

---

## Confidence and trust protocol

### I - How confidence should be interpreted

- Classification confidence decides auto vs clarify vs triage; a model is asked only when keywords and similar tickets disagree.
- A draft is trusted only if the output guard passes (sources cited, numbers grounded, right region, right language, no PII, no promises).
- Statutory answers are always reviewed, whatever the confidence.

---

## SPIN question funnel for the follow-up call

## Situation questions (S)
- Which channels does each tier use in payroll week?
- Who updates the KB when a circular lands, and how long does it take?
- Which engine endpoints can support call today, and with what limits?

## Problem questions (P)
- How many reopens in August were PF or WPS answers?
- Which second reassignments were approved in Slack, and why?
- How long does a ticket linked to PNJ-4412 stay open?

## Implication questions (I)
- What does one wrong statutory answer cost: a credit, a re-run, a filing correction?
- What happens to the cap if a bot answers every payroll-week message?
- What would the DPO need to see before a pilot touches ticket text?

## Need-payoff questions (N)
- If the assistant answered with "the value on the date you asked about, from the engine", would L2 stop the firefight?
- If repeats were linked to Jira automatically, how many hours would L2 get back?
- If spend were visible daily with a hard cap, would the CFO approve a pilot?

---

## Expected SPIN arc

From "we want a chatbot to cut 30%" -> "our answers are wrong for a month after each rule change and tickets bounce" -> "fix routing, dated answers and repeats first, with a human on statutory and a cap on spend" -> "measure cost per ticket and credits, then decide on headcount".

---

## Problem definition summary

The problem is stale statutory knowledge, mis-routing and repeats, under strict privacy and cost constraints. It is not agent speed and not the absence of a chatbot.

---

## Assumptions made

- The rule table (`statutory_rules.json`) mirrors what `/statutory/rates` returns.
- KB titles are approved for customer use; process documents are reviewer-facing only.
- Customers accept a chat answer for How-To and a reviewed answer for statutory questions (Deepa and Hassan, transcript 09).
