-- How-To learning loop. Support writes an answer once; the agent reuses it for every
-- similar question after that.
--   review_tasks.kind: 'reply' (approve a draft for this customer) or 'knowledge'
--   (write the approved How-To answer for a question the agent could only point to a guide for).
--   howto_answers: the durable library of approved How-To answers (masked text only).
ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'reply';

CREATE TABLE IF NOT EXISTS howto_answers (
    id           uuid PRIMARY KEY,
    region       text,                              -- IN | UAE | NULL (all regions)
    language     text NOT NULL,                     -- en | hi-Latn | hi | ar
    question     text NOT NULL,                     -- masked customer question
    answer       text NOT NULL,                     -- approved answer (masked)
    kb_ids       text[] NOT NULL DEFAULT '{}',
    source       text NOT NULL,                     -- agent_approved | imported
    approved_by  text,
    ticket_id    uuid,
    active       boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS howto_answers_lookup ON howto_answers (language, region) WHERE active;
