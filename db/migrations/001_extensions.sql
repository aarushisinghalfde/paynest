-- Enable pgvector (embeddings, phase 4) and pg_trgm (text search, phase 8).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
