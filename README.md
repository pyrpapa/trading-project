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

Tables use Row Level Security with no public write policies — reachable only via the service role key from backend scripts, or (for reads) an authenticated dashboard login.

## Alpaca paper trading setup

1. Sign up at [alpaca.markets](https://alpaca.markets) — a paper account (fake $100k) is created automatically.
2. Get paper API keys from the [paper dashboard](https://app.alpaca.markets/paper/dashboard/overview) → API Keys.
3. Add to `.env`: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER=true`.
4. Dry run first: `python live/run_live.py --dry-run`. Then for real (still paper money): `python live/run_live.py`.

**Safeguard**: `broker/alpaca_client.py` refuses to run if `ALPACA_PAPER=false` — deliberate, so going live with real money requires consciously removing that check yourself, not an accident.

### Running it daily

`.github/workflows/daily-trading-check.yml` runs `live/run_live.py` automatically on a schedule (currently weekday market-hours, since the live strategy is equities/ETFs — see that file's own header if you switch back to the crypto config). Add `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` as repo secrets (Settings → Secrets and variables → Actions) and it just runs — no machine of your own needs to stay on. Trigger it manually anytime from the Actions tab.

`.github/workflows/close-position.yml` is a separate, manual-only workflow for closing one specific position on demand (defaults to a dry run — see its own comments).

## Dashboard

A React console (`dashboard/`) showing equity curve, open positions, a profit/milestone tracker, recent signals, and backtest comparisons — reading live from Supabase.

```bash
cd dashboard && npm install
cp .env.example .env   # fill in Supabase URL + anon public key
npm run dev             # http://localhost:5173
```

Requires a Supabase Auth login (create one under Authentication → Users — no public signup). Deploy to Vercel/Netlify (both free for personal projects) if you want it accessible from your phone.

## Important

This is a personal, speculative project, not a product and not financial advice. Every number in the config is a reasonable, backtested starting point, not a recommendation — markets change, and a strategy that worked in the past may not work going forward. Real trading costs (spread, slippage) aren't fully modeled in the backtest; see the guide's data-pipeline section for the honest gaps. Don't run this with money you're not prepared to lose.
