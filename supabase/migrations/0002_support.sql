-- Support tickets (services/runtime/app/support/). Schema `accnomos`, same rules as 0001_accounts.sql.
--
-- A ticket belongs to one registry account; its messages are the thread (the user's words, admins' replies and
-- admins' internal notes, which the user never sees). `context` holds what the user ticked to attach when the ticket
-- was made (page, app version, recent errors, PayPal connection status); it never holds books, receipts, amounts or
-- tokens unless the user ticked "include financial details", and even then only the short summary the app showed.
--
-- Row-level security is ON and there are NO policies: only the runtime, with the service-role key, reads and writes.
--
-- NOT APPLIED to the live project yet: the owner runs it once in the Supabase SQL editor (or `supabase db push`).
-- Re-running is safe: every statement is idempotent.

create table if not exists accnomos.support_tickets (
  id              uuid primary key default gen_random_uuid(),
  number          bigint generated always as identity unique,  -- shown to people: "Ticket 1042"
  account_id      uuid not null references accnomos.accounts (id) on delete cascade,
  email           text,
  subject         text not null check (char_length(subject) between 1 and 200),
  category        text not null check (category in
                    ('how_to', 'bug', 'account', 'billing', 'paypal', 'hmrc_vat', 'bank', 'storage', 'mobile', 'other')),
  status          text not null default 'open' check (status in ('open', 'pending', 'solved')),
  source          text not null default 'form' check (source in ('form', 'assistant', 'voice')),
  page            text check (char_length(page) <= 300),
  app             text check (app in ('web', 'android', 'ios', 'api')),
  version         text check (char_length(version) <= 40),
  context         jsonb not null default '{}'::jsonb,
  action_id       text unique check (char_length(action_id) <= 32),  -- the assistant card it came from: made once
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  last_reply_by   text check (last_reply_by in ('user', 'admin')),
  solved_at       timestamptz
);

create index if not exists support_tickets_account_idx on accnomos.support_tickets (account_id, updated_at desc);
create index if not exists support_tickets_status_idx on accnomos.support_tickets (status, updated_at desc);

create table if not exists accnomos.support_messages (
  id          uuid primary key default gen_random_uuid(),
  ticket_id   uuid not null references accnomos.support_tickets (id) on delete cascade,
  at          timestamptz not null default now(),
  author      text not null check (author in ('user', 'admin')),
  author_email text,
  body        text not null check (char_length(body) between 1 and 10000),
  internal    boolean not null default false,  -- an admin's note: never shown to the user
  emailed     boolean not null default false   -- an admin reply that was also emailed to the user
);

create index if not exists support_messages_ticket_idx on accnomos.support_messages (ticket_id, at);

alter table accnomos.support_tickets enable row level security;
alter table accnomos.support_messages enable row level security;

revoke all on accnomos.support_tickets from public;
revoke all on accnomos.support_messages from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on accnomos.support_tickets from anon';
    execute 'revoke all on accnomos.support_messages from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on accnomos.support_tickets from authenticated';
    execute 'revoke all on accnomos.support_messages from authenticated';
  end if;
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant select, insert, update, delete on accnomos.support_tickets to service_role';
    execute 'grant select, insert, update, delete on accnomos.support_messages to service_role';
    execute 'grant usage, select on all sequences in schema accnomos to service_role';
  end if;
end $$;
