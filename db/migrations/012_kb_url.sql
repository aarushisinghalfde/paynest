-- A guide's page in the help centre (imported with the article as `url:`), given to the customer with the steps.
ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS url text;
