-- Accnomos account registry (docs/billing/PLANS_AND_CONTRACT.md). Schema `accnomos`.
--
-- Account metadata only: who signed up, their plan and billing state, monthly usage counts, promo codes, the admin
-- audit log, product events and bug reports. Never books, documents, receipts, amounts or other services' tokens.
--
-- Row-level security is ON for every table and there are NO policies: the anon and authenticated keys can read or
-- write nothing. Only the runtime, with the service-role key (which bypasses RLS), reads and writes. Nothing here is
-- exposed to browsers directly.
--
-- Run once in the Supabase SQL editor (or `supabase db push`). Re-running is safe: every statement is idempotent.

create extension if not exists pgcrypto;

create schema if not exists accnomos;
revoke all on schema accnomos from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on schema accnomos from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on schema accnomos from authenticated';
  end if;
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant usage on schema accnomos to service_role';
  end if;
end $$;

-- --------------------------------------------------------------------------------------------------------------
-- Plans (limits are editable in the admin without a deploy)
-- --------------------------------------------------------------------------------------------------------------

create table if not exists accnomos.plans (
  code               text primary key check (code in ('starter', 'comprehensive', 'ultimate')),
  name               text not null,
  price_month_pence  integer not null check (price_month_pence >= 0),
  price_year_pence   integer not null check (price_year_pence >= 0),
  stripe_price_month text,
  stripe_price_year  text,
  limits             jsonb not null default '{}'::jsonb,
  active             boolean not null default true,
  sort               integer not null default 0
);

-- Limits: a number per month (docs, ask, invoices) or of things set up (users, bank_feeds, marketplaces,
-- autopilot_rules, payroll_employees); null = unlimited, 0 = not on this plan. Prices ex VAT, in pence.
insert into accnomos.plans (code, name, price_month_pence, price_year_pence, limits, active, sort) values
  ('starter', 'Starter', 1000, 10000,
   '{"users": 1, "docs": 50, "ask": 100, "bank_feeds": 1, "invoices": 20, "marketplaces": 0,
     "payroll_employees": 0, "autopilot_rules": 5, "multi_currency": false, "projects": false,
     "support": "email"}'::jsonb, true, 1),
  ('comprehensive', 'Comprehensive', 2000, 20000,
   '{"users": 3, "docs": 300, "ask": 500, "bank_feeds": 3, "invoices": null, "marketplaces": 1,
     "payroll_employees": 3, "autopilot_rules": null, "multi_currency": false, "projects": false,
     "support": "email"}'::jsonb, true, 2),
  ('ultimate', 'Ultimate', 5000, 50000,
   '{"users": 10, "docs": 1500, "ask": 3000, "bank_feeds": null, "invoices": null, "marketplaces": null,
     "payroll_employees": 20, "autopilot_rules": null, "multi_currency": true, "projects": true,
     "support": "priority_email"}'::jsonb, true, 3)
on conflict (code) do nothing;

-- --------------------------------------------------------------------------------------------------------------
-- Accounts
-- --------------------------------------------------------------------------------------------------------------

create table if not exists accnomos.accounts (
  id                     uuid primary key default gen_random_uuid(),
  email                  text not null,
  display_name           text,
  auth_kind              text not null check (auth_kind in ('personal', 'work', 'google')),
  auth_subject           text not null,                 -- Graph /me id or Google `sub`
  created_at             timestamptz not null default now(),
  last_seen_at           timestamptz,
  plan_code              text not null default 'comprehensive' references accnomos.plans (code),
  status                 text not null default 'trialing'
                         check (status in ('trialing', 'active', 'past_due', 'trial_ended', 'cancelled', 'comped')),
  trial_ends_at          timestamptz,
  comp_until             timestamptz,
  stripe_customer_id     text unique,
  stripe_subscription_id text unique,
  billing_interval       text check (billing_interval in ('month', 'year')),
  current_period_end     timestamptz,                   -- mirrored from Stripe
  cancel_at_period_end   boolean not null default false, -- mirrored from Stripe
  country                text,
  notes                  text,                          -- admin only
  analytics_opt_out      boolean not null default false, -- Settings > Privacy
  unique (auth_kind, auth_subject)
);

create index if not exists accounts_email_idx on accnomos.accounts (lower(email));
create index if not exists accounts_status_idx on accnomos.accounts (status);
create index if not exists accounts_plan_idx on accnomos.accounts (plan_code);
create index if not exists accounts_created_idx on accnomos.accounts (created_at desc);
create index if not exists accounts_trial_ends_idx on accnomos.accounts (trial_ends_at) where status = 'trialing';

-- --------------------------------------------------------------------------------------------------------------
-- Usage (per account per month, 1st of the month UTC)
-- --------------------------------------------------------------------------------------------------------------

create table if not exists accnomos.usage (
  account_id           uuid not null references accnomos.accounts (id) on delete cascade,
  month                date not null check (extract(day from month) = 1),
  docs                 integer not null default 0 check (docs >= 0),
  ask                  integer not null default 0 check (ask >= 0),
  invoices             integer not null default 0 check (invoices >= 0),
  topup_docs_remaining integer not null default 0 check (topup_docs_remaining >= 0),
  topup_expires_at     timestamptz,                   -- 12 months after the latest top-up
  primary key (account_id, month)
);

create index if not exists usage_month_idx on accnomos.usage (month);

-- --------------------------------------------------------------------------------------------------------------
-- Promo codes and redemptions
-- --------------------------------------------------------------------------------------------------------------

create table if not exists accnomos.promo_codes (
  code             text primary key check (code ~ '^[A-Z0-9_-]{3,40}$'),
  kind             text not null check (kind in ('percent', 'fixed', 'free_months')),
  value            integer not null check (value > 0),  -- percent 1-100 | pence off | months free
  plan_codes       text[],                              -- null = any plan
  max_redemptions  integer check (max_redemptions is null or max_redemptions > 0),
  redeemed_count   integer not null default 0 check (redeemed_count >= 0),
  expires_at       timestamptz,
  active           boolean not null default true,
  created_by       text,
  created_at       timestamptz not null default now(),
  stripe_coupon_id text,
  duration_months  integer check (duration_months is null or duration_months > 0), -- percent/fixed: null = once
  check (kind <> 'percent' or value <= 100)
);

create table if not exists accnomos.redemptions (
  id          bigint generated always as identity primary key,
  code        text not null references accnomos.promo_codes (code) on update cascade,
  account_id  uuid not null references accnomos.accounts (id) on delete cascade,
  redeemed_at timestamptz not null default now(),
  unique (code, account_id)
);

create index if not exists redemptions_account_idx on accnomos.redemptions (account_id);

-- --------------------------------------------------------------------------------------------------------------
-- Admin audit log (every admin write)
-- --------------------------------------------------------------------------------------------------------------

create table if not exists accnomos.admin_audit (
  id          bigint generated always as identity primary key,
  at          timestamptz not null default now(),
  admin_email text not null,
  account_id  uuid references accnomos.accounts (id) on delete set null,
  action      text not null,
  detail      jsonb not null default '{}'::jsonb
);

create index if not exists admin_audit_at_idx on accnomos.admin_audit (at desc);
create index if not exists admin_audit_account_idx on accnomos.admin_audit (account_id, at desc);

-- --------------------------------------------------------------------------------------------------------------
-- Product events (first-party analytics; retention 13 months) and bug reports
-- --------------------------------------------------------------------------------------------------------------

create table if not exists accnomos.events (
  id         bigint generated always as identity primary key,
  at         timestamptz not null default now(),
  account_id uuid references accnomos.accounts (id) on delete cascade,
  name       text not null check (name ~ '^[a-z][a-z0-9_]{1,47}$'),
  props      jsonb not null default '{}'::jsonb,
  app        text not null default 'api' check (app in ('web', 'android', 'api')),
  version    text check (char_length(version) <= 40)
);

create index if not exists events_at_idx on accnomos.events (at);
create index if not exists events_name_at_idx on accnomos.events (name, at);
create index if not exists events_account_at_idx on accnomos.events (account_id, at);

create table if not exists accnomos.bug_reports (
  id              uuid primary key default gen_random_uuid(),
  at              timestamptz not null default now(),
  account_id      uuid references accnomos.accounts (id) on delete set null,
  email           text,
  message         text not null check (char_length(message) between 1 and 5000),
  page            text check (char_length(page) <= 300),
  app             text check (app in ('web', 'android', 'api')),
  version         text check (char_length(version) <= 40),
  ua              text check (char_length(ua) <= 500),
  screenshot_path text,
  status          text not null default 'new' check (status in ('new', 'triaged', 'fixed', 'wont_fix')),
  admin_notes     text,
  closed_at       timestamptz                           -- set when fixed / wont_fix; retention runs from here
);

create index if not exists bug_reports_status_idx on accnomos.bug_reports (status, at desc);

-- Stripe webhook idempotency: one row per event id handled
create table if not exists accnomos.stripe_events (
  id          text primary key,
  type        text not null,
  received_at timestamptz not null default now()
);

-- --------------------------------------------------------------------------------------------------------------
-- RLS on, no policies; table rights for the service role only
-- --------------------------------------------------------------------------------------------------------------

alter table accnomos.plans enable row level security;
alter table accnomos.accounts enable row level security;
alter table accnomos.usage enable row level security;
alter table accnomos.promo_codes enable row level security;
alter table accnomos.redemptions enable row level security;
alter table accnomos.admin_audit enable row level security;
alter table accnomos.events enable row level security;
alter table accnomos.bug_reports enable row level security;
alter table accnomos.stripe_events enable row level security;

revoke all on all tables in schema accnomos from public;
revoke all on all sequences in schema accnomos from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on all tables in schema accnomos from anon';
    execute 'revoke all on all sequences in schema accnomos from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on all tables in schema accnomos from authenticated';
    execute 'revoke all on all sequences in schema accnomos from authenticated';
  end if;
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant select, insert, update, delete on all tables in schema accnomos to service_role';
    execute 'grant usage, select on all sequences in schema accnomos to service_role';
  end if;
end $$;

-- --------------------------------------------------------------------------------------------------------------
-- Functions (atomic counters, code claims, admin aggregates). Service role only.
-- --------------------------------------------------------------------------------------------------------------

-- The usage row for (account, month), created with any unexpired top-up balance carried from the latest earlier row.
create or replace function accnomos.ensure_usage(p_account uuid, p_month date)
returns void language plpgsql set search_path = accnomos, pg_temp as $$
begin
  insert into usage (account_id, month, topup_docs_remaining, topup_expires_at)
  select p_account, p_month,
         coalesce((select u.topup_docs_remaining from usage u
                   where u.account_id = p_account and u.month < p_month and u.topup_expires_at > now()
                   order by u.month desc limit 1), 0),
         (select u.topup_expires_at from usage u
          where u.account_id = p_account and u.month < p_month and u.topup_expires_at > now()
          order by u.month desc limit 1)
  on conflict (account_id, month) do nothing;
end $$;

-- Add p_n to p_field ('docs' | 'ask' | 'invoices') unless that passes p_limit (null: no limit). For docs, what is
-- over the monthly allowance comes from the top-up balance. Returns {"ok": bool, "usage": row}.
create or replace function accnomos.bump_usage(p_account uuid, p_month date, p_field text, p_n integer,
                                               p_limit integer)
returns jsonb language plpgsql set search_path = accnomos, pg_temp as $$
declare
  r usage%rowtype;
  topup integer;
  from_topup integer := 0;
begin
  if p_field not in ('docs', 'ask', 'invoices') or p_n < 0 then
    raise exception 'bad usage field %', p_field;
  end if;
  perform ensure_usage(p_account, p_month);
  select * into r from usage where account_id = p_account and month = p_month for update;
  topup := case when r.topup_expires_at > now() then r.topup_docs_remaining else 0 end;
  if p_limit is not null then
    if p_field = 'docs' then
      from_topup := greatest(0, p_n - greatest(0, p_limit - r.docs));
      if from_topup > topup then
        return jsonb_build_object('ok', false, 'usage', to_jsonb(r));
      end if;
    elsif (case p_field when 'ask' then r.ask else r.invoices end) + p_n > p_limit then
      return jsonb_build_object('ok', false, 'usage', to_jsonb(r));
    end if;
  end if;
  update usage set
    docs = docs + case when p_field = 'docs' then p_n else 0 end,
    ask = ask + case when p_field = 'ask' then p_n else 0 end,
    invoices = invoices + case when p_field = 'invoices' then p_n else 0 end,
    topup_docs_remaining = case when p_limit is not null and p_field = 'docs' then topup - from_topup
                                else topup_docs_remaining end
  where account_id = p_account and month = p_month
  returning * into r;
  return jsonb_build_object('ok', true, 'usage', to_jsonb(r));
end $$;

-- A paid top-up: p_n more documents, the whole balance valid 12 months from now.
create or replace function accnomos.add_topup(p_account uuid, p_month date, p_n integer)
returns jsonb language plpgsql set search_path = accnomos, pg_temp as $$
declare
  r usage%rowtype;
begin
  perform ensure_usage(p_account, p_month);
  update usage set
    topup_docs_remaining = (case when topup_expires_at > now() then topup_docs_remaining else 0 end) + p_n,
    topup_expires_at = now() + interval '12 months'
  where account_id = p_account and month = p_month
  returning * into r;
  return to_jsonb(r);
end $$;

-- One redemption of p_code by p_account, if the code allows it. Returns the code row, or null.
create or replace function accnomos.claim_code(p_code text, p_account uuid)
returns jsonb language plpgsql set search_path = accnomos, pg_temp as $$
declare
  r promo_codes%rowtype;
begin
  update promo_codes set redeemed_count = redeemed_count + 1
  where code = p_code and active
    and (expires_at is null or expires_at > now())
    and (max_redemptions is null or redeemed_count < max_redemptions)
    and not exists (select 1 from redemptions x where x.code = p_code and x.account_id = p_account)
  returning * into r;
  if not found then
    return null;
  end if;
  insert into redemptions (code, account_id) values (p_code, p_account);
  return to_jsonb(r);
end $$;

-- GET /admin/metrics
create or replace function accnomos.admin_metrics()
returns jsonb language sql stable set search_path = accnomos, pg_temp as $$
  with days as (
    select generate_series((now() at time zone 'utc')::date - 29, (now() at time zone 'utc')::date, '1 day')::date d
  ),
  active as (
    select a.plan_code, a.billing_interval, p.price_month_pence, p.price_year_pence
    from accounts a join plans p on p.code = a.plan_code where a.status = 'active'
  ),
  ending as (
    select id, email, trial_ends_at from accounts
    where status = 'trialing' and trial_ends_at between now() and now() + interval '7 days'
  )
  select jsonb_build_object(
    'signups_by_day', (select coalesce(jsonb_agg(jsonb_build_object('day', d, 'count',
        (select count(*) from accounts a where (a.created_at at time zone 'utc')::date = d)) order by d), '[]')
        from days),
    'total_accounts', (select count(*) from accounts),
    'trialing', (select count(*) from accounts where status = 'trialing'),
    'active_by_plan', (select coalesce(jsonb_object_agg(p.code,
        (select count(*) from accounts a where a.status = 'active' and a.plan_code = p.code)), '{}') from plans p),
    'active', (select count(*) from accounts where status = 'active'),
    'past_due', (select count(*) from accounts where status = 'past_due'),
    'cancelled', (select count(*) from accounts where status = 'cancelled'),
    'trial_ended', (select count(*) from accounts where status = 'trial_ended'),
    'comped', (select count(*) from accounts where status = 'comped'),
    'mrr_pence', (select coalesce(sum(case when billing_interval = 'year' then round(price_year_pence / 12.0)
                                           else price_month_pence end), 0)::bigint from active),
    'trials_ending_7d', (select count(*) from ending),
    'trials_ending', (select coalesce(jsonb_agg(to_jsonb(e) order by e.trial_ends_at), '[]')
                      from (select * from ending order by trial_ends_at limit 50) e)
  );
$$;

-- GET /admin/analytics?from=&to= (inclusive UTC days)
create or replace function accnomos.analytics(p_from date, p_to date)
returns jsonb language sql stable set search_path = accnomos, pg_temp as $$
  with ev as (
    select * from events where (at at time zone 'utc')::date between p_from and p_to
  ),
  signups as (
    select id from accounts where (created_at at time zone 'utc')::date between p_from and p_to
  ),
  scanned as (
    select distinct e.account_id from events e join signups s on s.id = e.account_id
    where e.name = 'document_scanned'
  ),
  approved as (
    select distinct e.account_id from events e join scanned s on s.account_id = e.account_id
    where e.name = 'proposal_approved'
  ),
  ended as (
    select id, status from accounts where (trial_ends_at at time zone 'utc')::date between p_from and p_to
  ),
  converted as (
    select id from ended
    where status in ('active', 'past_due')
       or id in (select account_id from events where name = 'subscription_active')
  ),
  cancelled as (
    select distinct account_id from ev where name = 'subscription_cancelled' and account_id is not null
  ),
  base as (
    select (select count(*) from accounts where status in ('active', 'past_due'))
           + (select count(*) from cancelled) n
  ),
  feature_names(name) as (
    values ('document_scanned'), ('proposal_approved'), ('bank_synced'), ('ask'), ('vat_export'),
           ('itsa_export'), ('ebay_sync')
  )
  select jsonb_build_object(
    'from', p_from,
    'to', p_to,
    'daily_active', (select coalesce(jsonb_agg(jsonb_build_object('day', d, 'count',
        (select count(distinct account_id) from ev where (at at time zone 'utc')::date = d)) order by d), '[]')
        from (select generate_series(p_from, p_to, '1 day')::date d) g),
    'funnel', jsonb_build_object('signed_up', (select count(*) from signups),
                                 'first_document', (select count(*) from scanned),
                                 'first_approval', (select count(*) from approved)),
    'features', (select jsonb_object_agg(f.name, (select count(*) from ev where ev.name = f.name))
                 from feature_names f),
    'trial_conversion', jsonb_build_object(
        'trials_ended', (select count(*) from ended),
        'converted', (select count(*) from converted),
        'rate', (select case when count(*) = 0 then null
                             else round((select count(*) from converted)::numeric / count(*), 4) end from ended)),
    'churn', jsonb_build_object(
        'cancelled', (select count(*) from cancelled),
        'active_at_start', (select n from base),
        'rate', (select case when n = 0 then null
                             else round((select count(*) from cancelled)::numeric / n, 4) end from base)),
    'errors_by_route', (select coalesce(jsonb_agg(jsonb_build_object('route', route, 'count', c) order by c desc), '[]')
        from (select trim(coalesce(props->>'method', '') || ' ' || coalesce(props->>'route', '?')) route, count(*) c
              from ev where name = 'api_error' group by 1 order by 2 desc limit 20) t)
  );
$$;

-- Retention (call daily from a Supabase cron job, see supabase/README.md): events 13 months, closed bug reports
-- 12 months after closing.
create or replace function accnomos.apply_retention()
returns jsonb language plpgsql set search_path = accnomos, pg_temp as $$
declare
  n_events integer;
  n_bugs integer;
begin
  delete from events where at < now() - interval '13 months';
  get diagnostics n_events = row_count;
  delete from bug_reports where status in ('fixed', 'wont_fix') and closed_at < now() - interval '12 months';
  get diagnostics n_bugs = row_count;
  return jsonb_build_object('events', n_events, 'bug_reports', n_bugs);
end $$;

revoke all on all functions in schema accnomos from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on all functions in schema accnomos from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on all functions in schema accnomos from authenticated';
  end if;
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant execute on all functions in schema accnomos to service_role';
  end if;
end $$;

-- New objects created later in this schema stay closed to anon/authenticated by default.
alter default privileges in schema accnomos revoke all on tables from public;
alter default privileges in schema accnomos revoke all on functions from public;

-- Screenshot bucket for bug reports (private; the service role uploads, admins read via signed URLs).
do $$
begin
  if exists (select 1 from information_schema.tables where table_schema = 'storage' and table_name = 'buckets') then
    insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    values ('bug-screenshots', 'bug-screenshots', false, 2097152, array['image/png', 'image/jpeg', 'image/webp'])
    on conflict (id) do nothing;
  end if;
end $$;
