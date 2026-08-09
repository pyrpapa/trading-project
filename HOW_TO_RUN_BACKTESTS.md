# How to Run Backtests

Quick reference for running backtests on this project. Short version:
**backtests are local-only** — nothing about them requires pushing to
GitHub. GitHub Actions in this repo does something different (see the
bottom of this doc).

---

## Prerequisites (one-time)

```powershell
pip install -r requirements.txt
```

Re-run this if you haven't since `matplotlib` was added (needed for
`--chart`). Your `.env` file (Supabase credentials) should already be
set up from earlier — that's only needed if you use `--save`.

---

## Basic commands

```powershell
# Real data, default config (config/strategy.yaml)
python run_backtest.py

# Offline test data — no internet needed, useful for a quick sanity check
python run_backtest.py --synthetic

# A specific config instead of the default
python run_backtest.py --config config/strategy_v4.yaml

# Also save results to Supabase, with a label so you can find it later
python run_backtest.py --config config/strategy_v4.yaml --save --label "v4-run1"

# Also write an HTML chart report to results/<label>_report.html
python run_backtest.py --config config/strategy_v4.yaml --chart --save --label "v4-run1"
```

Flags combine freely and can be in any order. `--label` only matters
if you're using `--save` or `--chart` (it's used to name the output
file / the Supabase row).

## Comparing v4 vs. v5 (N-based sizing)

```powershell
python run_backtest.py --config config/strategy_v4.yaml --chart --save --label "v4-2019-2024"
python run_backtest.py --config config/strategy_v5_n_sizing.yaml --chart --save --label "v5-2019-2024"
```

Both configs currently run 2019-01-01 to 2024-12-31 (set in each
YAML's `backtest.start_date`/`end_date`). Open both `results/*_report.html`
files side by side to compare.

## Testing across the other two historical windows

v4 has already been tested on three windows: the default (2019-2024),
`strategy_v4_earlier.yaml` (2012-2018), and `strategy_v4_crisis.yaml`
(2006-2011) — each is just a copy of v4 with different `start_date`/
`end_date`. **v5 doesn't have those two variants yet** — only the
2019-2024 window exists for it
(`config/strategy_v5_n_sizing.yaml`). To do the full 3-window
comparison from `PROJECT_STATUS.md`, those two files need to be created
first (copy `strategy_v5_n_sizing.yaml`, change the dates to match the
corresponding v4 variant). Ask and I'll create them.

## Exporting a saved run

```powershell
python export_run.py --label "v4-2019-2024"
```

Writes a CSV of trades + a markdown summary from whatever was saved to
Supabase under that label. Independent of `--chart` — that flag builds
the HTML report immediately from the run in memory; this pulls a past
run back out of Supabase.

---

## What GitHub Actions is actually for (it's not backtesting)

`.github/workflows/daily-trading-check.yml` only runs
`live/run_live.py` — the daily **live/paper trading check** — not
`run_backtest.py`. There's no backtest workflow in this repo; backtesting
has always been a local-only thing.

That workflow's automatic daily schedule is intentionally disabled
(commented out in the YAML) until you're ready. Right now it only runs
if you manually trigger it from GitHub's Actions tab
(`workflow_dispatch`), which does require the code to be pushed to
GitHub first, since Actions runs against what's on GitHub, not your
local files. If/when you want backtests to run in CI too, that would
need a new workflow file — not built, ask if you want it.

**Bottom line**: to run a backtest, just run the Python command in a
terminal in this folder. Pushing to GitHub is unrelated.
