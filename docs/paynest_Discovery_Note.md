# Discovery note - Ramco Payce Support (Paynest)

**Author:** Aarushi Singhal
**Date:** 2026-11-20, written up from the discovery done before the first agent feature (phase 3 gate passed first)
**Status:** Agreed scope - build Payce Support Assist for Priya Nair (Head of Support), with the CFO's cost rules
**Brief:** `Case.md` and `data-room/` in `niti007/paynest-support-discovery` (treated as confidential; no data copied to public services)

---

## 1. The problem (one sentence, client language)

In payroll week our agents answer statutory questions from a wiki that is a week behind the payroll engine, tickets bounce between queues because customers pick the wrong category, and repeat tickets for the same known issue pile up, so SLA credits doubled in August while volume rose only 9%.

---

## 2. Who owns it today, and what they do instead

| Role | Person | What they do today |
|------|--------|--------------------|
| Owner | Priya Nair, Head of Customer Support | Rolls up SLA and CSAT for the board; believes CSAT falls because agents are slow; "nobody on my team should lose their job because of a bot" |
| Budget | Anjali Krishnan, CFO | Pays ~USD 90k a month for support; wants cost per ticket from ~USD 6 to ~USD 4, a hard cap on AI spend, daily spend visible to her, and an off switch |
| Front line | Farhan Qureshi, Senior L1 | 40-60 tickets a day; copies a KB answer plus the article id; pastes KB-0142 (PF 15,000) after the ceiling became 25,000; translates Arabic by hand |
| Escalations | Sandeep Rao, L2 lead | Approves second reassignments in Slack (no log); learns about rule changes "around the first, second of August"; "we're always one week behind" |
| Source of truth | Meera Iyer, Eng Manager | Owns the payroll engine; support tooling is read-only after May; `/statutory/rates` takes an as-of date; run status is rate limited (30/min per tenant) |
| Privacy | Karthik Subramanian, DPO | Found Aadhaar, PAN, bank details, Emirates IDs and IBANs in 90 days of tickets; needs a DPIA, in-region processing, retention and erasure |
| Sponsor | Rohan Mehta, CEO | Asked for "a ChatGPT chatbot that cuts support headcount by 30%" before the Q4 board |

---

## 3. Evidence from the data room (cite specifically)

- **The KB lags the engine on dated rules.** PF wage ceiling INR 15,000 -> 25,000 from 1 Aug 2026 (`R-IN-PF-2026-08`); WPS SIF v2 (14 cols) -> v3 (16 cols) from 15 Jul (`R-UAE-WPS-2026-07`) in `integrations/statutory_rules.json`. KB-0142 and KB-0201 still carried the old values (Farhan, transcript 05; Hassan, transcript 09).
- **Customer-picked categories are wrong often.** 201 of 1,327 picks differ from the final queue; 111 tickets moved more than once (loader, `data/tickets_export.json`). The SOP allows one move (`process/ticket_triage_sop.md`); approvals happen in Slack (Priya, transcript 03).
- **Repeat tickets for one known defect.** PNJ-4412 (connector v2.7 idempotency) is a Jira issue customers keep re-raising (Deepa, transcript 09; Meera, transcript 06); the Meridian burst on 25 Sep reached ~30 tickets before the runbook's 5-ticket incident trigger was acted on (Sandeep, transcript 04).
- **Credits are contractual, not random.** 128 breaches, USD 19,196 in Q3 credits (`data/sla_breaches_q3.csv`); 104 of them Enterprise; reasons are mostly "High volume" (37), "Agent delay" (27) or blank (24).
- **Personal data in tickets.** 103 of 1,353 tickets carry PAN, Aadhaar, IBAN, Emirates ID, phone or email (masking run in phase 4); the May payslip incident (`security/incident_2026_05_payslip_leak.md`).
- **The last chatbot failed on exactly these points.** Stale TDS slabs, an invented gratuity figure (11 of 200 sampled answers wrong), p95 19 s in peak week, a one-line handoff, no access to tier or run state, June bill USD 41,200 with an uncapped surcharge, a US sub-processor (`vendor_pilot/postmortem_chatbot_pilot.md`, invoice).
- **Languages.** 1,057 English, 156 Hinglish, 64 Hindi, 76 Arabic tickets; UAE customers prefer Arabic on WhatsApp (Farhan; Hassan).

---

## 4. What it costs them

| Metric | Value from the data room | What it implies |
|--------|--------------------------|-----------------|
| Support cost | ~USD 90k/month: 42 agents at ~USD 1,930 loaded, tooling ~USD 9.4k (`monthly_cost_sheet.csv`) | The CFO's yardstick is cost per ticket, USD 5.71-6.73 in Q3 |
| SLA credits | USD 3.9k Jul, 8.3k Aug, 7.0k Sep | Doubled in August with ~9% more volume: a statutory-change effect, not only volume |
| Category errors | 201 / 1,327 picks wrong; 111 tickets moved more than once | Each bounce costs hours on a P1/P2 clock |
| Largest category | How-To: 406 of 1,353 tickets (30%) | The safe, high-volume place to automate first |
| Failed vendor pilot | USD 78,200 for Apr-Jun, 5.5% wrong-fact rate | Any proposal needs a spend cap, a usage report and a wrong-answer plan |

We do not claim headcount savings. The CFO's own framing: "headcount is an output, not an input".

---

## 5. What success looks like (measurable with data they already hold)

- **Primary metric:** share of How-To tickets answered in chat from an approved source, with no reopen, at zero statutory errors.
- **Safety metrics:** 0 statutory figures sent without a human; 0 personal-data leaks to a model or another tenant; every wrong draft stopped by the guard on the planted set.
- **Routing metric:** tickets routed to the right team on first try (vs 1,126 / 1,327 today) and repeats linked to the open incident/Jira instead of new work.
- **Cost metric:** model cost per resolved ticket in peak week, visible daily, under a hard cap.
- **Data source they already have:** the Q3 ticket export (final labels), Jira, SLA breaches, statutory rules with effective dates.

**Out of scope to claim:** headcount reduction, CSAT movement, credit reduction. Those are pilot measurements.

---

## 6. Ranked shortlist

**Criteria:** cost to Ramco Payce (credits, rework), data readiness, safety risk, operability with the current team, time to value.

| Rank | Problem | Why it ranks here | Evidence |
|------|---------|-------------------|----------|
| 1 | Statutory answers out of date after a rule change | Directly drives reopens and the August credit spike; fix = answer by question date from the rule table | statutory_rules.json; transcripts 04, 05, 09 |
| 2 | Wrong category, bouncing tickets | 15% wrong picks; rules + similar past tickets can route on first try | tickets_export.json events |
| 3 | Repeat tickets for known issues and bursts | Link to Jira/incident and send a status update, not a new investigation | PNJ-4412; Meridian 25 Sep |
| 4 | How-To volume | 30% of tickets; safe to answer from guides in chat | final labels |
| 5 | Personal data in tickets | A precondition for anything that touches a model | DPO transcript; May incident |

**Rejected for v1 on purpose:** a voice bot (no data supports it), headcount targets, write access to the payroll engine, training on ticket data.

---

## 7. What we will build

A support assistant that masks personal data first, classifies and routes by code, answers How-To questions in chat from an answer cache and approved guides, answers statutory questions only from the dated rule table and only after a human approves, links repeats to incidents and Jira, and stops any bad draft with an output guard. In-region by design (Sydney for the demo; India and UAE regions as configs).

---

## 8. Assumptions made (and what would disprove them)

| Assumption | What would disprove it |
|------------|------------------------|
| Naive timestamps are IST | Event order breaks when read as IST (checked: 185/185 email, 483/483 widget, 219/219 partner in order) |
| The export's top-level category is the final label | Final queue on the last event disagrees with it |
| The KB titles are the approved guides; the rule table is the statutory truth | Engineering says `/statutory/rates` disagrees with `statutory_rules.json` |
| How-To answers can be reused across tenants in the same region and language | A guide differs per tenant configuration |

**Cheapest test:** replay the 200-ticket labelled set through the router and drafter, and have Support score every disagreement before a pilot.
