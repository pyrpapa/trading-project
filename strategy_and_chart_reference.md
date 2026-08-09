# Strategy & Chart Reference

A plain-language reference for two things: what every value in
`config/strategy.yaml` actually does, and how to read the HTML report
`python run_backtest.py --chart` produces. Written as a companion to
`STRATEGY_GUIDE.md` (which documents the same config from a more
technical angle) — this version leans toward "what does this number
mean and how might I improve it," and adds the chart explanations
that don't exist anywhere else yet.

---

## 1. The strategy config, value by value

Base reference file: `config/strategy.yaml`. Where `strategy_v4.yaml`
or `strategy_v5_n_sizing.yaml` change a value, it's noted inline.

### Watchlist

```yaml
watchlist: [SPY, AAPL, MSFT]
```

The entire universe the strategy is allowed to trade — nothing outside
this list is ever bought, regardless of what it's doing. It's
hand-picked, not selected by any rule.

Worth knowing: this isn't really three diversified bets. AAPL and MSFT
are two of SPY's largest holdings, so a move in either tends to drag
SPY the same direction. This is closer to one concentrated
large-cap-tech position wearing three tickers than three independent
markets.

**Improvement path**: a portfolio-selection algorithm — something that
screens for liquidity, checks real diversification (different
sectors/asset classes, or at least low correlation to each other), and
possibly rotates the list over time instead of it being permanent.
Confirmed gap, not built yet (see `PROJECT_STATUS.md`).

### Entry rule

```yaml
entry:
  ma_period: 20
  volume_confirmation: true
  volume_ma_period: 20
```

Buys the moment a ticker's price closes above its 20-day moving
average, but only if today's volume is also above its own 20-day
average (the idea: don't trust a price move on thin volume).

`ma_period: 20` is a fairly fast/short lookback — quick to react to
new trends, but also reacts to short-term noise, which is a big part
of why win rate sits around 26-44% across the configs tested so far.
Raising it (e.g. to 50) means fewer, more committed trades and less
whipsaw; lowering it means more trades and more false starts.

`volume_confirmation` is a blunt instrument as written — "above its
own 20-day average" doesn't distinguish a real breakout from routine
noise on a stock like AAPL, where volume spikes are common and not
always meaningful.

**Improvement path**: Donchian breakout entries (enter on an N-day
price breakout instead of an MA cross) — the Turtles found this
generalizes better across different kinds of markets. Also queued: a
volume filter that compares against a longer baseline or weights by
how unusual the spike actually is.

### Exit rule

```yaml
exit:
  ma_exit: true
  stop_loss_pct: 8.0
  take_profit_pct: null
```

Three ways out, whichever fires first: the trend reverses (price
closes back below the same 20-day MA), or you're down 8% from entry
regardless of trend (a fixed backstop), or — currently disabled
(`null`) — you're up some target %.

`take_profit_pct: null` means winners currently run all the way until
the trend actually breaks or the stop catches you. That's deliberate
and consistent with trend-following philosophy — cutting the upside
early is usually a net negative for this style of system.

`stop_loss_pct: 8.0` is a flat distance regardless of how volatile the
stock actually is — either exits too early on volatile names or too
late on calm ones.

**Improvement path (already built)**: N/ATR-based stops
(`risk.sizing_method: atr_unit` in `strategy_v5_n_sizing.yaml`) replace
this flat 8% with a stop that scales to each stock's own recent
volatility. Not yet tested on real historical data, only synthetic.

### Risk / position sizing

```yaml
risk:
  max_position_pct: 5.0     # 20.0 in v4 and v5
  max_invested_pct: 60.0
```

`max_position_pct` caps any single trade as a % of account value;
`max_invested_pct` caps total exposure (the rest sits in cash).

This pair caused the original v1 bug: with only 3 tickers and a 5%
cap, at most 15% of the account could ever be deployed, no matter what
the 60% ceiling allowed. v4 fixed this by raising the cap to 20% — a
better number, but still hand-picked, not derived from the actual risk
of each position.

v5 (`sizing_method: atr_unit`, plus `atr_period: 20`,
`risk_pct_per_unit: 1.0`, `stop_atr_multiple: 2.0`) replaces the
*primary* sizing logic with something that scales per position; here
`max_position_pct`/`max_invested_pct` become an outer safety ceiling
rather than the main lever.

**Improvement path (already built)**: a correlation-based circuit
breaker (`risk.correlation_breaker` in `config/strategy_v6_circuit_breaker.yaml`)
now stops the strategy from stacking positions that are highly
correlated with what's already open — see STRATEGY_GUIDE.md Section 11
for the full config and mechanics. It computes actual rolling
correlation from price history rather than a hand-picked list, and
blocks (rather than resizes) a new entry when the cap is hit. Not yet
tested on real historical data, only synthetic — see next steps in
PROJECT_STATUS.md.

### Backtest settings

```yaml
backtest:
  starting_cash: 10000
  start_date: "2019-01-01"
  end_date: "2024-12-31"
  commission_pct: 0.0
```

`starting_cash` only affects how dollar figures look, not the
underlying %/ratio results. The date range is one specific 6-year
window — v4 has also been tested across 2012-2018 and 2006-2011; v5
hasn't been run against those yet.

`commission_pct: 0.0` accurately reflects Alpaca's stated fees, but
quietly assumes zero slippage and zero bid-ask spread too. For a
strategy generating ~240 trades over 6 years, that's a real, currently
invisible cost that could meaningfully eat into an already-thin edge.

**Improvement path**: model a small slippage cost (e.g. 0.05-0.1% per
trade) to see how sensitive results are to that assumption.

---

## 2. Reading the chart report

Generated by `python run_backtest.py --chart` into
`results/<label>_report.html`. All example numbers below are from an
actual sample run (`strategy_v5_n_sizing.yaml` on synthetic data) —
illustrative of how to read the chart, not a claim about real
performance.

### Stat tiles (top row)

| Tile | Example value | What it means |
|---|---|---|
| Total return | -5.79% | Whole-period % change in account value |
| Annualized | -0.99% | Total return converted to a "per year, compounded" rate — comparable across different time spans |
| Max drawdown | -13.76% | The single worst peak-to-trough decline at any point — not just where it ended up |
| Win rate | 26.36% | % of trades that closed profitably. Trend-following systems routinely run low here by design — most breakouts are false starts (small losses), and the system depends on rare big winners to make up for them |
| Trades | 239 | Total round-trips (entry + exit) over the period |
| Avg R-multiple | -0.07R | Average outcome per trade, in units of "how much was risked." -0.07R = lost ~7% of planned risk on average |
| System Quality (SQN) | -0.88 | Consistency of the edge (avg R ÷ spread of R, scaled by trade count), not just its size. Negative = no real edge; good systems are usually well above 0, often cited as 1.5-2+ |
| Best / Worst R | 6.46R / -1.87R | Best single trade returned 6.46× its planned risk; worst lost 1.87×. A worst-case beyond roughly -1R (with a 2N stop) usually means the price gapped past the stop overnight — a real risk with daily-bar backtesting |

Win rate alone doesn't tell you if a system works — you need it next
to the size of wins vs. losses (which is what R-multiples capture).

### Equity curve + drawdown

Two stacked panels sharing the same time axis. The top (blue line) is
portfolio value day by day. The bottom (red shaded area) is drawdown —
how far below the most recent peak you are at every point, always
≤ 0%. Every time the blue line makes a new high, the red area touches
zero; every decline after that shows up as red depth.

This is the "could I actually sit through this" chart — a headline
max-drawdown number on paper feels very different from living through
the stretch it came from.

### Monthly returns

The chart modeled after the *Way of the Turtle* performance chart.
Each bar is one calendar month's % change in account value — blue for
a winning month, red for a losing one. A different lens than the
equity curve: this shows the *rhythm* of the strategy (how often it
wins/loses month to month, and how lumpy the good/bad stretches are)
rather than the cumulative path.

### R-multiple distribution

A histogram of every trade's R-multiple, bucketed in 0.5R bins, same
blue/red split at zero. This is the clearest picture of what a typical
trade looks like: usually a large red cluster of small losses just
below zero, a smaller blue cluster of modest wins, and (hopefully) a
thin tail stretching out toward large winners. That shape — many small
losses, a few outsized winners — is the theoretical signature of a
healthy trend-following system. Whether the tail is fat enough to
outweigh the losses is exactly what "avg R-multiple" and "SQN" above
are measuring numerically.

### Price + buy/sell markers (one panel per ticker)

Gray line is closing price. Blue up-triangles are entries, red
down-triangles are exits — pulled straight from the trade journal
(`entry_log`/`exit_log`). This is the visual sanity check: dense
clusters of markers in a choppy stretch mean a lot of whipsaw there;
sparse, spaced-out markers in a clean trend mean the entry rule is
behaving as intended.

---

*Generated during the "Way of the Turtle" concept-mapping sessions —
see `PROJECT_STATUS.md` for the full running log of what's been built
and what's next.*
