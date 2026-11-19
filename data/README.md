# data

| Folder | What | In git? |
| --- | --- | --- |
| `raw/` | The case files as received (tickets_export.json, statutory_rules.json, KB articles) | **No** (git-ignored) |
| `masked/` | Output of the phase 3 PII gate | **No** (git-ignored) |
| `seed/` | Synthetic tickets written for tests (phase 3) | Yes |

Real tickets are loaded and masked in phase 4. Nothing unmasked is ever sent to a model.
