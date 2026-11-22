# Operating the demo (plan v2 phases C and D)

Everything runs from the repo root in PowerShell, signed in with `aws login --profile payce-fde`.
Only Sydney (ap-southeast-2) is ever deployed; India and UAE stay placeholders.

## Release: one command

```powershell
git add -A; git commit -m "..."
.\scripts\deploy.ps1 v0.8.0
```

`deploy.ps1` refuses uncommitted changes, pushes the branch and the tag, waits until **both**
images for that tag are in ECR (so a restart can never pick up the previous `:latest`), restarts
the app, waits until `/api/health` reports the new `version`, then runs every gate into
`checks_<time>.log`. Exit code 0 only if all pass. It never changes infrastructure.

To re-run the gates without releasing: `.\scripts\run_checks.ps1` (add `-Restart` to restart first).

## The gates

| Script | Phase | Needs |
|---|---|---|
| `check_phase4.py` | 4 data load: counts, 0 leaks, rules by date | AWS sign-in (SSM) |
| `check_chat.py` | 8 chat: greeting, vague, injection, How-To, statutory review, Arabic, run status | public URL |
| `check_dashboard.py` | A dashboard | `ADMIN_TOKEN` (read from `.env`) |
| `check_knowledge.py` | B knowledge import | `ADMIN_TOKEN` |
| `check_agent_live.py` | 6 classify, 7 duplicate + incident, 9 PII never sent + statutory review | public URL |
| `run_evals.py` | C evals on the 200-ticket labelled set + Q3 replay (local, no model) | the data room folder |
| `check_traces.py` | D one X-Ray trace per ticket | iam + ec2 stacks updated for phase D |
| `use_cache.ps1 valkey` | D cache on ElastiCache Valkey | cache stack applied |

## Phase C results (local, 22 Nov 2026)

`python scripts\run_evals.py` on the labelled set (classifier trained on the other Q3 tickets):

- Classification 100% on the 200 (customer's own pick: 88%); on the latest 20% of Q3 by time,
  trained on the earlier 80%: 99.2% (was 95.9%). The Q3 data is templated, so near-copies of a
  ticket exist in training; the time split is the more honest number.
- Statutory: 0 of 19 answered without a person. Guard: 200/200 drafts pass. 0 PII in sent replies.
- Dedupe precision 100% (26/26, was 93%); Meridian burst = 1 incident (was 2), 30 tickets attached,
  0 false incidents across Q3.

Fixes behind those numbers: "following up" counts as a resubmit only about our own earlier ticket;
incidents also match on subject + symptom across wordings and languages; near-copy past tickets
win a tie against a single keyword; a statutory figure question always goes to Statutory review;
fixed-wording fact replies in Hindi and Arabic; the guard no longer treats the customer's own
number (a run id) as an uncited claim; any auto-reply model draft that fails the guard falls back
to the fixed wording.

## Traces (X-Ray)

Each ticket is one trace: a root span with one child per graph node (pii_gate ... send). Spans
carry ids, route and timings only, never ticket text. Worker -> OTLP -> ADOT collector (a container
on the server) -> X-Ray with the instance role; `ticket_id` is indexed.

To turn on (infra change, your approval):
```powershell
.\scripts\cfn.ps1 plan iam    ; .\scripts\cfn.ps1 apply iam     # xray:PutTraceSegments for the role
.\scripts\cfn.ps1 plan ec2    ; .\scripts\cfn.ps1 apply ec2     # collector in compose; the instance stops/starts
.\scripts\deploy.ps1 v0.8.x                                    # image with the OpenTelemetry packages
python scripts\check_traces.py
```
In the console: X-Ray > Traces, filter `annotation.ticket_id = "<ticket id>"`.

## Cache: Upstash -> ElastiCache Valkey

```powershell
.\scripts\cfn.ps1 plan cache ; .\scripts\cfn.ps1 apply cache   # ~10 min, ~USD 0.02/hour while it exists
.\scripts\use_cache.ps1 valkey                                 # saves the Upstash URL, switches, restarts, checks
.\scripts\use_cache.ps1 upstash                                # switch back (do this before deleting the stack)
```
`/api/ready` shows which cache is in use (never the host or token).

## Cost control

`.\scripts\demo.ps1 stop` stops EC2 and RDS (storage and the Elastic IP still bill a little);
`start` brings them back. Delete the cache stack when not demoing (after `use_cache.ps1 upstash`).
