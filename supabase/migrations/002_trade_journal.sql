-- =============================================================
-- Adds a human-readable trade journal to the `trades` table, in the
-- style of the trade diary examples in "Way of the Turtle" — e.g.
-- "Entered long at $400.00 because it was a 60 day breakout according
-- to the rules of System 2."
--
-- Run this in the Supabase SQL Editor (or `supabase db push`), same as
-- 001_initial_schema.sql. Safe to run even if some columns already
-- exist (IF NOT EXISTS).
--
--   entry_reason / exit_reason_detail  — the "why", as a plain sentence
--                                         fragment (e.g. "price closed
--                                         above its 20-day moving
--                                         average, with volume above
--                                         its 20-day average")
--   entry_log / exit_log               — the full journal-style sentence,
--                                         ready to display or export as-is
-- =============================================================

alter table trades add column if not exists entry_reason text;
alter table trades add column if not exists entry_log text;
alter table trades add column if not exists exit_reason_detail text;
alter table trades add column if not exists exit_log text;
