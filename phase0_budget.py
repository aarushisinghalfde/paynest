#!/usr/bin/env python3
"""Phase 0: create the pilot's AWS Budget with e-mail alerts.

    python3 phase0_budget.py --email you@example.com            # USD 15 a month
    python3 phase0_budget.py --email you@example.com --limit 10

Alerts: actual spend at 50% and 80%, forecast at 100%.
The budget *action* that stops EC2 and RDS at 100% is added in phase 2, once
those instances exist (an action needs the instance IDs and an IAM role).

AWS Budgets is a global service, so this runs against us-east-1 whatever the
pilot regions are. Safe to re-run: an existing budget is updated, not duplicated.
"""
import argparse
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError

BUDGET_NAME = "payce-pilot-monthly"


def notifications(email, thresholds):
    out = []
    for kind, pct in thresholds:
        out.append({
            "Notification": {"NotificationType": kind, "ComparisonOperator": "GREATER_THAN",
                             "Threshold": float(pct), "ThresholdType": "PERCENTAGE"},
            "Subscribers": [{"SubscriptionType": "EMAIL", "Address": email}],
        })
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", required=True)
    ap.add_argument("--limit", type=float, default=15.0, help="monthly limit in USD (default 15)")
    ap.add_argument("--profile")
    args = ap.parse_args(argv)

    session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
    account = session.client("sts").get_caller_identity()["Account"]
    budgets = session.client("budgets", region_name="us-east-1")

    budget = {
        "BudgetName": BUDGET_NAME,
        "BudgetLimit": {"Amount": f"{args.limit:.2f}", "Unit": "USD"},
        "TimeUnit": "MONTHLY",
        "BudgetType": "COST",
    }
    thresholds = [("ACTUAL", 50), ("ACTUAL", 80), ("FORECASTED", 100)]
    try:
        budgets.create_budget(AccountId=account, Budget=budget,
                              NotificationsWithSubscribers=notifications(args.email, thresholds))
        print(f"Created budget {BUDGET_NAME}: USD {args.limit:.2f}/month, alerts to {args.email}")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "DuplicateRecordException":
            print(f"Could not create the budget: {exc}")
            return 1
        budgets.update_budget(AccountId=account, NewBudget=budget)
        print(f"Budget {BUDGET_NAME} already existed: limit set to USD {args.limit:.2f}. "
              "Existing alerts were left as they are.")
    except BotoCoreError as exc:
        print(f"Could not reach AWS Budgets: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
