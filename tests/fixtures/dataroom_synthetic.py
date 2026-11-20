"""A tiny data room in the client's formats, with invented values only (for CI).

Mirrors the shapes of the real export (three ticket formats in one list, mixed timestamps,
a repeated row, a partner ticket with only the end customer's name, notes in events) so the
loader is tested end to end without the client data ever reaching CI.
"""

import json

PII = {  # every raw personal value planted below
    "pan": "QWERT5521Z",
    "aadhaar": "0000 4821 7734",
    "iban": "AE00 0000 1111 2222 3333 444",
    "eid": "784-0000-1234567-0",
    "acct": "12345678901",
    "ifsc": "TEST0123456",
    "email": "hr9@zeta.example",
    "wa": "+91 00000 01234",
}

CUSTOMERS = """customer_id,name,tier,region,monthly_fee_usd,employees_paid
C-9001,Zeta Foods Pvt Ltd,Enterprise,IN,4000,5000
C-9002,Sand Dune Trading LLC,Business,UAE,2000,900
C-9003,Lotus Works Trust,Standard,IN,500,120
"""


def tickets() -> dict:
    email = {
        "ticket_id": "PN-900001",
        "channel": "email",
        "received_at": "2026-08-10T09:36:23+05:30",
        "from_email": PII["email"],
        "customer_id": "C-9001",
        "subject": "PF deduction wrong",
        "body": f"PF looks wrong. My Aadhaar is {PII['aadhaar']} and PAN {PII['pan']}, please verify.",
        "category": "Statutory",
        "priority": "P2",
        "status": "closed",
        "assigned_group": "Statutory-Compliance",
        "first_response_at": "2026-08-10T10:00:00",
        "resolved_at": "2026-08-11T09:00:00Z",
        "events": [
            {
                "event": "created",
                "ts": "2026-08-10T09:36:23+05:30",
                "actor": "system",
                "meta": {"category": "PAYROLL ISSUE", "priority": "P2"},
            },
            {
                "event": "assigned",
                "ts": "2026-08-10T09:36:59+05:30",
                "actor": "system",
                "meta": {"queue": "Payroll-Ops"},
            },
            {
                "event": "reassigned",
                "ts": "2026-08-10T09:50:00",
                "actor": "AG-002",
                "meta": {
                    "from": "Payroll-Ops",
                    "to": "Statutory-Compliance",
                    "reason": "Not payroll - moving to compliance",
                },
            },
            {
                "event": "replied",
                "ts": "2026-08-10T10:00:00",
                "actor": "AG-002",
                "meta": {
                    "tier": "L1",
                    "kb_article_id": "KB-9142",
                    "note": f"customer sent A/C {PII['acct']}",
                    "internal": True,
                },
            },
            {
                "event": "resolved",
                "ts": "2026-08-11T09:00:00Z",
                "actor": "AG-002",
                "meta": {"resolution": "resolved", "category": "statutory/compliance"},
            },
        ],
    }
    widget = {
        "tkt": "PN-900002",
        "source": "inapp_widget",
        "org_id": "C-9002",
        "user_ref": "U-1",
        "title": "WPS file rejected",
        "message": f"Salary account IBAN {PII['iban']}, Emirates ID {PII['eid']}.",
        "cat": "Compliance - PF/WPS",
        "prio": "urgent",
        "state": "solved",
        "created": "2026-07-20 11:38:51",
        "first_reply_ts": 1784530731000,
        "closed_ts": 1784617131000,
        "history": [
            {"action": "created", "time": 1784527731000, "who": "system", "data": {"category": "STATUTORY"}},
            {
                "action": "assigned",
                "time": 1784527767000,
                "who": "system",
                "data": {"queue": "Statutory-Compliance"},
            },
            {
                "action": "resolved",
                "time": 1784617131000,
                "who": "AG-003",
                "data": {"resolution": "resolved", "category": "Statutory"},
            },
        ],
    }
    partner = {
        "reference": "PN-900003",
        "partner_id": "RS-01",
        "end_customer": "Lotus Works Trust",
        "tenant": None,
        "summary": "Bulk upload kaise kare",
        "details": "Bulk upload template kahan hai aur columns kaise map kare? Kya help milegi?",
        "topic": "how to",
        "severity": "S3",
        "opened_on": "01/08/2026 13:05 GST",
        "status": "CLOSED",
        "fr_at": "2026-08-01T18:36:12",
        "closed_at": "2026-08-03T09:24:53",
        "activity_log": [
            {
                "evt": "Created",
                "when": "2026-08-01T14:35:17",
                "user": "system",
                "info": {"category": "HowTo"},
            },
            {
                "evt": "Assigned",
                "when": "2026-08-01T14:35:53",
                "user": "system",
                "info": {"queue": "General-L1"},
            },
            {
                "evt": "Resolved",
                "when": "2026-08-03T09:24:53",
                "user": "AG-001",
                "info": {"resolution": "resolved", "category": "How-To"},
            },
        ],
    }
    resubmit = {
        "tkt": "PN-900004",
        "source": "inapp_widget",
        "org_id": "C-9001",
        "user_ref": "U-2",
        "title": "Re: PF deduction wrong",
        "message": "Following up on my earlier ticket PN-900001, no reply yet.",
        "cat": "Statutory",
        "prio": "high",
        "state": "closed",
        "created": "2026-08-10 15:00:00",
        "first_reply_ts": None,
        "closed_ts": 1786355000000,
        "history": [
            {
                "action": "created",
                "time": 1786354200000,
                "who": "customer",
                "data": {"category": "Statutory"},
            },
            {
                "action": "resolved",
                "time": 1786355000000,
                "who": "AG-003",
                "data": {"resolution": "duplicate of PN-900001", "category": "Statutory"},
            },
        ],
    }
    hindi = {
        "ticket_id": "PN-900005",
        "channel": "email",
        "received_at": "2026-09-01T10:00:00+05:30",
        "from_email": "hr2@lotus.example",
        "customer_id": "C-9003",
        "subject": "नया कर्मचारी कैसे जोड़ें",
        "body": "नए कर्मचारी को सिस्टम में कैसे जोड़ें? कृपया बताएं।",
        "category": "Onboarding",
        "priority": "P3",
        "status": "Resolved",
        "assigned_group": "Onboarding",
        "first_response_at": None,
        "resolved_at": "2026-09-02T10:00:00+05:30",
        "events": [
            {
                "event": "created",
                "ts": "2026-09-01T10:00:00+05:30",
                "actor": "system",
                "meta": {"category": "New Customer Setup"},
            }
        ],
    }
    repeat = dict(email, status="Closed")  # the export script's repeated row
    return {
        "export_meta": {"range": "2026-07-01..2026-09-30"},
        "tickets": [email, widget, partner, resubmit, hindi, repeat],
    }


def raw() -> dict[str, str]:
    kb = [
        {
            "id": "KB-9101",
            "title": "How to run monthly payroll",
            "region": "ALL",
            "topic": "howto_payroll",
            "last_reviewed": "2026-03-10",
            "excerpt": "See full article in Confluence space SUP-KB.",
        },
        {
            "id": "KB-9142",
            "title": "PF wage ceiling",
            "region": "IN",
            "topic": "pf_wage_ceiling",
            "last_reviewed": "2024-02-14",
            "excerpt": "The EPF wage ceiling is INR 15,000 per month.",
        },
        {
            "id": "KB-9201",
            "title": "WPS SIF file",
            "region": "UAE",
            "topic": "wps_file_format",
            "last_reviewed": "2024-06-20",
            "excerpt": "Use the v2 layout (14 columns).",
        },
    ]
    rules = {
        "rules": [
            {
                "rule_id": "R-IN-PF-2026-08",
                "region": "IN",
                "topic": "pf_wage_ceiling",
                "title": "EPF ceiling raised",
                "effective_from": "2026-08-01",
                "old_value": "INR 15,000 per month",
                "new_value": "INR 25,000 per month",
                "affects_kb_topics": ["pf_wage_ceiling"],
                "source": "circular (fictional)",
                "status": "in_force",
            },
            {
                "rule_id": "R-UAE-WPS-2026-07",
                "region": "UAE",
                "topic": "wps_file_format",
                "title": "SIF v3",
                "effective_from": "2026-07-15",
                "old_value": "SIF v2 (14 columns)",
                "new_value": "SIF v3 (16 columns)",
                "affects_kb_topics": ["wps_file_format"],
                "source": "notice (fictional)",
                "status": "in_force",
            },
        ]
    }
    whatsapp = [
        {
            "thread_id": "WA-1",
            "ticket_id": "PN-900001",
            "wa_contact": PII["wa"],
            "customer_hint": "Zeta Foods Pvt Ltd",
            "closed": True,
            "messages": [
                {"from": "customer", "ts": 1786354200000, "text": f"my PAN is {PII['pan']}"},
                {"from": "agent", "ts": 1786354300000, "text": "Thanks, checking."},
            ],
        }
    ]
    calls = [
        {
            "call_id": "CL-1",
            "ticket_id": "PN-900002",
            "agent_id": "AG-003",
            "customer_id": "C-9002",
            "called_at": "20-07-2026 11:19",
            "duration_min": 5.5,
            "summary": f"Caller asked about IFSC {PII['ifsc']} change.",
            "disposition": "Ticket logged",
            "callback_required": False,
        }
    ]
    jira = [
        {
            "key": "PNJ-9001",
            "summary": "Connector duplicates punches",
            "issue_type": "Bug",
            "priority": "P1",
            "component": "Integrations",
            "status": "Done",
            "created": "2026-08-07T04:03:30+05:30",
            "reporter": "AG-002",
            "customer_ids": ["C-9001"],
            "linked_ticket_ids": ["PN-900001"],
            "resolution_note": "Fix in 2.7.3, rollout pending customer UAT.",
        }
    ]
    sla_md = """# MSA Schedule 3
*Template v3.2, effective 2025.*
## 3.1 Support tiers
| Tier | Who | Hours | First response target | Resolution target | SLA credits |
|---|---|---|---|---|---|
| **Enterprise** | x | y | P1: 1 h, P2: 4 h, P3: 8 h | P1: 8 h, P2: 24 h, P3: 72 h | Yes |
| **Standard** | x | y | Best effort | Best effort | No |
## 3.4 Service credits
| Tier | P1 | P2 | P3 |
|---|---|---|---|
| Enterprise | 10% | 5% | 2% |
**Severity multiplier:** if the actual resolution time exceeds **twice** the target,
the credit percentage is multiplied by **1.5**.
"""
    return {
        "data-room/data/tickets_export.json": json.dumps(tickets(), ensure_ascii=False),
        "data-room/data/customers.csv": CUSTOMERS,
        "data-room/data/agent_roster.csv": "agent_id,name,tier,desk,languages,hire_date,status,left_date\n"
        'AG-002,Test Person,L1,Pune,"en,hi",2022-01-25,active,\n',
        "data-room/data/csat_survey.csv": "survey_id,ticket_id,customer_id,score,comment,submitted_at,survey_channel\n"  # noqa: E501
        f"S-1,PN-900001,C-9001,2,Mail {PII['email']} back,2026-08-12 07:20,email_link\n",
        "data-room/data/sla_breaches_q3.csv": (
            "breach_id,ticket_id,customer_id,tier,priority,sla_resolution_target_h,actual_resolution_h,breach_h,"  # noqa: E501
            "credit_pct,monthly_fee_usd,credit_usd,invoice_month,agent_noted_reason,approved_by\n"
            "BR-1,PN-900001,C-9001,Enterprise,P2,24,40.0,16.0,5.0,4000,200.0,2026-08,Agent delay,Q. Approver\n"  # noqa: E501
        ),
        "data-room/data/monthly_cost_sheet.csv": "month,tickets_received_all_customers,agent_fte,notes\n2026-08,100,4,\n",  # noqa: E501
        "data-room/data/whatsapp_export.json": json.dumps(whatsapp),
        "data-room/data/call_center_notes.json": json.dumps(calls),
        "data-room/data/jira_escalations.json": json.dumps(jira),
        "data-room/data/kb_articles.json": json.dumps(kb),
        "data-room/integrations/statutory_rules.json": json.dumps(rules),
        "data-room/process/sla_contract_excerpt.md": sla_md,
        "data-room/process/escalation_policy.md": "# Escalation Policy\n## Tiers\nL1 then L2.\n## Not allowed\nNo writes.\n",  # noqa: E501
    }
