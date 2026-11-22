-- Phase B: knowledge import. Articles uploaded by support (e.g. a Confluence export) are
-- masked, split into kb_chunks rows (source_kind 'kb_article') and recorded here, so an
-- import can be listed and withdrawn. The agent reloads knowledge when this table changes.
CREATE TABLE IF NOT EXISTS knowledge_imports (
    kb_id          text PRIMARY KEY,
    title          text NOT NULL,
    region         text NOT NULL,                 -- IN | UAE | ALL
    language       text NOT NULL,
    topic          text NOT NULL,                 -- howto | statutory:<topic> (never auto-sent)
    chunks         int  NOT NULL,
    masked_counts  jsonb NOT NULL DEFAULT '{}',
    created_title  boolean NOT NULL DEFAULT false, -- the import added the KB title row (remove it on withdraw)
    active         boolean NOT NULL DEFAULT true,
    imported_by    text,
    imported_at    timestamptz NOT NULL DEFAULT now()
);
