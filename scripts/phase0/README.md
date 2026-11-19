# Phase 0: account and day-1 checks

Two scripts settle the open choices before any pipeline code is written. Run them in
**AWS CloudShell**, which already has Python 3, boto3 and your AWS sign-in, so nothing
needs installing or configuring.

| Script | What it does | Cost |
| --- | --- | --- |
| `phase0_budget.py` | Creates the `payce-pilot-monthly` budget: USD 15 a month, e-mail alerts at 50% and 80% of actual spend and at 100% of forecast | Free |
| `phase0_checks.py` | Checks Sydney (`ap-southeast-2`), the build region; also reports whether the production regions `ap-south-1` and `me-central-1` are enabled | Well under USD 0.10 |

## Steps

1. Sign in to the AWS console as **Agentic Core FDE**, set the region selector to
   **Asia Pacific (Sydney)**, and open **CloudShell** (the terminal icon in the top bar).
   CloudShell keeps a separate home folder per region, so stay in Sydney while you work.
2. **Actions → Upload file**, and upload `phase0_checks.py` and `phase0_budget.py`.
3. Create the budget:
   ```bash
   python3 phase0_budget.py --email you@example.com
   ```
4. Run the checks (about 2 minutes):
   ```bash
   python3 phase0_checks.py
   ```
5. **Actions → Download file**, path `results/phase0_summary.md`. Also download
   `results/phase0_results.json` and `results/gates.csv` and keep them: they go into the
   repository's `results/` folder in phase 1.

## What the checks cover

For Sydney:

- **Text models:** Nova Micro, Lite, Pro, Nova 2 Lite and Claude Haiku 4.5. The script
  finds every way to call each one (an in-region model ID, or an inference profile),
  sends a one-line prompt, and records which route worked and **which regions that route
  can send data to**.
- **Embedding models:** Titan Text Embeddings v2, Cohere Embed Multilingual v3 and Embed v4,
  tested on the same question in English, Hindi, Hinglish and Arabic. As a rough check of
  multilingual quality, the Hindi and Hinglish PF questions must score closer to each other
  than to the English WPS question.
- **Guardrails:** creates a temporary guardrail with the sensitive-information filter
  (built-in email, phone, name and IBAN types, plus custom regex for Aadhaar, PAN, Emirates
  ID and UAE IBAN) and the prompt-attack filter. It runs synthetic English, Hindi and Arabic
  text and the PN-101129-style injection through it, then deletes the guardrail.
- **Services:** EC2 `t4g.small`, RDS Postgres on `db.t4g.micro`, ElastiCache for Valkey,
  SQS, KMS and X-Ray.

All test text is synthetic. No client data is used in phase 0.

## Reading the results

| Status | Meaning |
| --- | --- |
| pass | Works, and the data stays in the region |
| warn | Works, but only through a route that can leave the region, or only partly (for example, Guardrails missed an ID in Hindi) |
| FAIL | Does not work: see the error in the Detail column |
| info | Not offered in this region |

`phase0_summary.md` starts with these decisions for Sydney:

- **model ladder**: every model that works in-region, cheapest rung first
  (Nova Micro → Nova Lite → Nova 2 Lite → Nova Pro → Claude Haiku 4.5). If no rung works
  in-region, it says `DECIDE` and lists the routes that do work, with the regions each one can
  reach. That choice is yours to make.
- **starting rung**: the lowest rung. Classification and drafting both start there; phases 6
  and 8 move a job up a rung only when the lower one fails its eval.
- **out of region rungs**: models that work only through a route that can leave the region.
  They are not on the ladder unless you decide to add them.
- **embedding model**: the best in-region multilingual model, or `multilingual-e5` on the
  EC2 if none passed.
- **guardrails**: whether the filter can be the AWS-native output check, or whether the
  Presidio re-scan has to carry the Hindi and Arabic cases.

One case is *expected* to fail: Devanagari digits (२३४५…). It shows why the phase 3 PII
gate converts digits before matching.

## If something fails

- **AccessDenied on Claude Haiku 4.5:** open Amazon Bedrock in the console, find the model
  in the model catalog, and complete the access request it shows. Then re-run.
- **AccessDenied mentioning a service control policy:** your account's project does not allow
  that service. Note it; the build plan's fallback applies.
- **The budget script is refused:** check that your user can manage budgets
  (Billing and Cost Management). Don't skip it: on the paid plan, spend beyond your credits is
  charged to your card, and the budget alerts are your early warning.
- Re-running is safe: each run appends new rows to `gates.csv`, and the budget script updates
  the existing budget instead of creating a second one.

## Gate to finish phase 0

The three decisions for Sydney (model ladder, embedding model, Guardrails) are written
down, and every service check is pass. Any `DECIDE` row needs your decision before
phase 2.

The budget *action* that stops EC2 and RDS at 100% is added in phase 2, once those instances
exist.
