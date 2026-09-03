-- Persists the report link so it survives a re-fetch, not just the
-- original run's live API response. Before this, report_url only ever
-- existed in api/run_backtest.py's response to the browser -- it was
-- never written to the row itself, so the Backtest page's "Saved
-- backtests" panel (which re-fetches from Supabase, not from memory)
-- always showed "no report" for anything saved, even when a report
-- had genuinely been generated and uploaded. report_error is added for
-- the same reason, so a saved row can show "failed" with the same
-- detail the live view already did, instead of losing that information
-- entirely once fetched back from the database.
alter table backtest_runs add column if not exists report_url text;
alter table backtest_runs add column if not exists report_error text;
