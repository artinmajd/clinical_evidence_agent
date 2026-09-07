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
