-- Migration 001: Initial tables for user management and usage tracking
-- Run this in Supabase SQL Editor for project: piclftokhzkdywupdyjo
-- Date: 2026-03-24

-- ═══════════════════════════════════════════════════════════════════════════
-- 1. Profiles (extends Supabase auth.users / Clerk users)
-- ═══════════════════════════════════════════════════════════════════════════

create table if not exists profiles (
    id text primary key,                    -- Clerk user_id (e.g., user_2x...)
    email text not null,
    full_name text default '',
    company text default '',
    role text default 'researcher',         -- researcher, analyst, director, developer
    plan text not null default 'free',      -- free, growth, business, enterprise
    stripe_customer_id text,                -- Stripe customer ID for billing
    stripe_subscription_id text,            -- Active subscription ID
    plan_started_at timestamptz,
    plan_expires_at timestamptz,            -- For annual plans
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create index if not exists idx_profiles_email on profiles(email);
create index if not exists idx_profiles_plan on profiles(plan);
create index if not exists idx_profiles_stripe on profiles(stripe_customer_id);

-- ═══════════════════════════════════════════════════════════════════════════
-- 2. API Keys (user-managed, for Claude Desktop / Claude Code / direct API)
-- ═══════════════════════════════════════════════════════════════════════════

create table if not exists api_keys (
    id uuid default gen_random_uuid() primary key,
    user_id text not null references profiles(id) on delete cascade,
    name text not null default 'Default',   -- User-chosen label
    key_prefix text not null,               -- First 8 chars of key (for display: sk_live_02099ac9...)
    key_hash text not null,                 -- SHA256 hash of full key
    plan text not null default 'free',      -- Inherited from user's plan at creation
    scopes text[] default '{"process","metadata","convert","crosstab","frequency","parse_ticket"}',
    is_active boolean default true,
    last_used_at timestamptz,
    created_at timestamptz default now(),
    revoked_at timestamptz                  -- Soft delete
);

create index if not exists idx_api_keys_user on api_keys(user_id);
create index if not exists idx_api_keys_hash on api_keys(key_hash);
create index if not exists idx_api_keys_active on api_keys(user_id, is_active) where is_active = true;

-- ═══════════════════════════════════════════════════════════════════════════
-- 3. Usage Tracking (per user per day — for plan enforcement)
-- ═══════════════════════════════════════════════════════════════════════════

create table if not exists usage_daily (
    id uuid default gen_random_uuid() primary key,
    user_id text not null references profiles(id) on delete cascade,
    usage_date date not null default current_date,
    files_uploaded int default 0,
    requests_total int default 0,
    requests_by_endpoint jsonb default '{}',  -- {"frequency": 5, "crosstab": 12, ...}
    bytes_processed bigint default 0,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    unique(user_id, usage_date)
);

create index if not exists idx_usage_daily_user_date on usage_daily(user_id, usage_date);

-- ═══════════════════════════════════════════════════════════════════════════
-- 4. Usage Monthly (aggregated — for billing dashboards)
-- ═══════════════════════════════════════════════════════════════════════════

create table if not exists usage_monthly (
    id uuid default gen_random_uuid() primary key,
    user_id text not null references profiles(id) on delete cascade,
    usage_month date not null,              -- First day of month (2026-03-01)
    files_uploaded int default 0,
    requests_total int default 0,
    bytes_processed bigint default 0,
    created_at timestamptz default now(),
    unique(user_id, usage_month)
);

create index if not exists idx_usage_monthly_user on usage_monthly(user_id, usage_month);

-- ═══════════════════════════════════════════════════════════════════════════
-- 5. RPC: Increment daily usage (called from API on each request)
-- ═══════════════════════════════════════════════════════════════════════════

create or replace function increment_usage(
    p_user_id text,
    p_endpoint text,
    p_bytes bigint default 0,
    p_is_file_upload boolean default false
)
returns void
language plpgsql
security definer
as $$
begin
    insert into usage_daily (user_id, usage_date, files_uploaded, requests_total, bytes_processed, requests_by_endpoint)
    values (
        p_user_id,
        current_date,
        case when p_is_file_upload then 1 else 0 end,
        1,
        p_bytes,
        jsonb_build_object(p_endpoint, 1)
    )
    on conflict (user_id, usage_date)
    do update set
        files_uploaded = usage_daily.files_uploaded + case when p_is_file_upload then 1 else 0 end,
        requests_total = usage_daily.requests_total + 1,
        bytes_processed = usage_daily.bytes_processed + p_bytes,
        requests_by_endpoint = usage_daily.requests_by_endpoint ||
            jsonb_build_object(
                p_endpoint,
                coalesce((usage_daily.requests_by_endpoint->>p_endpoint)::int, 0) + 1
            ),
        updated_at = now();
end;
$$;

-- ═══════════════════════════════════════════════════════════════════════════
-- 6. RPC: Check daily file limit (for plan enforcement)
-- ═══════════════════════════════════════════════════════════════════════════

create or replace function check_daily_file_limit(
    p_user_id text,
    p_max_files int
)
returns boolean
language plpgsql
security definer
as $$
declare
    v_count int;
begin
    if p_max_files is null then
        return true;  -- Unlimited
    end if;

    select coalesce(files_uploaded, 0) into v_count
    from usage_daily
    where user_id = p_user_id and usage_date = current_date;

    return coalesce(v_count, 0) < p_max_files;
end;
$$;

-- ═══════════════════════════════════════════════════════════════════════════
-- 7. RLS Policies
-- ═══════════════════════════════════════════════════════════════════════════

-- Enable RLS
alter table profiles enable row level security;
alter table api_keys enable row level security;
alter table usage_daily enable row level security;
alter table usage_monthly enable row level security;

-- Service role can do everything (API server uses service_role_key)
-- No user-facing RLS needed since all access is via the API server
create policy "Service role full access on profiles"
    on profiles for all using (true) with check (true);

create policy "Service role full access on api_keys"
    on api_keys for all using (true) with check (true);

create policy "Service role full access on usage_daily"
    on usage_daily for all using (true) with check (true);

create policy "Service role full access on usage_monthly"
    on usage_monthly for all using (true) with check (true);
