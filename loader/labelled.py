"""The 200-ticket labelled set for the phase 6 model-fit test (build plan, section 5).

Stratified by team and language, masked text only. The starting label is the data's own:
the closing category (normalised to the 9 SOP teams), which always equals the final team
queue after real moves. An independent relabel and a human check of every disagreement
(plus 20 random agreements) follow; the correction count is recorded.
"""

import random
from collections import defaultdict

SET_VERSION = "v1"


def stratified(tickets: list[dict], n: int = 200, seed: int = 20261120) -> list[dict]:
    pool = [t for t in tickets if t["status"] == "masked" and not t["duplicate_of_ref"] and t["team"]]
    groups = defaultdict(list)
    for t in sorted(pool, key=lambda t: t["ticket_ref"]):
        groups[(t["team"], t["language"])].append(t)
    rng = random.Random(seed)
    for g in groups.values():
        rng.shuffle(g)
    # every stratum gets at least one ticket, the rest in proportion to its size
    take = {k: 1 for k in groups}
    rest = n - len(take)
    total = sum(len(g) - 1 for g in groups.values())
    shares = sorted(groups, key=lambda k: -(len(groups[k]) - 1) * rest / max(total, 1) % 1)
    for k in groups:
        take[k] += int((len(groups[k]) - 1) * rest / max(total, 1))
    for k in shares:
        if sum(take.values()) >= n:
            break
        if take[k] < len(groups[k]):
            take[k] += 1
    chosen = [t for k, g in groups.items() for t in g[: take[k]]]
    return sorted(chosen, key=lambda t: t["ticket_ref"])[:n]


def export_rows(chosen: list[dict], tenants: dict[str, dict]) -> list[dict]:
    return [
        {
            "set_version": SET_VERSION,
            "ticket_ref": t["ticket_ref"],
            "language": t["language"],
            "tenant_region": tenants.get(t["tenant_id"], {}).get("region"),
            "channel": t["channel"],
            "subject": t["subject_masked"],
            "body": t["masked_body"],
            "customer_pick": t["initial_team"],
            "data_label": t["team"],
            "moved": t["initial_team"] != t["team"],
        }
        for t in chosen
    ]
