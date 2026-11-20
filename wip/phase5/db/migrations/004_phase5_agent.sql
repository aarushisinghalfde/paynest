-- Phase 5: the agent. LangGraph's PostgresSaver creates its own checkpoint tables
-- (checkpoints, checkpoint_writes, checkpoint_blobs) with setup() at worker start.

ALTER TABLE tickets
    ADD COLUMN IF NOT EXISTS idempotency_key  text,                     -- from the client, per message
    ADD COLUMN IF NOT EXISTS agent_status     text,                     -- running | waiting_review | replied | blocked | failed
    ADD COLUMN IF NOT EXISTS route            text,
    ADD COLUMN IF NOT EXISTS route_reason     text,
    ADD COLUMN IF NOT EXISTS classification   jsonb;
-- 20 parallel posts of the same message create 1 ticket
CREATE UNIQUE INDEX IF NOT EXISTS tickets_idempotency_key
    ON tickets (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
