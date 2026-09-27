-- =============================================================
-- Lets more than one live/paper strategy share these tables without
-- mixing their records. Every existing row (and every row the master
-- runner keeps writing) is 'master'. The trend + dip-buy blend
-- (live/run_blend.py, its own Alpaca paper account) writes:
--   trades:            'blend_trend' / 'blend_dip'  (one per sleeve)
--   signals:           'blend'
--   account_snapshots: 'blend'
--
-- Run this in the Supabase SQL Editor, same as 001-006, BEFORE merging
-- the code that uses it -- the live runners and dashboard filter on
-- this column. Safe to re-run (IF NOT EXISTS).
-- =============================================================

alter table trades add column if not exists strategy text not null default 'master';
alter table signals add column if not exists strategy text not null default 'master';
alter table account_snapshots add column if not exists strategy text not null default 'master';

create index if not exists idx_trades_strategy_open on trades (strategy, ticker) where exit_date is null;
create index if not exists idx_signals_strategy_date on signals (strategy, signal_date desc);
create index if not exists idx_snapshots_strategy_created on account_snapshots (strategy, created_at);
