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
