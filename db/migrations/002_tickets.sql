-- Phase 3: tickets and the short-lived raw inbox.
--
-- tickets holds only masked data. The agent, search and evals read this table.
-- ticket_inbox holds the body exactly as received, plus the sender fields, only until
-- the worker has masked it: the worker deletes the inbox row in the same transaction
-- that writes masked_body. A ticket quarantined by the re-scan (status pii_blocked)
-- keeps its inbox row for a human to review; nothing else reads it.
-- Raw values go to the encrypted vault (DynamoDB + KMS), never to these tables.

CREATE TABLE IF NOT EXISTS tickets (
    id                  uuid PRIMARY KEY,
    tenant_id           text NOT NULL,
    channel             text NOT NULL DEFAULT 'web',
    status              text NOT NULL DEFAULT 'received'
                        CHECK (status IN ('received', 'masked', 'pii_blocked')),
    -- HMAC-SHA256 of the sender's email / phone, keyed per tenant: lets us group tickets
    -- by sender without storing the address. NULL when not given.
    sender_email_token  text,
    sender_phone_token  text,
    masked_body         text,
    pii_counts          jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {"IBAN": 1, "NAME": 2}: counts, never values
    pii_block_reasons   text[] NOT NULL DEFAULT '{}',         -- e.g. {second_pass:PHONE}: kinds, never values
    ner_layer           text,                                 -- presidio | rules
    created_at          timestamptz NOT NULL DEFAULT now(),
    masked_at           timestamptz
);

CREATE INDEX IF NOT EXISTS tickets_status_created_idx ON tickets (status, created_at);
CREATE INDEX IF NOT EXISTS tickets_sender_email_idx ON tickets (tenant_id, sender_email_token);

CREATE TABLE IF NOT EXISTS ticket_inbox (
    ticket_id     uuid PRIMARY KEY REFERENCES tickets (id) ON DELETE CASCADE,
    body          text NOT NULL,
    sender_name   text,
    sender_email  text,
    sender_phone  text,
    received_at   timestamptz NOT NULL DEFAULT now()
);
