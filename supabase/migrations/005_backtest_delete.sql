-- Lets the dashboard's logged-in user delete a saved backtest run from
-- the Backtest page's "Saved backtests" list (see BacktestPage.jsx's
-- handleDelete). Previously only SELECT was granted to authenticated
-- users on every table -- this repo has no public signup (see
-- README.md), so "authenticated" here just means "the one dashboard
-- login," same trust boundary every other authenticated policy in
-- 001_initial_schema.sql already assumes.

-- Cascade trades when their parent backtest_runs row is deleted.
-- 001_initial_schema.sql's original FK had no ON DELETE behavior
-- specified, which defaults to NO ACTION -- deleting a backtest_runs
-- row that still has trades referencing it via backtest_run_id would
-- otherwise fail with a foreign key violation.
alter table trades drop constraint if exists trades_backtest_run_id_fkey;
alter table trades add constraint trades_backtest_run_id_fkey
    foreign key (backtest_run_id) references backtest_runs(id) on delete cascade;

-- The cascade delete on trades is still itself subject to RLS (it's
-- implemented as a real DELETE on that table), so trades needs its own
-- delete policy too, not just backtest_runs.
create policy "Authenticated delete access" on backtest_runs for delete using (auth.role() = 'authenticated');
create policy "Authenticated delete access" on trades for delete using (auth.role() = 'authenticated');
