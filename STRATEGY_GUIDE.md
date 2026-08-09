# Trading System — Strategy Guide

This is your reference for understanding and editing how the strategy
works. Keep it next to `config/strategy.yaml` — whenever you change a
number in that file, this doc explains what it actually does.

---

## 1. Where everything lives

| What | File |
|---|---|
| **The strategy itself** (all tunable numbers) | `config/strategy.yaml` |
| Signal logic (buy/sell rules, reads the config) | `strategy/rules.py` |
| Backtest simulation engine | `backtest/engine.py` |
| Daily live/paper trading runner | `live/run_live.py` |
| Broker connection (Alpaca) | `broker/alpaca_client.py` |
| Results storage | Supabase (`backtest_runs`, `trades`, `signals`, `account_snapshots`) |
| Results viewer | `dashboard/` (currently **read-only** — see Section 6) |

**You should only ever need to edit a `config/*.yaml` file.** The
`.py` files contain the logic that reads that config — you shouldn't
need to touch them to change how the strategy behaves.

Both `run_backtest.py` and `live/run_live.py` default to
`config/strategy.yaml`, but both accept a different file so you can
switch strategies without renaming anything:

```powershell
python run_backtest.py --config config/strategy_v4.yaml
python live/run_live.py --dry-run --config config/strategy_v4.yaml
```

`live/run_live.py` also honors a `STRATEGY_CONFIG` environment
variable (same effect as `--config`, useful for the GitHub Actions
workflow — see Section 5). `--config` on the command line wins if
both are set.

---

## 2. What runs, and when

- **Backtest** (`python run_backtest.py`) — simulates the strategy
  against *historical* prices. No real trades, no risk. Run this
  anytime you want to test a config change.
- **Live/paper runner** (`python live/run_live.py`) — runs the
  strategy for *real*, once per call, against current Alpaca account
  and live market data. On a paper account this uses fake money; on a
  live account it would use real money. This is what the GitHub
  Actions workflow runs automatically once a day.

Both use the **exact same signal logic** from `strategy/rules.py` — a
backtest and a live run with the same config will make the same
decisions given the same price data. That's intentional: it's what
makes the backtest a meaningful preview of live behavior.

---

## 3. The full config, explained

```yaml
watchlist:
  - SPY
  - AAPL
  - MSFT
```
The list of tickers the strategy watches. It will only ever buy
something on this list. Add or remove tickers by editing this list.

```yaml
entry:
  ma_period: 20
  volume_confirmation: true
  volume_ma_period: 20
```
**The buy trigger.** Buys a ticker on the day its price closes above
its `ma_period`-day moving average, *if* `volume_confirmation` is on
and today's volume is above its own `volume_ma_period`-day average.

- Bigger `ma_period` (e.g. 50) → slower to react, fewer trades, less
  whipsaw from short-term noise.
- Smaller `ma_period` (e.g. 10) → faster to react, more trades, more
  false signals.
- `volume_confirmation: false` → removes the volume filter entirely.
  More trades, less certainty each one reflects real buying interest.

```yaml
exit:
  ma_exit: true
  stop_loss_pct: 8.0
  take_profit_pct: null
```
**The sell trigger.** A position closes when *any* of these fire,
whichever happens first:
- `ma_exit: true` → price closes back below the moving average
  (the trend that justified the buy has reversed)
- `stop_loss_pct: 8.0` → price has dropped 8% from your entry price,
  regardless of the moving average. This is your safety net — it
  fires even if the MA logic hasn't caught up yet.
- `take_profit_pct` → optional. If set (e.g. `15.0`), also sells once
  a position is up 15%, locking in the gain instead of riding it
  further. Currently `null` (off) — the strategy currently lets
  winners run until the trend-exit or stop-loss triggers instead.

```yaml
risk:
  max_position_pct: 5.0
  max_invested_pct: 60.0
```
**Position sizing — this is the part that controls how much money
touches any single trade.** See Section 4 for the full walkthrough.

```yaml
backtest:
  starting_cash: 10000
  start_date: "2019-01-01"
  end_date: "2024-12-31"
  commission_pct: 0.0
```
Only affects backtests, not live trading (which uses your real
Alpaca account balance and today's date automatically). Change
`start_date`/`end_date` to test different historical periods;
`starting_cash` to test with a different hypothetical account size.

---

## 4. How position size is actually calculated

Every time the strategy decides to buy, it computes an **allocation**
using this exact logic (from `backtest/engine.py`, mirrored in
`live/run_live.py`):

```
max_position_value = portfolio_value * max_position_pct     (e.g. 5% cap per trade)
room_left           = (portfolio_value * max_invested_pct) - invested_value
allocation           = min(max_position_value, room_left, cash)
```

**Three numbers compete, and the smallest one wins:**

1. **The per-trade cap** — `max_position_pct` × your total account value
2. **The remaining room under your total exposure cap** — `max_invested_pct`
   × total account value, minus whatever's already invested
3. **Actual cash you have free** — can't spend money you don't have

### Worked example: $5,000 account, default config

- `max_position_pct: 5%` → no single trade can exceed **$250**
- `max_invested_pct: 60%` → total invested can never exceed **$3,000**
- Watchlist has 3 tickers (SPY, AAPL, MSFT)

**The catch:** 3 tickers × $250 max each = **$750 maximum possible
exposure** — far below the $3,000 the 60% cap would allow. With this
exact config, **at least 85% of a $5,000 account sits idle as cash,
permanently**, because you'd run out of tickers to buy before you'd
run out of allowed exposure. That's not a bug — it's what these
numbers produce together, and worth deciding on purpose rather than
by accident.

**To actually use more of the account**, you'd change one or both of:
- Raise `max_position_pct` (e.g. to 15-20%) so each position can be bigger
- Add more tickers to the watchlist so there's more to invest in

---

## 5. A day in the life of the live runner

The GitHub Actions workflow (`workflow_dispatch`) has a
`strategy_config` input — leave it as `config/strategy.yaml` or point
it at any other file in `config/` (e.g. `config/strategy_v4.yaml`) for
that run, no code or secrets change needed. It defaults to
`config/strategy.yaml` if left blank, including on the (currently
disabled) scheduled runs.

Each time `live/run_live.py` runs (once daily via GitHub Actions):

1. **Check open positions for exits.** For each ticker currently held,
   compare today's price to your entry price. If down `stop_loss_pct`%
   or more → sell. Else if price closed back below the MA → sell.
   Otherwise, hold.
2. **Check for new buys.** For each watchlist ticker *not* currently
   held, check if today's data triggers the entry rule. If yes, compute
   the allocation (Section 4) and buy.
3. **Log everything to Supabase** — signals fired, trades opened/closed,
   and a snapshot of account equity (this is what feeds the dashboard's
   equity curve).

Most days, nothing happens — that's normal, not a sign anything's
broken. The strategy only acts when its specific conditions are met.

---

## 6. Editing the strategy today vs. the dashboard

**Today:** edit `config/strategy.yaml` directly in a text editor
(Notepad++), save, then re-run a backtest to see the effect:
```powershell
python run_backtest.py --save --label "v2-description-of-change"
```
Compare the new run's metrics against previous ones (visible in the
dashboard's "Backtest runs" table, or directly in Supabase).

**The dashboard is currently read-only** — it displays results but
doesn't let you edit the strategy. If you want to control the config
from the dashboard itself instead of editing a file on your computer,
that requires a real feature addition: a "Strategy" tab where the
config lives in Supabase (instead of only the local YAML file), and
both the dashboard and your Python scripts read from that shared
source. That's a natural next build whenever you're ready for it.

---

## 7. Before this touches real money — a checklist

- [ ] Run paper trading for a meaningful stretch (weeks, not days) and
      compare actual results to what the backtest predicted
- [ ] Decide `max_position_pct` / `max_invested_pct` deliberately for
      your real account size, not just left at the defaults
      (Section 4 — check the math actually uses the % of your account
      you intend it to)
- [ ] Consider whether you want a hard dollar ceiling in addition to
      the percentage caps (e.g. "never more than $X per trade,
      period") — not built yet, ask if you want this added
- [ ] Re-read `broker/alpaca_client.py` — it currently has a hard
      safeguard that refuses to run against a live (non-paper) account.
      That's intentional friction; you'll need to consciously remove
      it when you're ready, not have it happen by accident
- [ ] Know your own answer to: what's the maximum amount you're fully
      prepared to see this lose, and are you still comfortable if it does?

---

## 8. Quick glossary

- **Signal** — a computed BUY or SELL trigger for a ticker on a given day
- **Position** — a currently-held (open) trade
- **Entry / exit** — opening / closing a position
- **Drawdown** — a decline from a peak account value; *max drawdown*
  is the worst such decline in a given period
- **Trend-exit** — sale triggered by price crossing back below the MA
  (as opposed to a stop-loss, which is triggered by % loss regardless
  of the MA)
- **Backtest** — simulation against historical data, no real money
- **Paper trading** — real-time simulation against live market data,
  using a broker's fake-money account
- **Live trading** — the real thing, real money
