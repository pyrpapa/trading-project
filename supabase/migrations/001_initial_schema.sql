-- =============================================================
-- Run this in the Supabase SQL Editor (or via `supabase db push`
-- if you use the CLI) to set up the tables this project needs.
-- =============================================================

-- Every signal the strategy generates, whether or not it was acted on.
create table if not exists signals (
    id bigint generated always as identity primary key,
    ticker text not null,
    signal_date date not null,
    signal_type text not null check (signal_type in ('BUY', 'SELL')),
    price numeric not null,
    reason text,                 -- e.g. 'ma_crossover', 'stop_loss', 'trend_exit'
    created_at timestamptz not null default now()
);

-- One row per backtest you run, snapshotting the config used and the
-- resulting metrics — so you can compare tweaks over time.
create table if not exists backtest_runs (
    id bigint generated always as identity primary key,
    run_label text,                    -- optional name, e.g. 'ma20-stop8'
    config jsonb not null,             -- full strategy.yaml snapshot
    watchlist text[] not null,
    start_date date not null,
    end_date date not null,
    metrics jsonb not null,            -- total_return_pct, max_drawdown_pct, etc.
    created_at timestamptz not null default now()
);

-- Actual trades — filled once you're paper/live trading via Alpaca.
-- Backtest trades can also be logged here with source = 'backtest'.
create table if not exists trades (
    id bigint generated always as identity primary key,
    ticker text not null,
    source text not null check (source in ('backtest', 'paper', 'live')),
    entry_date date not null,
    entry_price numeric not null,
    exit_date date,
    exit_price numeric,
    shares numeric not null,
    pnl numeric,
    return_pct numeric,
    exit_reason text,
    backtest_run_id bigint references backtest_runs(id),
    created_at timestamptz not null default now()
);

-- Audit trail of config changes, independent of backtest runs.
create table if not exists config_history (
    id bigint generated always as identity primary key,
    config jsonb not null,
    note text,                          -- why you changed it
    created_at timestamptz not null default now()
);

-- Snapshot of account state each time the live runner checks in —
-- this is what powers the dashboard's equity curve for paper/live trading.
create table if not exists account_snapshots (
    id bigint generated always as identity primary key,
    equity numeric not null,
    cash numeric not null,
    portfolio_value numeric not null,
    buying_power numeric not null,
    mode text not null check (mode in ('paper', 'live')),
    created_at timestamptz not null default now()
);

-- Helpful indexes for the queries the dashboard will run most.
create index if not exists idx_signals_ticker_date on signals (ticker, signal_date desc);
create index if not exists idx_trades_ticker on trades (ticker);
create index if not exists idx_backtest_runs_created on backtest_runs (created_at desc);

-- Row Level Security: since this is single-user, the simplest safe
-- setup is to enable RLS and only allow access via the service role
-- key (used by your backend scripts), not the public anon key.
alter table signals enable row level security;
alter table trades enable row level security;
alter table backtest_runs enable row level security;
alter table config_history enable row level security;
alter table account_snapshots enable row level security;

-- No INSERT/UPDATE/DELETE policies are created for any non-service role
-- on purpose — writes only happen via the service_role key from your
-- backend scripts. That key must never appear in frontend code.
--
-- For the dashboard to READ this data from the browser, it authenticates
-- as a real Supabase Auth user (you) rather than using the anon key
-- wide open. These policies allow SELECT only for a logged-in user.
create policy "Authenticated read access" on signals for select using (auth.role() = 'authenticated');
create policy "Authenticated read access" on trades for select using (auth.role() = 'authenticated');
create policy "Authenticated read access" on backtest_runs for select using (auth.role() = 'authenticated');
create policy "Authenticated read access" on config_history for select using (auth.role() = 'authenticated');
create policy "Authenticated read access" on account_snapshots for select using (auth.role() = 'authenticated');

-- To create your login: Supabase Dashboard -> Authentication -> Users
-- -> Add User (email + password). The dashboard app will prompt for
-- these credentials and use Supabase Auth to sign in — no separate
-- user system needed.
