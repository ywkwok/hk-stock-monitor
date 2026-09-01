-- ============================================================
-- Supabase schema for hk-stock-monitor
-- Run this in the Supabase SQL editor once.
-- ============================================================

-- Query / monitor history log
create table if not exists public.stock_monitor_log (
    id bigint generated always as identity primary key,
    symbol text not null,
    snapshot jsonb not null default '{}'::jsonb,
    chart_url text,
    created_at timestamptz not null default now()
);

-- Optional index for fast lookups by symbol + time
create index if not exists idx_stock_monitor_log_symbol_time
    on public.stock_monitor_log (symbol, created_at desc);

-- Row Level Security: allow server (service role) writes, anon read-only.
alter table public.stock_monitor_log enable row level security;

create policy "anon read stock_monitor_log"
    on public.stock_monitor_log for select
    using (true);

create policy "service write stock_monitor_log"
    on public.stock_monitor_log for insert
    with check (auth.role() = 'service_role' or auth.role() = 'anon');
