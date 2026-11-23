# evals

How we know the agent is right. Every eval runs on masked text only and writes its gates to
`results/gates.csv`; `scripts/evidence.py` copies the latest result per gate into `docs/PROJECT_STATE.md`.

## The sets

| Set | Where | What |
| --- | --- | --- |
| Labelled set | `evals/local/labelled_set_v1.json` (git-ignored: masked client data stays out of the public repo) | 200 Q3 tickets, stratified by team and language, with the final team as the label. Written by `scripts/run_phase4.py` (fixed seed). |
| Q3 replay | built in memory from the data room | All Q3 tickets in time order, for duplicates, resubmits and the 25 Sep incident burst. |
| PII seeds | `tests/fixtures/pii_*.json` | Synthetic tickets with planted personal data (and clean ones) for the masking gate. |

## The evals

| Command | Gates |
| --- | --- |
| `python scripts\run_evals.py --record` | `classify_accuracy` (>= 90% overall, >= 85% per language, against the customer's own pick), `statutory_never_auto` (0 statutory answers without a person), `sent_replies_clean` (0 PII or unknown tokens sent), `guard_pass_rate` (>= 95%), `dedupe_precision` (>= 95%), `meridian_incident` (the burst is one incident by ticket 5) |
| `python scripts\run_evals.py --with-model --record` | adds `faithfulness`: >= 90% of claims in model drafts backed by a source the drafter had (`agent/faithfulness.py`) |
| `python scripts\eval_pii.py --record` | masking recall and false positives on the PII seeds |
| `python scripts\model_fit.py` | the cheapest model per job on the labelled set (classify, draft) |
| `.\scripts\run_checks.ps1` | all of the above plus the live gates against the deployed app |

The similar-tickets classifier and the past resolutions are trained on the other Q3 tickets, so no
labelled ticket grades itself. Each labelled ticket goes through the real agent graph.

## In production

Two signals come from live traffic, shown in the control room: customers' "Did this solve it?" and
reviewers' outcomes (approved as is, edited, rejected) by confidence band.

## Known limits

- The data room's tickets are generated from templates, so near-copies are common and the labelled
  classify score (100%) is optimistic; expect lower on real traffic.
- How-To answer quality cannot be scored until the guides' content (Confluence SUP-KB) is imported;
  the data room has titles only.
- Not yet measured: reopens (the same customer asking again within 7 days after an agent answer).
