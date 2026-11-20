-- Phase 7: duplicates, incidents, Jira links. Fingerprints live in Postgres so dedupe still
-- works when the cache is down (the cache is only a fast path).
CREATE TABLE IF NOT EXISTS incidents (
    id            uuid PRIMARY KEY,
    tenant_id     text NOT NULL,
    team          text,
    signature     text NOT NULL,        -- the first ticket's masked text, normalised
    opened_at     timestamptz NOT NULL,
    ticket_count  integer NOT NULL DEFAULT 0,
    status        text NOT NULL DEFAULT 'open',
    jira_key      text
);
ALTER TABLE tickets
    ADD COLUMN IF NOT EXISTS fingerprint   text,
    ADD COLUMN IF NOT EXISTS incident_id   uuid,
    ADD COLUMN IF NOT EXISTS jira_key      text;
CREATE INDEX IF NOT EXISTS tickets_tenant_recent_idx ON tickets (tenant_id, created_at DESC);
