-- Phase 4: the masked data room. Everything here is masked or reference data; raw values
-- live only in the PII vault (DynamoDB + KMS). Loaded by `python -m loader.main load` on the EC2.

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id        text PRIMARY KEY,                 -- C-1001
    name             text NOT NULL,                    -- company name (not personal data)
    tier             text NOT NULL,                    -- Enterprise | Business | Standard
    region           text NOT NULL CHECK (region IN ('IN', 'UAE')),
    home_aws_region  text NOT NULL CHECK (home_aws_region IN ('ap-south-1', 'me-central-1')),
    monthly_fee_usd  numeric(10, 2),
    employees_paid   integer
);

-- tickets (from phase 3) gains the fields of the historical export
ALTER TABLE tickets
    ADD COLUMN IF NOT EXISTS ticket_ref          text,
    ADD COLUMN IF NOT EXISTS origin              text NOT NULL DEFAULT 'live',   -- live | export
    ADD COLUMN IF NOT EXISTS tenant_resolved_by  text,          -- id | name | unresolved
    ADD COLUMN IF NOT EXISTS subject_masked      text,
    ADD COLUMN IF NOT EXISTS user_ref            text,
    ADD COLUMN IF NOT EXISTS partner_id          text,
    ADD COLUMN IF NOT EXISTS end_customer        text,
    ADD COLUMN IF NOT EXISTS category_raw        text,          -- as typed (final label in the export)
    ADD COLUMN IF NOT EXISTS initial_team        text,          -- the customer's original pick
    ADD COLUMN IF NOT EXISTS team                text,          -- closing category, one of the 9 SOP teams
    ADD COLUMN IF NOT EXISTS final_queue_team    text,
    ADD COLUMN IF NOT EXISTS reassign_count      integer,
    ADD COLUMN IF NOT EXISTS duplicate_of_ref    text,          -- resubmits ("duplicate of PN-...")
    ADD COLUMN IF NOT EXISTS kb_ids              text[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS priority            text,
    ADD COLUMN IF NOT EXISTS case_status         text,          -- the helpdesk's status (closed, resolved)
    ADD COLUMN IF NOT EXISTS language            text,          -- en | hi | hi-Latn | ar
    ADD COLUMN IF NOT EXISTS first_response_at   timestamptz,
    ADD COLUMN IF NOT EXISTS resolved_at         timestamptz;
CREATE UNIQUE INDEX IF NOT EXISTS tickets_ticket_ref_key ON tickets (ticket_ref) WHERE ticket_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS tickets_tenant_created_idx ON tickets (tenant_id, created_at);

CREATE TABLE IF NOT EXISTS ticket_events (
    ticket_id  uuid NOT NULL REFERENCES tickets (id) ON DELETE CASCADE,
    seq        integer NOT NULL,
    ts         timestamptz,
    type       text NOT NULL,                 -- created, assigned, replied, reassigned, escalated, ...
    actor      text,                          -- system, customer, AG-nnn
    data       jsonb NOT NULL DEFAULT '{}',   -- masked
    PRIMARY KEY (ticket_id, seq)
);

CREATE TABLE IF NOT EXISTS whatsapp_threads (
    id             uuid PRIMARY KEY,
    thread_id      text UNIQUE NOT NULL,
    ticket_ref     text,
    tenant_id      text,
    customer_hint  text,
    contact_token  text,                      -- HMAC of the WhatsApp number; the number is in the vault
    closed         boolean,
    pii_blocked    boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS whatsapp_messages (
    thread_id    uuid NOT NULL REFERENCES whatsapp_threads (id) ON DELETE CASCADE,
    seq          integer NOT NULL,
    sender       text,
    ts           timestamptz,
    text_masked  text,
    PRIMARY KEY (thread_id, seq)
);

CREATE TABLE IF NOT EXISTS call_notes (
    id                 uuid PRIMARY KEY,
    call_id            text UNIQUE NOT NULL,
    ticket_ref         text,
    agent_id           text,
    customer_id        text,
    called_at          timestamptz,
    duration_min       numeric(6, 1),
    summary_masked     text,
    disposition        text,
    callback_required  boolean
);

CREATE TABLE IF NOT EXISTS jira_issues (
    key                     text PRIMARY KEY,
    summary_masked          text,
    issue_type              text,
    priority                text,
    component               text,
    status                  text,
    created_at              timestamptz,
    reporter_agent          text,
    customer_ids            text[] NOT NULL DEFAULT '{}',
    linked_ticket_refs      text[] NOT NULL DEFAULT '{}',
    resolution_note_masked  text                    -- read by get_incident (PNJ-4412: Done, awaiting UAT)
);

CREATE TABLE IF NOT EXISTS csat_responses (
    survey_id       text PRIMARY KEY,
    ticket_ref      text,
    customer_id     text,
    score           integer,
    comment_masked  text,
    submitted_at    timestamptz,
    survey_channel  text
);

CREATE TABLE IF NOT EXISTS sla_breaches (
    breach_id                  text PRIMARY KEY,
    ticket_ref                 text,
    customer_id                text,
    tier                       text,
    priority                   text,
    sla_resolution_target_h    numeric(8, 1),
    actual_resolution_h        numeric(8, 1),
    breach_h                   numeric(8, 1),
    credit_pct                 numeric(5, 1),
    monthly_fee_usd            numeric(10, 2),
    credit_usd                 numeric(10, 2),
    invoice_month              text,
    agent_noted_reason_masked  text,
    approved_by_kind           text                    -- system | person (names are not kept)
);

CREATE TABLE IF NOT EXISTS agents (                    -- names are not kept
    agent_id   text PRIMARY KEY,
    tier       text,
    desk       text,
    languages  text[] NOT NULL DEFAULT '{}',
    hire_date  date,
    status     text,
    left_date  date
);

CREATE TABLE IF NOT EXISTS monthly_costs (
    month                              text PRIMARY KEY,
    tickets_received_all_customers     numeric,
    tickets_in_ops_extract             numeric,
    agent_fte                          numeric,
    agent_loaded_cost_usd              numeric,
    tooling_usd                        numeric,
    vendor_pilot_usd                   numeric,
    sla_credits_paid_usd               numeric,
    cost_per_ticket_excl_credits_usd   numeric,
    cost_per_ticket_incl_credits_usd   numeric,
    notes                              text
);

CREATE TABLE IF NOT EXISTS sla_terms (
    template_version     text NOT NULL,
    tier                 text NOT NULL,
    priority             text NOT NULL,
    first_response_h     numeric(5, 1),               -- NULL = best effort (Standard)
    resolution_h         numeric(5, 1),
    credit_pct           numeric(4, 1),
    severity_multiplier  numeric(3, 1),               -- applies when resolution > 2x target
    PRIMARY KEY (template_version, tier, priority)
);

CREATE TABLE IF NOT EXISTS statutory_rules (
    rule_id            text PRIMARY KEY,
    region             text NOT NULL,
    topic              text NOT NULL,
    title              text NOT NULL,
    effective_from     date NOT NULL,
    old_value          text,
    new_value          text,
    affects_kb_topics  text[] NOT NULL DEFAULT '{}',
    source             text,
    status             text
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    chunk_id        text PRIMARY KEY,              -- KB-0201#excerpt, R-UAE-WPS-2026-07#rule, ...
    kb_id           text,
    source_kind     text NOT NULL,                 -- kb_title | kb_excerpt | rule | process_doc
    region          text NOT NULL,                 -- IN | UAE | ALL
    topic           text NOT NULL,
    language        text NOT NULL,
    title           text,
    content         text NOT NULL,
    effective_from  date,                          -- NULL = no known start
    effective_to    date,                          -- NULL = still valid
    superseded_by   text,
    last_reviewed   date,
    embedding       vector(384),                   -- filled in phase 6 (multilingual-e5-small, 384 dims)
    tsv             tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(title, '') || ' ' || content)) STORED
);
CREATE INDEX IF NOT EXISTS kb_chunks_tsv_idx ON kb_chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS kb_chunks_topic_idx ON kb_chunks (topic, region);

-- Empty until later phases; created now so the schema is complete (build plan section 6).
CREATE TABLE IF NOT EXISTS review_tasks (
    id            uuid PRIMARY KEY,
    ticket_id     uuid NOT NULL REFERENCES tickets (id),
    status        text NOT NULL DEFAULT 'open',    -- open | approved | changes_requested | rejected
    draft         text,
    sources       jsonb NOT NULL DEFAULT '[]',
    route_reason  text,
    guard_result  jsonb,
    sla_deadline  timestamptz,
    assignee      text,
    decision      text,
    note          text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    decided_at    timestamptz
);
CREATE TABLE IF NOT EXISTS sent_replies (
    ticket_id      uuid NOT NULL REFERENCES tickets (id),
    draft_version  integer NOT NULL,
    body_masked    text NOT NULL,
    channel        text,
    sent_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ticket_id, draft_version)        -- a reply can never go out twice
);
CREATE TABLE IF NOT EXISTS cost_ledger (
    id          bigserial PRIMARY KEY,
    ts          timestamptz NOT NULL DEFAULT now(),
    ticket_id   uuid,
    purpose     text,                              -- classify | draft | judge
    route       text,
    model_id    text,
    rung        integer,
    tokens_in   integer,
    tokens_out  integer,
    cost_usd    numeric(10, 6)
);
CREATE TABLE IF NOT EXISTS eval_labels (
    set_version  text NOT NULL,
    ticket_ref   text NOT NULL,
    label_team   text NOT NULL,
    label_source text NOT NULL,                    -- data | relabel | reviewer
    corrected    boolean NOT NULL DEFAULT false,
    note         text,
    PRIMARY KEY (set_version, ticket_ref)
);
CREATE TABLE IF NOT EXISTS load_runs (
    id           bigserial PRIMARY KEY,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    summary      jsonb
);
