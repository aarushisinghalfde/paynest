# db

Database changes are plain SQL files in `migrations/`, applied in name order by
`scripts/migrate.py`. Each file runs once: the runner records it in the
`schema_migrations` table. To change the schema, add the next file
(`002_tickets.sql`, …); never edit a file that has already been applied.
