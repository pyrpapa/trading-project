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

**You should only ever need to edit `config/strategy.yaml`.** The
`.py` files contain the logic that reads that config — you shouldn't
need to touch them to change how the strategy behaves.

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

---

## 9. Trade journal — the "why" behind every trade

Every trade (backtest, paper, or live) now carries a plain-English
reason, in the style of the trade diary examples in *Way of the
Turtle*:

> Entered long AAPL at $427.15 because price closed above its 20-day
> moving average, with volume above its 20-day average (volume
> confirmation).
>
> Exited AAPL at $393.02 (-8.02%, down) because price dropped 8.0%
> from entry, triggering the stop-loss.

This isn't hardcoded — `strategy/rules.py` builds the "why" text
directly from whatever's in `config/strategy.yaml`, so it stays
accurate no matter how the entry/exit rule changes (MA crossover
today, a Donchian breakout later, etc.). `strategy/journal.py` just
formats that reason into the full sentence.

**Where it lives:**
- Backtest trades: each entry in `result["trades"]` has `entry_reason`,
  `entry_log`, `exit_reason_detail`, and `exit_log` fields, printed in
  the console output and saved to Supabase's `trades` table.
- Live/paper trades: printed to the console each run and saved to the
  same `trades` table via `entry_reason`/`entry_log` on open and
  `exit_reason_detail`/`exit_log` on close.
- CSV exports (`export_run.py`) include `entry_log` and `exit_log` columns.

**One-time setup:** run `supabase/migrations/002_trade_journal.sql` in
the Supabase SQL Editor before your next backtest save or live run —
it adds the four new columns to the existing `trades` table. Safe to
run anytime; it won't touch existing rows beyond adding empty columns
to them.

---

## 10. N/ATR-based sizing, R-multiples, and the chart report

Three related additions, all "play around and build intuition" tools
for working through *Way of the Turtle* concepts without touching v1-v4:

### Position sizing modes

`risk.sizing_method` in a config controls how positions get sized:

- `"pct"` (default, v1-v4 behavior) — flat `max_position_pct` of the
  account per trade, stop-loss at a fixed `stop_loss_pct`.
- `"atr_unit"` (Turtle-style) — position size is set so that a
  `stop_atr_multiple * N` move against you (N = ATR) costs exactly
  `risk_pct_per_unit` of account equity. A volatile stock automatically
  gets fewer shares than a calm one. See `config/strategy_v5_n_sizing.yaml`
  for a working example, side by side with `config/strategy_v4.yaml`
  (same watchlist/entry rule — sizing is the only thing that changes).
  `max_position_pct`/`max_invested_pct` still apply as a hard ceiling
  on top, in either mode.

This is implemented once in `backtest/engine.py` and mirrored in
`live/run_live.py` so backtest and live decisions match — though for
live trading, an N-based stop has to be looked up from the Supabase
trade record saved at entry time (there's no way to recompute "N as of
entry day" later), so if that record isn't there the stop check is
skipped with a printed warning rather than guessing.

### R-multiples

Every trade's P&L is now also expressed as a multiple of its own
initial planned risk — the Turtles' own yardstick ("+2.3R", "-1.0R").
Works the same way regardless of sizing mode, since both get reduced
to a per-trade dollar risk figure. Portfolio-level stats
(`avg_r_multiple`, `system_quality_number` — a Van Tharp-style measure
of how *consistent* the edge is, not just how big) are in every
backtest's `metrics` dict, next to the existing win rate / drawdown
numbers.

### Chart report

`python run_backtest.py --chart` writes a self-contained HTML report to
`results/<label>_report.html` — stat tiles, equity curve + drawdown,
a monthly-returns bar chart (winning/losing months, styled after the
book's own performance charts), an R-multiple distribution, and a
price chart per ticker with buy/sell markers. Nothing is saved to
Supabase for this — it's built straight from the in-memory backtest
result, so it's fast to regenerate every time you tweak a config:

```powershell
python run_backtest.py --config config/strategy_v4.yaml --synthetic --chart --label "v4"
python run_backtest.py --config config/strategy_v5_n_sizing.yaml --synthetic --chart --label "v5-n-sizing"
```

Open both reports side by side to compare.

---

## 11. Correlation-based circuit breaker

A portfolio-level risk check, layered on top of everything in Section
10 rather than replacing it. N-based sizing controls how big any one
position is; the circuit breaker controls whether a NEW position is
allowed to open at all, given how correlated it already is with what's
currently held.

**Why it exists**: with a watchlist like SPY/AAPL/MSFT, holding max
positions in all three isn't really three independent bets — AAPL and
MSFT are two of SPY's largest holdings, so all three tend to move
together. Without this check, nothing stops the strategy from sizing
that concentrated, correlated bet as if it were properly diversified.

**Config** (`risk.correlation_breaker` — see `config/strategy_v6_circuit_breaker.yaml`):

```yaml
risk:
  correlation_breaker:
    enabled: true
    lookback_period: 60           # trading days of returns used to compute correlation
    correlation_threshold: 0.7    # Pearson correlation at/above this counts as "correlated"
    max_correlated_positions: 2   # 2+ already-open correlated positions trips the breaker
```

**How it works** (`strategy/correlation.py`): before opening a new
position, the engine computes the trailing Pearson correlation (over
`lookback_period` days of daily returns) between the candidate ticker
and every position currently open. If `correlation_threshold` or
higher correlation is found with `max_correlated_positions` or more of
them, the new entry is skipped entirely — logged the same way as
entries/exits (see `strategy/journal.py`'s `format_blocked`). Pairs
without enough shared price history to compute a reliable number don't
count against the candidate — it fails open, the same pattern N-based
sizing already uses when ATR isn't available yet.

This is computed from actual price history, not a hand-assigned list
of "correlated groups" (which is what the Turtles themselves used,
with hard unit caps per group). The tradeoff: hand-assigned groups are
simpler to reason about, but have to be updated by hand whenever the
watchlist changes; computed correlation adapts automatically — which
matters once the (still unbuilt) portfolio selection algorithm starts
choosing tickers dynamically instead of today's static list.

**Visibility**: `metrics["correlation_blocked_count"]` and
`result["blocked_signals"]` (each with a ticker, date, and plain-English
reason) are available on every backtest result; the chart report shows
a "Blocked by breaker" stat tile; `run_backtest.py`'s console output
prints up to 10 blocked signals with their reasons.

Implemented once in `backtest/engine.py`, mirrored in `live/run_live.py`
(which reuses price history already fetched for open positions during
the exit check, rather than re-fetching).

**Real-data result (2019-2024)**: net negative. Blocking 59 of ~211
potential signals cost 1.21 points of annualized return AND made max
drawdown 0.63 points DEEPER (-8.18% vs v5's -7.55%) — the opposite of
the intended effect. Best explanation: `max_correlated_positions: 2`
still allows 2 correlated positions open together (caps concentration,
doesn't remove it), while the block itself is signal-blind — it can't
tell whether a blocked trade would have been a winner or a loser, so
it costs whatever it blocks regardless. See PROJECT_STATUS.md for the
full table and discussion, and Section 12 below for the approach tried
next as a result.

---

## 12. Portfolio selection

The third pillar of "system edge" alongside entries and exits (Way of
the Turtle's own framing: portfolio selection + entry signals + exit
signals). Chooses WHICH markets from a larger candidate pool are
actually tradable right now, instead of trading a fixed, hand-picked
watchlist forever — and a direct response to Section 11's result:
instead of policing an already-correlated 3-ticker list after the
fact, this chooses a genuinely less-correlated set of markets up
front.

**Config** (`portfolio_selection` — see `config/strategy_v7_portfolio_selection.yaml`):

```yaml
portfolio_selection:
  enabled: true
  candidate_universe: [SPY, AAPL, MSFT, GOOGL, AMZN, JPM, JNJ, XOM, CAT, PG, TLT, GLD, XLU, VNQ]
  target_size: 3                    # how many tickers to actually trade at once
  min_avg_dollar_volume: 20000000   # liquidity floor, in trailing average $/day
  lookback_period: 90               # trading days used for both the liquidity and correlation checks
  rebalance_frequency_months: 3     # how often the active set is re-evaluated
```

**How it works** (`strategy/portfolio_selection.py`), recomputed on a
rebalance schedule using only trailing data as of the rebalance date —
no lookahead:

1. **Liquidity filter** — drop any candidate whose trailing average
   *dollar* volume (price × volume, not raw share count — comparable
   across tickers at very different price levels) is below
   `min_avg_dollar_volume`.
2. **Greedy diversification** — seed with the most liquid surviving
   candidate, then repeatedly add whichever remaining candidate has
   the LOWEST average correlation (via the same `trailing_correlation`
   function the circuit breaker uses) to everything already picked,
   until `target_size` is reached.

Positions already open in a ticker that drops out at a rebalance are
**not force-closed** — they're left to exit normally via their own
stop/trend-exit/take-profit. Only NEW entries are restricted to
whatever's currently selected, the same "don't disrupt what's already
running" pattern used elsewhere in this codebase.

**Backtest vs. live differ slightly**: the backtester holds a
selection fixed between quarterly rebalance checkpoints, replaying
history day by day. The live runner has no cross-run state to track a
rebalance schedule against, so it simply recomputes fresh from today's
trailing data every run — simplest correct thing, though it means live
selections could in principle change more often than the backtest's
quarterly cadence implies. Worth revisiting if that turns out to
matter once paper trading is active.

**Known startup quirk**: the very first rebalance (day 1 of a
backtest) has no trailing history yet, so the active set starts EMPTY
and stays that way until `lookback_period` days of data accumulate at
a later rebalance checkpoint — expect close to zero trades for
roughly the first couple of quarters of a fresh config. Same kind of
warm-up N-based sizing already has with its ATR period, just longer
here (90 trading days by default).

**Visibility**: `metrics["portfolio_rebalances"]` and
`metrics["avg_active_portfolio_size"]` are on every backtest result;
`result["rebalance_log"]` has the full history (date, selected,
added, dropped); the chart report shows "Rebalances" / "Avg portfolio
size" stat tiles plus a full rebalance history text block;
`run_backtest.py`'s console output prints every rebalance.

Implemented once in `backtest/engine.py`, mirrored in
`live/run_live.py` (which required a small refactor: price history
fetching was consolidated into one memoized `get_price_history()`
helper shared by the exit check, the correlation breaker, and
portfolio selection — needed since portfolio selection requires price
history for the FULL candidate universe up front, not just currently
held tickers).

---

## 13. Donchian breakout entries

An alternative ENTRY rule to the MA-crossover used since v1 — a direct
response to Section 12's result. Portfolio selection (v7) correctly
identified TLT/GLD/JNJ/XOM/CAT/JPM as genuinely less-correlated
diversifiers than AAPL/MSFT/GOOGL/AMZN, but real-data results were
still much worse than v5 on return, win rate, and SQN. The working
theory: MA-crossover doesn't produce clean signals on non-trending,
lower-volatility assets like bonds/gold/defensive sectors — the same
problem v3's earlier diversification attempt hit. Donchian breakouts
are what the Turtles actually used, specifically because the same
rule needed to work across very different market types (currencies,
bonds, metals, equity indices) — a genuine new price extreme is a
cleaner, more portable definition of "something changed" than a price
crossing its own smoothed average.

**Config** (`entry.type` — see `config/strategy_v8_donchian_breakout.yaml`):

```yaml
entry:
  type: donchian_breakout   # "ma_crossover" (default, v1-v7 behavior) or "donchian_breakout"
  breakout_period: 20       # Turtle System 1 (20-day) or System 2 (55-day)
  volume_confirmation: false  # dropped for breakout entries, per the original Turtle system
  ma_period: 20              # still read by the (unchanged) MA-based trend exit
  volume_ma_period: 20
```

**How it works** (`strategy/rules.py`): `add_indicators()` now
unconditionally computes a `donchian_high` column — the highest `High`
over the `breakout_period` days *before* today (`shift(1)` excludes
today itself, so a day's own high can never count toward its own
breakout threshold — no lookahead). `generate_signals()` branches on
`entry.type`: `"donchian_breakout"` fires a BUY whenever today's close
is above that rolling threshold; `"ma_crossover"` (the default, so
every v1-v7 config keeps working unchanged with no `entry.type` key
at all) keeps the original "just crossed above its own moving
average" logic. Both `run_backtest.py` and `live/run_live.py` already
call the same shared `rules.generate_signals()`, so this one change
in `strategy/rules.py` is enough — no engine or live-runner changes
were needed for entries. (`live/run_live.py`'s history lookback
window was widened to also account for `breakout_period`, so a config
using a longer breakout — e.g. System 2's 55-day — still pulls enough
history live.)

**Exit rule is deliberately unchanged**: `config/strategy_v8_donchian_breakout.yaml`
keeps v5's exact MA-based trend exit + 2N/ATR stop, same watchlist,
same window — isolating the entry rule as the one new variable, same
"don't conflate changes" discipline used for v6 and v7. The Turtles'
own system also swaps the EXIT to a Donchian low (10-day for System
1, 20-day for System 2) — deliberately not done here yet, so a future
result can tell entries and exits apart.

**Verified in the sandbox** before shipping: constructed a synthetic
price series with an obvious range-then-breakout shape and confirmed
`donchian_high` on a given day exactly equals the manually-computed
rolling max of the *prior* `breakout_period` days (not including that
day) — the no-lookahead property holds. Ran a full
`engine.run_backtest()` against the real `strategy_v8_donchian_breakout.yaml`
config on synthetic data end-to-end with no errors, confirmed
`report.py` generates cleanly with the new "entry: donchian_breakout
(20-day)" subtitle line, and re-ran a legacy config
(`strategy_v5_n_sizing.yaml`, which has no `entry.type` key at all) to
confirm the default fallback to `ma_crossover` still works exactly as
before — a pure backward-compatibility regression check.

**Visibility**: the chart report's subtitle now always shows the
active entry rule (`entry: ma_crossover (20-day)` or `entry:
donchian_breakout (20-day)`), so it's obvious at a glance which rule
produced a given report.

**Real-data result (2019-2024, SPY/AAPL/MSFT)**: a genuine
quality-vs-quantity tradeoff against v5 — win rate, avg R-multiple,
and SQN all improved (44.08% → 52.53%, 0.53R → 0.67R, 3.92 → 3.99),
but 35% fewer trades (99 vs. 152) meant less time participating in a
strong bull market, so total/annualized return came in lower (7.75%
vs 9.46%). Max drawdown was essentially unchanged. See
PROJECT_STATUS.md item #15 for the full table and discussion — this
result is what motivated v9 below.

**v9 — combined with portfolio selection**: `config/strategy_v9_donchian_portfolio.yaml`
pairs this entry rule with Section 12's 14-ticker candidate universe
and rebalance logic, unchanged from `strategy_v7_portfolio_selection.yaml`
except for the `entry` block (donchian_breakout instead of
ma_crossover). The two features are fully independent in the code —
`entry.type` only affects `strategy/rules.py`'s buy-signal branch,
`portfolio_selection` only affects which tickers are eligible for new
entries in `backtest/engine.py` — so combining them required no new
code, only a new config. **Verified in the sandbox** before shipping:
ran a full `engine.run_backtest()` on a synthetic 14-ticker universe
and confirmed every trade's entry ticker was actually in the active
portfolio-selection set as of its entry date (the two features gate
correctly together, not bypassing each other), and confirmed
`report.py` renders both the entry-rule subtitle and the rebalance
history section for a combined-config result. **Not yet run on real
data** — see PROJECT_STATUS.md for the next step. The hypothesis: v8
showed breakout entries meaningfully improve signal quality even on
already-trending tickers (SPY/AAPL/MSFT); if that effect is at least
as strong on the non-trending bonds/gold/defensive-sector names
portfolio selection prefers, v9 could recover v7's collapsed win rate
(31.58%) and R-multiple (0.19R) without losing its best-yet max
drawdown (-4.72%).

## 14. Pyramiding (Turtle-style position building)

Every config through v9 sizes a position ONCE, at entry, purely off
RISK (N/ATR — see Section 4). There was no lever for REWARD or
conviction: a trade that immediately proves itself right gets exactly
the same size as one that barely scrapes by. Pyramiding is the
Turtles' own answer to that gap — instead of placing one full-size bet
up front, add more size to a position only as price confirms the
trade is working, capped at a fixed number of "units."

**Config** (`risk.pyramiding` — see `config/strategy_v10_pyramiding.yaml`):

```yaml
risk:
  sizing_method: atr_unit   # pyramiding requires atr_unit sizing (see below)
  pyramiding:
    enabled: true
    unit_interval_n: 0.5    # add a unit every 0.5N further in your favor (Turtle default)
    max_units: 4             # cap the stack at 4 units total (Turtle default)
```

Requires `sizing_method: atr_unit` — the add-trigger and the sizing of
each new unit are both N-based, so under flat-% sizing (`"pct"`)
`risk.pyramiding.enabled: true` is silently a no-op (same
"backward-compatible by default" pattern used for every other
`risk.*` feature block; nothing breaks, pyramiding just never fires).

**How it works** (`backtest/engine.py`): `open_positions` changed from
`ticker -> Position` to `ticker -> list[Position]` — a "stack" of one
or more units. Every day, for each open stack under `max_units`, the
engine checks a PURE PRICE THRESHOLD (not a fresh entry signal, and
independent of the day's BUY/SELL signal): has price moved
`unit_interval_n * N` further in the position's favor since the LAST
unit's own entry price? `N` is re-measured fresh each time (current
ATR, not the ATR from the original entry), so a new unit is sized the
same way a fresh entry would be — `risk_pct_per_unit` of account
equity, re-priced to current volatility. `max_position_pct` /
`max_invested_pct` still apply as a ceiling on the whole stack's
combined value, same as they do for a single-unit position.

Every time a unit is added, the WHOLE stack's stop-loss is trailed up
to the new unit's stop level — `max(old_stop, new_unit_stop)`, so it
can only ever move up, never down. The entire stack always shares one
stop and exits together: on a stop-loss hit, a take-profit (checked
against the stack's weighted-average entry price), or the same
MA-based trend-exit signal used everywhere else. There's no partial
exit — a 4-unit stack closes as 4 trades on the same day at the same
price.

**Each unit is still its own trade record** — its own entry
date/price/shares/initial-risk, closed as a separate row in
`closed_trades` with its own `r_multiple`. This is deliberate, not
incidental: Van Tharp's own convention (used throughout this
project's R-multiple/SQN math) is that R is measured per discrete
unit of risk taken, not blended across a whole ticker position. A
trade record now also carries `unit_number` (1 = the original entry,
2+ = pyramid adds) and `units_in_stack` (how many units were in the
stack when it closed), so a report or later analysis can tell a
1-unit trade from unit 3 of a 4-unit stack.

**Backtest-only for now — a known, deliberate limitation.**
`live/run_live.py` was NOT modified to support pyramiding in this
pass. Paper/live trading isn't active yet, and reconstructing per-unit
state (each unit's own entry price and stop) from a live broker
position — which only reports one blended average entry price — is a
meaningfully harder problem than anything else built so far. This
mirrors how portfolio selection's live-mode simplification was
handled in Section 12: documented as a known gap, not silently
skipped. If/when paper trading is activated, `live/run_live.py` will
need its own design pass for pyramiding before any `config/strategy.yaml`
that enables it should be used live.

**Verified in the sandbox** before shipping, since real backtests
can't run here (no internet/PowerShell access):
- **Backward-compatibility regression**: ran `strategy_v5_n_sizing.yaml`
  (no `risk.pyramiding` key at all) through the refactored engine —
  every trade came back with `units_in_stack == 1` and
  `unit_number == 1`, `pyramid_adds` metric was `0`, and the result
  was structurally identical to the pre-refactor single-Position code
  path (the whole pyramid-add block is skipped entirely when
  `pyramiding.enabled` is absent or false).
- **Forced-trending scenario**: built a synthetic price series
  engineered to trend strongly enough, for long enough, to cross
  several `0.5N`/`0.3N` thresholds — confirmed units get added at the
  correct price thresholds, each new unit is sized off *current* N
  (share count shrinks slightly as volatility rises, same behavior as
  a fresh entry), the stack correctly stops adding once `max_units` is
  reached even though price kept climbing well past the cap, and the
  trailed stop only ever increased across the sequence of adds
  (verified the exact stop-price sequence step by step).
- **Stack-exits-together check, both exit paths**: confirmed a
  4-unit stack closes as 4 trade records on the same date at the same
  price both when the exit is a trend-exit (MA cross) and when it's a
  stop-loss (engineered a sharp reversal that breached the trailed
  stop before the 20-day MA could catch up) — and that later units
  (added at higher entry prices, against the same absolute stop level)
  correctly show larger negative R-multiples than the original unit,
  as expected.
- Also confirmed the shipped `config/strategy_v10_pyramiding.yaml`
  runs end-to-end against `--synthetic` data with no errors, the
  console output prints a `=== PYRAMIDING ===` section, and
  `report.py` renders the new "Pyramid adds" / "Positions pyramided"
  stat tiles plus a `pyramiding: +1 unit/0.5N (max 4)` subtitle
  fragment.

**Real-data result (2019-2024, SPY/AAPL/MSFT)**: the first genuinely
unambiguous win of the whole project. Against v5: total return 71.91%
→ **76.33%**, annualized 9.46% → **9.93%**, win rate 44.08% →
**45.18%**, SQN 3.92 → **4.37** — every one of those numbers is now
also the best of ANY config tested this session, including v4 (flat-%
sizing's 75.97% total / 9.89% annualized, previously the project's
best-return config). The cost is a modestly deeper max drawdown
(-7.55% → -8.53%, still well inside v4's -9.58%) — exactly the
tradeoff pyramiding is supposed to produce: it deliberately takes on
MORE risk into positions that are already working, so a somewhat
deeper worst-case is the expected price of a better average outcome,
not a red flag. 45 pyramid units were added across all 3 tickers over
the 6-year window (`Pyramid adds: 45`, `Positions pyramided: 3`),
which also explains the trade count jump from 152 to exactly 197
(152 + 45) — each add becomes its own trade record. Average R-multiple
came back IDENTICAL (0.53R both), which is itself informative: the
SQN improvement isn't from better per-trade quality, it's almost
entirely explained by the sqrt(n) term in the SQN formula acting on
45 more roughly-equal-quality trades (`sqrt(197/152) ≈ 1.14`, which
alone accounts for nearly all of the 3.92 → 4.37 move) — i.e.
pyramiding didn't change the EDGE, it gave the existing edge more
chances to compound, which is exactly what a reward/conviction-based
sizing lever is supposed to do on top of N-based risk sizing. See
PROJECT_STATUS.md item #20 for the full table and discussion.

## 15. Donchian-low trend exit (does it un-cap R-multiples?)

Every config through v10 exits a winning trade the same way: the FIRST
day price closes back below its own N-day moving average (Section 3's
`exit.ma_exit`). This raised a direct question after v10's real-data
result: this project's `Best R` has clustered around 6-8R across every
config tested so far (v4: 3.96R, v5: 6.72R, v6: 6.72R, v7: 8.26R, v8:
5.55R, v9: 7.16R, v10: 6.75R), well short of the 15R+ outliers *Way of
the Turtle*'s own R-multiple charts show. Is something in this system
structurally capping how far a winning trade can run?

**Diagnosis (code review, not a fresh data pull)**: two candidate
causes were ruled out first. `exit.take_profit_pct` is `null` in every
config used this session, so there's no artificial profit ceiling.
The stop-loss is also not the cause under normal (non-pyramided)
operation — `backtest/engine.py` sets it once at entry
(`price - stop_atr_multiple * N`) and never trails it as price simply
advances; it only moves when a pyramid unit is added (Section 14). The
actual answer is the trend-exit rule itself: a 20-day simple moving
average is a smoothed running mean, and price routinely dips below its
own trailing average during completely ordinary pullbacks inside an
intact uptrend — long before the market makes any genuine new
short-term low. The Turtles' own exit is structurally more tolerant:
Donchian System 1 exits on a 10-day LOW, System 2 on a 20-day LOW — a
real support level has to actually be revisited, a strictly higher bar
than dipping under a smoothed average. This is a direct, mechanistic
explanation for the R-multiple ceiling, not a hidden bug.

**Config** (`exit.type` — see `config/strategy_v11_donchian_exit.yaml`):

```yaml
exit:
  ma_exit: true
  type: donchian_low        # "ma_crossover" (v1-v10 default) or "donchian_low"
  exit_breakout_period: 10  # Turtle System 1's own pairing with a 20-day entry
```

Mirrors the existing `entry.type` pattern from Section 13 exactly:
`exit.type` defaults to `"ma_crossover"` when the key is absent, so
every pre-v11 config keeps behaving identically with zero code or
config changes needed. `entry.type` and `exit.type` are fully
independent of each other — a config can vary either, both, or
neither.

**How it works** (`strategy/rules.py`): `add_indicators()`
unconditionally computes a `donchian_low` column — the lowest `Low`
over the prior `exit_breakout_period` days, with `shift(1)` excluding
today's own low from its own threshold (same no-lookahead pattern as
`donchian_high` for entries). `generate_signals()` branches on
`exit.type`: under `"donchian_low"`, the SELL signal fires the first
day `Close` drops below that rolling low; under the default, it's the
existing MA-crossunder logic, byte-for-byte unchanged.
`trend_exit_reason_text()` gained a matching branch so the trade
journal reads correctly either way ("price closed below its 10-day low
(Donchian exit)" vs. "price closed back below its 20-day moving
average (trend exit)"). No changes were needed in `backtest/engine.py`
— it already just reads whatever `signal`/`reason` `rules.py`
produces, so the exit-rule swap is entirely contained to one file, the
same isolation `entry.type` achieved in Section 13.

**New config**: `config/strategy_v11_donchian_exit.yaml` copies v5's
watchlist (SPY/AAPL/MSFT), MA-crossover entry, and N/ATR sizing
UNCHANGED; the only difference from v5 is `exit.type: donchian_low`
with `exit_breakout_period: 10`. Deliberately built on v5, not v10 —
isolating the exit rule as the one new variable against the
last-clean baseline, rather than compounding it with pyramiding in the
same result. `report.py` gained an `_exit_rule_subtitle()` helper
(omitted entirely for the default `ma_crossover` exit, so every
existing report's subtitle is visually unchanged) and `run.ps1` gained
a `backtest-v11` command.

**Verified in the sandbox** before shipping, since real backtests
can't run here (no internet access):
- Confirmed `donchian_low` on a given day exactly matches the manually
  computed rolling minimum of the PRIOR `exit_breakout_period` Lows
  (not including that day) — the no-lookahead property holds exactly.
- Confirmed `exit.type: "ma_crossover"` set explicitly produces
  byte-for-byte identical signals to a config with no `exit.type` key
  at all (backward-compatibility regression), and that
  `strategy_v5_n_sizing.yaml` (no `exit.type` key) still runs cleanly
  end-to-end through the updated `engine.run_backtest()`.
- On a synthetic trending series with an engineered shallow pullback
  (a dip that does NOT make a new 10-day low), `donchian_low(10)` fired
  zero SELL signals across the window while the MA-crossunder rule
  fired 71 on the identical data — direct confirmation that the new
  exit rule is meaningfully more tolerant of ordinary pullbacks, in the
  same window where the old rule already found reasons to exit. On a
  separate synthetic series with a genuine, sustained breakdown,
  `donchian_low(10)` correctly fired with the right "10-day low" reason
  text, confirming it isn't simply broken/inert.
- Confirmed `engine.run_backtest()` runs end-to-end against the actual
  shipped `strategy_v11_donchian_exit.yaml` with no errors, correctly
  producing zero closed trades on a window where a position opened but
  never revisited a 10-day low before the window ended (the position
  stays open rather than closing early) — consistent with, not
  contradictory to, the "lets winners run further" hypothesis this
  config exists to test.

**Real-data result (2019-2024, SPY/AAPL/MSFT)**: confirms the
hypothesis. Against v5: avg R-multiple 0.53R → **0.77R** (+45%
relative, the single biggest per-trade quality jump of the whole
session), Best R 6.72R → **8.00R**, win rate 44.08% → **49.02%**, total
return 71.91% → **73.55%**, annualized 9.46% → **9.64%**. Real progress
toward the book's 15R+ outliers, and direct proof the MA-crossunder
exit really was giving back winners early. **Not a free upgrade,
though**: max drawdown got 2.16 points deeper (-7.55% → -9.71%), and
SQN went DOWN, not up (3.92 → 3.52) — trading 33% less often (152 →
102 trades, from holding both winners and losers longer between
round-trips) outweighed the per-trade quality gain in the
`sqrt(n_trades)` term of the SQN formula. Backing out the implied
R-multiple standard deviation from `sqn = avg_r / r_stdev * sqrt(n)`
makes the tradeoff legible: v5's r_stdev ≈ 1.67, v11's ≈ 2.21 — a ~32%
wider spread of outcomes, since letting a trade run longer before
exiting adds variance to how it eventually resolves, not just upside.
**On its own, v11 does not beat v10 (pyramiding) on the headline
numbers** — see Section 14 and PROJECT_STATUS.md item #23 for the full
comparison table and discussion. See Section 16 below for the direct
follow-up test this motivated: combining pyramiding with this exit.

## 16. Pyramiding + Donchian-low exit combined ("v12")

Section 14's pyramiding (bigger bets on a position that's already
working) and Section 15's Donchian-low exit (letting a position run
further before closing) each independently changed how much reward
this system lets a working trade express — one on the SIZE axis, one
on the DURATION axis. Neither beat v5 outright on every metric alone
(pyramiding won on total return/win rate/SQN at a modest drawdown
cost; the Donchian-low exit won on avg R-multiple/win rate at a bigger
drawdown cost and a worse SQN). The open question after v11's result
(Section 15, PROJECT_STATUS.md #23): does combining them compound the
benefits, the same way pyramiding cleanly compounded on top of v5's
plain baseline in Section 14 — or does stacking two "let more risk/
reward through" levers just stack their drawdown costs instead?

**Config** (`config/strategy_v12_pyramid_donchian_exit.yaml`): v5's
watchlist, entry rule, and sizing settings UNCHANGED, with v10's
`risk.pyramiding` block AND v11's `exit.type: donchian_low` block both
present at once. No new code was needed to build this — pyramiding
(`backtest/engine.py`) and `exit.type` (`strategy/rules.py`) are fully
independent code paths, the exact same situation that let v9 combine
Donchian breakout entries with portfolio selection (Section 13) with
zero new logic. `report.py`'s subtitle already shows both features
independently (`_exit_rule_subtitle()` and `_pyramiding_subtitle()`
each check their own config block), so a combined report renders
correctly with no changes there either. `run.ps1` gained a
`backtest-v12` command.

**Verified in the sandbox** before shipping, since real backtests
can't run here (no internet access) — this combination hadn't been
exercised before, so it was verified rather than assumed safe, same
discipline as v9's combination test:
- Built a synthetic price series engineered to climb steadily enough
  to trigger a pyramid add, then break down sharply enough to make a
  genuine new 10-day low (not just dip under its moving average).
- Confirmed a 2-unit pyramided stack closed as 2 trade records, BOTH
  on the same exit date and at the same exit price — the "whole stack
  exits together" invariant from Section 14 holds even when the exit
  trigger is specifically a `donchian_low` signal, not just the
  previously-tested MA-crossunder or stop-loss paths.
- Confirmed the exit reason recorded was `trend_exit` with the correct
  "10-day low (Donchian exit)" journal wording (Section 15's
  `trend_exit_reason_text()` branch), proving the SELL signal that
  closed the pyramided stack really did come from the donchian_low
  rule, not a coincidental stop-loss hit.
- Confirmed each unit retained its own entry price and R-multiple
  through the combined path — unit 2 (added at a higher price than
  unit 1, against the same trailed stop) showed a different R-multiple
  than unit 1 on the same close, consistent with the per-unit
  accounting Section 14 established.

**Real-data result (2019-2024, SPY/AAPL/MSFT)**: the two mechanisms
genuinely compound rather than just stacking their costs. v12 posted
the project's best total return (80.95%), best annualized return
(10.40%), and best single-trade Best R (9.11R) of anything tested —
all three ahead of v5, v10, AND v11 simultaneously. Measured against a
naive "add v10's delta and v11's delta to v5" baseline, the actual
gains on return and Best R came in well ABOVE the additive prediction
(e.g. total return: v10 +4.42 pts, v11 +1.64 pts, naive sum +6.06 pts,
actual +9.04 pts), while the actual cost on max drawdown came in BELOW
the additive prediction (v10 +0.98 pts, v11 +2.16 pts, naive sum +3.14
pts, actual +2.40 pts, i.e. -9.95%). Concrete evidence in the trade
log: the single best trade of the whole project (9.11R, MSFT,
2019-12-03 to 2020-02-21) was itself a pyramided unit (unit 2 of 4)
that exited via the new 10-day-low rule — the two mechanisms operating
on the very same trade. Win rate (47.89%), avg R-multiple (0.70R), and
SQN (3.83) all land between v10's and v11's numbers rather than at
either extreme. The real cost: -9.95% is now the deepest drawdown of
any non-crisis config in the project, so this is a genuinely
higher-conviction version of the system's edge, not a free upgrade —
still ~4.9 points/year behind SPY buy-and-hold's ~15.3%/year (narrower
than v10's or v11's gap alone, but not closed). See PROJECT_STATUS.md
item #25 for the full comparison table and discussion, and item #2 in
"next steps" for testing v12 across the crisis/choppy windows before
treating this as a settled upgrade.
