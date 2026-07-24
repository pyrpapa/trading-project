# Trading Strategy Backtester

A tool you own and can tweak: define buy/sell rules in a config file,
backtest them against historical data, and see exactly how they would
have performed — before any money (real or paper) is involved.

## Project structure

```
config/strategy.yaml   <- YOUR strategy lives here. Edit numbers, not code.
data/fetcher.py         <- pulls real historical prices (yfinance)
data/synthetic.py       <- generates fake data for offline testing
strategy/rules.py       <- turns indicators into BUY/SELL signals
backtest/engine.py      <- simulates the strategy day-by-day, tracks P&L
run_backtest.py          <- entry point: ties it all together
```

## How the rule currently works (edit in config/strategy.yaml)

- **Buy**: price closes above its 20-day moving average, AND volume is
  above its 20-day average (confirms real interest, not noise)
- **Sell**: price closes back below the 20-day MA, OR drops 8% from your
  entry price (stop-loss — this fires regardless of the MA, it's a safety net)
- **Position size**: max 5% of portfolio per position, max 60% invested
  at once (40% always stays in cash as a buffer)

Every one of those numbers is a lever. Change one, rerun the backtest,
compare the metrics. That's the whole workflow.

## Running it

This sandbox can't reach Yahoo Finance (no internet access to finance
APIs), so I validated the code with **synthetic data** — a random walk
with realistic drift/volatility, not real market history. The logic
is fully tested and working; you just need to run it on your own
machine to get real results.

On your machine:

```bash
pip install -r requirements.txt

# Test with synthetic data (no internet needed, sanity-check only)
python run_backtest.py --synthetic

# Run with real historical data (needs internet)
python run_backtest.py
```

The first run with real data will cache prices to `data/cache/*.csv`
so subsequent backtests are instant. Delete the cache or run
`python data/fetcher.py` to refresh.

## What the metrics mean

- **total_return_pct** — overall portfolio return over the backtest period
- **annualized_return_pct** — return normalized to a yearly rate
- **max_drawdown_pct** — the worst peak-to-trough decline. This is your
  real risk number — bigger picture than any single trade
- **win_rate_pct** — % of trades that were profitable (a strategy can
  have a low win rate and still be profitable if wins are bigger than losses)
- **longest_losing_streak** — how many losses in a row, worst case. Useful
  for knowing what it'll *feel* like to run this for real

## Supabase setup

1. In your Supabase project dashboard, open the **SQL Editor** and run
   the contents of `supabase/migrations/001_initial_schema.sql`. This
   creates four tables: `signals`, `trades`, `backtest_runs`, `config_history`.
2. Copy `.env.example` to `.env` and fill in your project's URL and
   **service role key** (Settings → API in the Supabase dashboard).
   Never commit `.env` or use the service key in frontend/browser code.
3. Install the new dependency: `pip install -r requirements.txt`
4. Run a backtest and save it:
   ```bash
   python run_backtest.py --save --label "ma20-stop8-v1"
   ```
   This writes the full config, metrics, and every trade into Supabase.
   Change a parameter in `strategy.yaml`, run again with a new `--label`,
   and now you have a real history to compare instead of memory.

Tables use Row Level Security with no public policies — meaning they're
only reachable via the service role key from your backend scripts. When
we build the dashboard, if it needs to read directly from the browser,
we'll add a scoped read-only policy using the anon key at that point
rather than exposing the service key.

## Alpaca paper trading setup

1. Sign up at [alpaca.markets](https://alpaca.markets) — a paper trading
   account (fake $100k) is created automatically, no application needed.
2. Get your paper API keys from the
   [paper dashboard](https://app.alpaca.markets/paper/dashboard/overview)
   → API Keys.
3. Add them to `.env`:
   ```
   ALPACA_API_KEY=...
   ALPACA_SECRET_KEY=...
   ALPACA_PAPER=true
   ```
4. Install dependencies: `pip install -r requirements.txt`
5. Do a dry run first — shows what it *would* do without placing orders:
   ```bash
   python live/run_live.py --dry-run
   ```
6. Once that looks right, run it for real (still paper money, no risk):
   ```bash
   python live/run_live.py
   ```

**Important safeguard**: `broker/alpaca_client.py` refuses to run if
`ALPACA_PAPER=false` is set. This is deliberate — it forces you to
consciously remove that check yourself when you're actually ready to
risk real money, rather than it happening by accident (a typo'd env
var, a copy-pasted config, etc).

### Running it daily (scheduling)

`run_live.py` does one check-and-trade cycle — it needs to run on a
schedule to matter. This project ships with a **GitHub Actions**
workflow (`.github/workflows/daily-trading-check.yml`) that handles
this for free, with no machine of yours needing to stay on:

1. Push this project to a GitHub repo (private is fine, free tier works)
2. In the repo: **Settings → Secrets and variables → Actions**, add:
   - `ALPACA_API_KEY`
   - `ALPACA_SECRET_KEY`
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY`
3. That's it — it runs automatically at 4:30pm ET on weekdays (after
   market close), and you can also trigger it manually anytime from the
   repo's **Actions** tab (useful for testing).
4. If a run fails, GitHub emails you and the log is saved as a
   downloadable artifact on that run.

Other options if you'd rather not use GitHub Actions:
- **Cron (if you leave a machine on)**:
  ```
  0 20 * * 1-5 cd /path/to/trading-project && /usr/bin/python3 live/run_live.py >> live.log 2>&1
  ```
- **Render/Railway cron jobs**: same idea as GitHub Actions, hosted elsewhere.

What it does each run:
- Fetches recent price data for your watchlist
- Checks open Alpaca positions against your exit rules (stop-loss,
  take-profit, trend-exit) — closes any that trigger
- Checks for new BUY signals on tickers you don't currently hold, sizes
  the order per your risk config, and submits it
- Logs every action to Supabase's `signals` table if credentials are set

## Dashboard

A web console (in `dashboard/`) showing equity curve, open positions,
recent signals, and backtest run comparisons — reading live from
Supabase. Built with React + Vite, styled as a monitoring console
(dark, amber accent, monospace numbers) rather than a generic finance
template.

### Setup

1. **Create your login** — Supabase Dashboard → Authentication → Users
   → Add User (email + password). This console has no public signup;
   it's just for you.
2. `cd dashboard && npm install`
3. Copy `dashboard/.env.example` → `dashboard/.env`, fill in your
   Supabase URL and **anon public key** (Settings → API — this is the
   public key, safe for frontend code, different from the service key
   the Python backend uses).
4. `npm run dev` — opens locally at `http://localhost:5173`, log in
   with the credentials you created in step 1.

### Deploying so you can check it from your phone

```bash
npm run build
```
Push the `dashboard/` folder to a GitHub repo and connect it to
[Vercel](https://vercel.com) or [Netlify](https://netlify.com) (both
free for personal projects) — set the root directory to `dashboard`
and add the same two env vars in their dashboard's environment
variables settings. You'll get a URL you can open from any device, or
add to your phone's home screen for an app-like feel (PWA-style, no
app store needed).

## Next steps (in order)

1. ~~Add storage (Supabase)~~ ✅ done
2. **Tune the rule against real data.** Try different `ma_period` values,
   toggle `volume_confirmation`, adjust `stop_loss_pct`. Save each run
   with `--save --label` and compare metrics in Supabase or the dashboard.
3. ~~Paper trading via Alpaca~~ ✅ done — run `--dry-run` first, then
   let the GitHub Actions workflow run it daily and watch it for a few
   weeks. Compare what actually happens to what the backtest predicted.
4. ~~Dashboard~~ ✅ done — check it periodically rather than obsessively;
   daily or every-few-days is plenty at this stage.
5. **Live trading** — only after paper results look sane over a
   meaningful stretch of time, and only with money you're fully
   prepared to see drop 20-30% temporarily. This is not a
   "guaranteed profit" system — see the disclaimer below.

## Important

This is a tool for *you* to define and test rules — it is not investment
advice, and no backtest guarantees future results (markets change, and
a strategy that worked 2019-2024 may not work going forward). Every
number in `config/strategy.yaml` was chosen as a reasonable starting
point, not a recommendation. You own this logic — that's the point.
