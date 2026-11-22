-- Operations dashboard: how each live ticket was resolved and by which routing rule.
ALTER TABLE tickets
    ADD COLUMN IF NOT EXISTS route_rule   text,     -- e.g. R11-howto
    ADD COLUMN IF NOT EXISTS answer_tier  text;     -- library | cache | model | fallback | template
CREATE INDEX IF NOT EXISTS tickets_origin_created ON tickets (origin, created_at);
