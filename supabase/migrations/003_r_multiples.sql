-- =============================================================
-- Adds R-multiple risk/reward tracking to the `trades` table — every
-- trade's P&L expressed as a multiple of its own initial planned risk
-- (the Turtles' own yardstick, e.g. "+2.3R", "-1.0R"). Works for both
-- flat-% stops (v1-v4 style) and N/ATR-based stops (risk.sizing_method:
-- atr_unit), since both get converted to a per-trade dollar risk figure.
--
-- Run this in the Supabase SQL Editor, same as 001 and 002. Safe to run
-- even if some columns already exist (IF NOT EXISTS).
--
--   sizing_method         — "pct" or "atr_unit", whichever sized this trade
--   initial_risk_dollars  — "1R" for this trade, in dollars (set at entry)
--   r_multiple            — pnl / initial_risk_dollars (set at exit)
-- =============================================================

alter table trades add column if not exists sizing_method text;
alter table trades add column if not exists initial_risk_dollars numeric;
alter table trades add column if not exists r_multiple numeric;
