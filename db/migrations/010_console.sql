-- Phase G: the support-head console.
--   tickets.decision     why the agent did what it did (agent/decision.py): ids, scores, rule, checks; no text
--   tickets.translation  English for the lead: {"question": ..., "reply": ..., "from": "ar", "by": model}
--                        (machine translation of MASKED text; numbers and tokens verified identical)
--   tickets.feedback     the customer's "did this solve it?" (yes | no) and when
--   review_tasks.proposed_draft  the agent's draft as proposed, so an approval can be told apart
--                        from an edit; outcome = approved_as_is | edited | rejected
ALTER TABLE tickets
    ADD COLUMN IF NOT EXISTS decision     jsonb,
    ADD COLUMN IF NOT EXISTS translation  jsonb,
    ADD COLUMN IF NOT EXISTS feedback     text,
    ADD COLUMN IF NOT EXISTS feedback_at  timestamptz;
ALTER TABLE review_tasks
    ADD COLUMN IF NOT EXISTS proposed_draft text,
    ADD COLUMN IF NOT EXISTS outcome        text;
CREATE INDEX IF NOT EXISTS tickets_live_status ON tickets (origin, agent_status, created_at);
