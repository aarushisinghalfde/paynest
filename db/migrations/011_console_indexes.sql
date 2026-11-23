-- The control room reads each live ticket with its latest review and its model spend. With many
-- tickets these look-ups must not scan whole tables. (sent_replies is already keyed by ticket_id.)
CREATE INDEX IF NOT EXISTS review_tasks_ticket ON review_tasks (ticket_id, kind, created_at DESC);
CREATE INDEX IF NOT EXISTS cost_ledger_ticket ON cost_ledger (ticket_id);
CREATE INDEX IF NOT EXISTS cost_ledger_ts ON cost_ledger (ts);
