# Trading Strategy Backtester

A speculative, personal passion project — a systematic trading strategy I built, backtested, and now paper-trade on a real brokerage account (fake money, real market conditions), with the goal of eventually deciding, deliberately, whether it's earned the right to run with real money. **This is not investment advice and no backtest guarantees future results.** I own the logic, own the decisions, and I'm sharing the code because building it has been a genuinely interesting project — not because it's a proven money-maker.

**Where the project is right now**: after backtesting a crypto-focused strategy for most of this project's history, a deliberate reassessment showed its headline numbers were mostly a historic bull market, not durable edge — see [`MASTER_STRATEGY_GUIDE.md`](MASTER_STRATEGY_GUIDE.md) for the full story. The live strategy now trades a basket of 3x leveraged ETFs (SPXL/TQQQ/SOXL/FAS/TNA/TECL) instead, chosen after testing showed materially healthier trade quality on that recent, harder window. The old crypto strategy is fully preserved (`config/strategy_master_crypto_v36.yaml`), not deleted — just no longer the default.

**Start here**: [`MASTER_STRATEGY_GUIDE.md`](MASTER_STRATEGY_GUIDE.md) is the real documentation — plain-English, no background assumed, covers exactly how the strategy decides to buy/sell/size positions, every metric in a backtest report, and the honest open risks. This README is just setup instructions.

**An example report** (built from synthetic/fake data, not real results — just to show what the tool produces): [view it live](https://pyrpapa.github.io/trading-project/examples/example_backtest_report.html) (source: [`examples/example_backtest_report.html`](examples/example_backtest_report.html)).

## Project structure

```
config/strategy_master.yaml   <- the live strategy. Edit numbers, not code.
data/fetcher.py                <- pulls real historical prices (yfinance)
data/synthetic.py               <- generates fake data for offline testing
strategy/rules.py               <- turns indicators into BUY/SELL signals
backtest/engine.py               <- simulates the strategy day-by-day, tracks P&L
run_backtest.py                   <- CLI entry point for backtesting
live/run_live.py                  <- one daily check-and-trade cycle against Alpaca
live/close_position.py            <- manually close one position on demand
broker/alpaca_client.py           <- Alpaca API wrapper
storage/supabase_client.py        <- logs signals/trades/snapshots to Supabase
dashboard/                        <- React console reading live from Supabase
```

Also included: `parameter_sweep.py`, `rotation_backtest.py`, `blend_backtest.py`, `side_pot_sweep.py` — research tools built while exploring specific questions (which parameters matter, whether blending asset classes helps, how to protect gains once profitable). Not part of the live system, kept as reusable tooling.

## Running a backtest

```bash
pip install -r requirements.txt

python run_backtest.py --synthetic          # fake data, no internet needed, sanity-check only
python run_backtest.py                       # real historical data (needs internet)
python run_backtest.py --chart               # also write an HTML report to results/
```

First run with real data caches prices to `data/cache/*.csv` so later backtests are instant. Delete the cache to refresh. See `MASTER_STRATEGY_GUIDE.md` Section 13 for what every metric in the output actually means.

## Supabase setup

1. In your Supabase project, open the **SQL Editor** and run everything in `supabase/migrations/` in order.
2. Copy `.env.example` → `.env`, fill in your project's URL and **service role key** (Settings → API). Never commit `.env` or use the service key in frontend code.
3. `python run_backtest.py --save --label "my-first-run"` writes the full config, metrics, and every trade into Supabase.
4. For the dashboard's Backtest page to link to a run's HTML report: Storage → **New bucket** → name it `backtest-reports` → **Public bucket** (this is what `storage/supabase_client.py`'s `SupabaseStore.REPORTS_BUCKET` uploads `--chart` reports to; `api/run_backtest.py` returns each report's public URL directly in its response, so the dashboard never has to reconstruct it).

Tables use Row Level Security with no public write policies — reachable only via the service role key from backend scripts, or (for reads) an authenticated dashboard login.

## Alpaca paper trading setup

1. Sign up at [alpaca.markets](https://alpaca.markets) — a paper account (fake $100k) is created automatically.
2. Get paper API keys from the [paper dashboard](https://app.alpaca.markets/paper/dashboard/overview) → API Keys.
3. Add to `.env`: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER=true`.
4. Dry run first: `python live/run_live.py --dry-run`. Then for real (still paper money): `python live/run_live.py`.

**Safeguard**: `broker/alpaca_client.py` refuses to run if `ALPACA_PAPER=false` — deliberate, so going live with real money requires consciously removing that check yourself, not an accident.

### Running it daily

`.github/workflows/daily-trading-check.yml` runs `live/run_live.py` on weekday market-hours (since the live strategy is equities/ETFs — see that file's own header if you switch back to the crypto config). Add `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` as repo secrets (Settings → Secrets and variables → Actions) and it just runs — no machine of your own needs to stay on. Trigger it manually anytime from the Actions tab.

**The actual daily trigger is external, not GitHub's own `schedule:`.** GitHub's native cron for this workflow turned out to be unreliable in practice (see the workflow file's own comments) — hours-late or entirely missing triggers, with no error raised anywhere. The real schedule is an external cron-job.org job that calls this workflow's `workflow_dispatch` REST endpoint directly at a fixed time (10:15 AM America/New_York, DST-aware) every weekday, using a fine-grained GitHub PAT (Actions read/write only, scoped to this repo). That credential lives in the cron-job.org account, not in this repo. GitHub's own `schedule:` trigger is left in as a free backup, not the thing actually driving this day to day. `daily-trading-check-watchdog.yml` opens a GitHub issue if no run succeeds within 20 hours, covering a failure in either path.

`.github/workflows/close-position.yml` is a separate, manual-only workflow for closing one specific position on demand (defaults to a dry run — see its own comments).

## Dashboard

A React console (`dashboard/`) showing equity curve, open positions, a profit/milestone tracker, and recent signals, reading live from Supabase. Its Backtest page lets you configure and run a custom backtest against any config, automatically compared against a baseline (master by default, changeable) over the same window and starting cash — submitted to `api/run_backtest.py`, a Vercel Python function that runs the exact same `run_backtest_for_config()` the CLI and this project's other backtests use, synchronously (this project's runs consistently finish well under Vercel's function timeout, so no GitHub Actions dispatch/poll step is needed for this one).

```bash
cd dashboard && npm install
cp .env.example .env   # fill in Supabase URL + anon public key
npm run dev             # http://localhost:5173
```

Requires a Supabase Auth login (create one under Authentication → Users — no public signup). Deploy to Vercel/Netlify (both free for personal projects) if you want it accessible from your phone.

### Deploying to Vercel

This project's Vercel **Root Directory must be the repo root**, not `dashboard/` — `vercel.json` at the repo root tells Vercel to build the frontend from `dashboard/` (`npm --prefix dashboard install && npm --prefix dashboard run build`, output `dashboard/dist`) while also exposing `/api/*` (both the `.js` functions and `api/run_backtest.py`) at the repo root. The Python function needs this specifically so it can import `strategy/`, `backtest/`, `data/`, and `storage/` directly — the real modules every other backtest in this project already uses, not a reimplementation — which isn't reachable from a `dashboard/`-rooted deployment. If you're setting this project up fresh, just point Vercel at the repo as-is; if you have an existing deployment rooted at `dashboard/`, change Root Directory to blank/`.` under Project Settings → General.

Vercel environment variables needed (Project → Settings → Environment Variables):
- `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` — same public values as `dashboard/.env`.
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` — the service role key, used server-side only by `api/run_backtest.py` to save results and upload chart reports (same credentials `run_backtest.py --save` already uses everywhere else).
- `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` — used server-side by `api/quotes.js` (live prices for open positions).
- `GITHUB_DISPATCH_TOKEN` — a fine-grained GitHub PAT (Actions read/write, this repo only), used server-side by `api/sell.js` to trigger `close-position.yml`.

None of these are `VITE_`-prefixed except the two that are meant to be public — Vite only bundles `VITE_`-prefixed vars into client code, so the rest stay server-side.

## Important

This is a personal, speculative project, not a product and not financial advice. Every number in the config is a reasonable, backtested starting point, not a recommendation — markets change, and a strategy that worked in the past may not work going forward. Real trading costs (spread, slippage) aren't fully modeled in the backtest; see the guide's data-pipeline section for the honest gaps. Don't run this with money you're not prepared to lose.
