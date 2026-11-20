-- How-To flow: chat messages from one browser session share a conversation_id, so a
-- follow-up ("and for contractors?") is read together with the earlier turns.
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS conversation_id text;
CREATE INDEX IF NOT EXISTS tickets_conversation_idx ON tickets (conversation_id, created_at)
    WHERE conversation_id IS NOT NULL;
