-- =============================================================
-- Supports tracking pyramided positions in LIVE/paper trading, not just
-- backtests. A pyramided stack is several separately-sized units of the
-- same ticker, each with its own entry price/shares/risk (needed for
-- correct per-unit R-multiple accounting) -- the `trades` table already
-- allows multiple open rows per ticker (no uniqueness constraint), this
-- just adds a column to distinguish and order them.
--
-- Run this in the Supabase SQL Editor, same as 001-003. Safe to run
-- even if the column already exists (IF NOT EXISTS).
--
--   unit_number  -- 1 = original entry, 2+ = pyramid adds, in order
-- =============================================================

alter table trades add column if not exists unit_number int not null default 1;
