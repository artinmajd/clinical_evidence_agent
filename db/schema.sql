create extension if not exists vector;

create table if not exists trial_chunks (
    id bigserial primary key,
    nct_id text not null,
    chunk_text text not null,
    phases text[] not null default '{}',
    conditions text[] not null default '{}',
    has_results boolean not null default false,
    embedding vector(768) not null
);

alter table trial_chunks
    add column if not exists chunk_text_tsv tsvector
    generated always as (to_tsvector('english', chunk_text)) stored;

create index if not exists trial_chunks_tsv_idx
    on trial_chunks using gin (chunk_text_tsv);

-- Phase 4 Step 3: synthetic access control. Real column, fake data - see
-- guardrails/access_control.py for which roles may see which groups, and
-- db/migrate_permission_groups.py for how existing rows get tagged. New
-- rows default to 'public' so ingestion doesn't need to change to stay
-- correct; the migration script is what assigns the 'restricted' subset.
alter table trial_chunks
    add column if not exists permission_group text not null default 'public';
