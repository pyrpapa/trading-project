# Master Strategy Guide

*Reference for `config/strategy_master.yaml`, the config that actually runs live. Written to be readable start to finish — no prior background assumed.*

---

## 1. The 30-second version

We built a computer program that watches six 3x-leveraged ETFs every day and follows a fixed, mechanical rulebook — no human judgment, no gut calls, no "I have a feeling about this one." It only buys when two specific conditions line up at once, it knows exactly how much money to risk before it ever places a trade, and it has a predetermined exit plan for every single position before that position even opens. Right now it's running with fake money ("paper trading") on a real brokerage account, so we can watch it operate under real market conditions with zero actual financial risk, before ever deciding whether to trust it with real money.

That's the whole idea. Everything below is how, specifically.

---

## 2. The cheat sheet

If you only remember one section, make it this one — everything else in this guide is this, expanded with real numbers.

**BUY** — checked once a day, for each ticker we don't already own. Both must be true:
1. Price just crossed above its 20-day average (short-term trend turned up)
2. Today's volume is above normal (real interest, not noise)

Both true → buy today. Either false → do nothing.

**HOW MUCH TO BUY (risk sizing)** — decided fresh every trade, before anything else:
1. Pick a risk budget: 1.0% of the total account, always.
2. Look at how choppy the ticker has been lately (call this "N").
3. Set the stop-loss 2×N below entry price.
4. Buy exactly enough that *if* the stop-loss hits, the loss equals that 1.0% — no more, no less.

A choppier ticker → smaller position. A calmer ticker → bigger position. The **dollar risk is always the same**; only the position size adjusts to get there.

**SELL** — checked every day a position is open, multiple possible triggers, only one applies per trade:
1. **Stop-loss (fixed)** — price falls to the floor calculated at entry → sell immediately. Caps the loss.
2. **Stop-loss (trailing)** — as the position climbs, this floor gets pulled up behind it (see Section 7) — so a winning position that reverses hard can still exit via "stop_loss," just at a much higher, profit-locking price, not the original entry-based floor.
3. **Trend exit** — price makes a new 10-day low → sell. The trend that justified buying is over.
4. **Take-profit — turned off.** No "sell once up X%" rule exists. Winners run until #2 or #3 happens, with no ceiling.

Whichever trigger fires *first* is what actually closes the trade.

**PYRAMID** — only for a position already open and winning:
- If price climbs another half-N above where the last unit was bought, buy *more* of that same ticker (up to 4 total units), each sized fresh with the same 1.0%-risk math.
- When it's time to sell, **everything sells together, all at once** — not one unit at a time.

**THE RATING METRICS** — how we score whether any of this is working. There isn't one single number anymore — see Section 13 for the full set (CAGR, drawdown, Sortino, Calmar, Profit Factor, Beta/Alpha vs. the S&P 500, and more), each answering a different question about the same result.

---

## 3. What kind of system this actually is

**Mechanical, not discretionary.** A human isn't looking at charts and deciding "this feels like a good time to buy." The computer checks a fixed set of numeric conditions every day, and if they're true, it acts — identically, whether it's a Tuesday or a holiday, whether the news is exciting or boring, whether "it" (the program) is nervous or confident, because it's neither.

**Tested before trusted.** Every rule in this system was checked against years of *real historical prices* first — replaying 2019 through today and asking "if these exact rules had been running the whole time, what would have happened?" That's called **backtesting**, and it's how every number you'll see below was arrived at before a single real (or fake) dollar was ever risked.

**One file controls everything.** The entire behavior of the live system is controlled by a single file: `config/strategy_master.yaml`. Change a number in that file — how much to risk per trade, which tickers to watch, how tight the stop-loss is — and the system's behavior changes. No programming required for most adjustments. This guide walks through exactly what's in that file today.

---

## 4. The watchlist — what it trades, and why the pivot

**Currently:** SPXL (3x S&P 500), TQQQ (3x Nasdaq-100), SOXL (3x semiconductors), FAS (3x financials), TNA (3x small-caps), TECL (3x technology) — all 3x leveraged ETFs.

**This wasn't always the strategy.** For most of this project's history, the live config traded six cryptocurrencies (BTC, ETH, SOL, XRP, LINK, RENDER) instead — that track is fully preserved, untouched, at `config/strategy_master_crypto_v36.yaml`, in case it's ever revisited as its own separate, deliberately smaller allocation. Here's why the primary strategy moved off crypto:

**Crypto's backtested numbers were mostly a historic bull market, not durable skill.** The multi-year backtests showed extraordinary returns (13,000%+ in the best windows), but every risk-reducing improvement tried — a trailing stop, tighter position limits, blending with equities — bought safety by giving up return, and the *size* of that trade (roughly an 80% haircut in the most protective version) revealed the underlying edge was much thinner than the headline number implied. The real test: checked against the most recent 12 months specifically (rather than only the multi-year windows that happened to contain a historic bull run), crypto **lost money** — a genuine, real loss, not just underperformance — and nothing tried fixed that without also gutting the years that worked.

**Leveraged ETFs, tested on that exact same recent window, made real, healthy money.** +35.55% return, and — just as importantly — the *quality* of the trades looked completely different: 29 genuine trend-exits versus only 16 stop-losses, compared to crypto's 32-of-33 stop-loss pattern in the same stretch. That's the signature of the entry/exit machinery actually working as designed (catching real trends), not fighting constant whipsaw.

**The watchlist was deliberately widened from an initial 3 tickers to 6.** The 3-ticker version (SPXL/TQQQ/SOXL) actually had a *higher* raw return on that recent window — but almost the entire gain came from one single ticker (SOXL), a fragile, single-name-dependent result. Adding FAS/TNA/TECL without the trailing stop made things *worse* (classic ticker dilution, the same lesson this project has hit before) — but WITH the trailing stop, the wider list produced the best risk-adjusted result of anything tested. Diversification only paid off once there was a mechanism to actually protect the gains it was diversifying.

**One honest, real weak spot, found by testing rather than assumed away:** across 2020-2022 — a window spanning both the COVID recovery bull run *and* the 2022 crash — this strategy is essentially flat (near-zero return, near-zero Sortino). 3x daily-reset leverage compounds losses on the way down the same way it compounds gains on the way up, and this is the first time that risk has actually been tested against a real crash rather than just assumed. Not disqualifying, but real, and worth knowing before trusting the other three tested windows as the typical case.

---

## 5. How it decides to BUY

Two conditions, from `entry:` in the config, **both have to be true on the same day**:

| Rule | Config value | Plain meaning |
|---|---|---|
| Moving-average crossover | `ma_period: 20` | Price just crossed *above* its own 20-day average — "the short-term trend just turned up" |
| Volume confirmation | `volume_confirmation: true` | Today's trading volume is above its own 20-day average — real buying interest, not a quiet, meaningless wiggle |

**Note for anyone who remembers the old crypto version:** there used to be a third condition, a 150-day "regime filter" requiring the longer-term trend to agree too. It was tested directly on this asset class and it *hurt* — return dropped and Sortino got worse — so it's deliberately not part of this config. A lever that helped crypto isn't assumed to help everything; each one gets checked on its own.

### Real example: an SPXL trade, 2025-08-19

Price crossed above its 20-day moving average with volume confirming, and the system bought its first unit at **$188.00**.

---

## 6. How much it buys — position sizing

The system doesn't buy a flat dollar amount every time. It sizes each trade so that **if the trade goes wrong and hits its stop-loss, the loss costs a fixed, small slice of the total account** — regardless of how volatile that particular ticker happens to be. This is the "N-based" or "Turtle-style" method, from `risk:` in the config:

```
risk_pct_per_unit: 1.0      →  risk 1.0% of total account equity per trade
stop_atr_multiple: 2.0      →  stop-loss set 2× a volatility measure (N) away from entry
```

**"N" (also called ATR)** is just a rolling measure of how much a ticker typically moves in a day. A choppier ticker has a bigger N, which — by design — means the system automatically buys *fewer* shares of it, so the dollar risk stays the same either way. (Section 12 has the full mechanical breakdown of how N is calculated, if you want the exact formula.)

### Real example, continued

- Entry price: $188.00
- Risk budget: 1.0% of account equity
- Risk per share: 2.0 × N (that day's ATR for SPXL)
- Position size = risk budget ÷ risk-per-share × price, capped by two ceilings below

Two safety ceilings also apply on top of this math, regardless of what the formula above says: no single position can exceed **35%** of the account (`max_position_pct`), and total money invested across everything can't exceed **80%** of the account (`max_invested_pct`) — so at least 20% always stays in cash.

---

## 7. How it decides to SELL — the ways out

From `exit:` and `risk.trailing_stop` in the config, checked every day a position is open:

1. **Fixed stop-loss** — the level calculated at entry. Never moves down, only ever gets replaced by something *higher* (see #2 and pyramiding).
2. **Trailing stop (new since the crypto era)** — `trailing_stop.enabled: true, atr_multiple: 2.0`. Every day, the system tracks the highest price the position has reached since entry, and pulls the stop up to (that peak − 2×N), if that's higher than the current stop. This exists specifically to catch a real gap in the older system: a sharp spike that reverses fast could round-trip almost entirely — neither the fixed stop nor the 10-day trend exit was fast enough to protect any of the gain. Now, a position that spiked and is giving it back exits at a *locked-in profit level*, not back at the original entry-based floor. **This is why some "stop_loss" exits in the trade log are actually wins** — the SPXL trade from Section 5 exited via `stop_loss` on 2025-10-10 at $197.60, up from its $188.00 entry, because the trailing stop had already climbed well above the original floor by the time it triggered.
3. **Trend exit** — price closes below its own 10-day low (`exit_breakout_period: 10`, a "Donchian" exit). The normal, healthy way most trades end when the trend itself genuinely breaks down, distinct from either stop-loss trigger.
4. **Take-profit — deliberately switched off** (`take_profit_pct: null`). There is no price target that automatically locks in a gain. This is on purpose: the philosophy is "cut losses short, let winners run as far as they'll go," rather than capping upside artificially. (Testing a take-profit directly confirmed this — even a fairly generous one cut total returns by more than half.)

### Real trade, start to finish (SPXL, 2025-08-19 to 2025-10-10)

- **8/19**: Entry, unit 1, $188.00.
- **8/22**: Price climbed enough to trigger a pyramid add — unit 2 bought at $192.36 (see Section 8).
- Along the way, the trailing stop climbed with the price, replacing the original fixed floor.
- **10/10**: Price reversed enough to hit the (by-then much higher) trailing stop. Both units closed together: unit 1 exited at +1.03R ($102.03 profit), unit 2 at +0.51R ($40.98 profit).

---

## 8. Pyramiding — growing a winning position

From `risk.pyramiding` in the config:

```
enabled: true
unit_interval_n: 0.5    →  add another unit every 0.5×N the price moves further in our favor
max_units: 4             →  cap the stack at 4 total units
```

Every time price rises by half of the current volatility measure above the *last* unit's own entry price, the system adds another position — up to 4 total — each one independently risk-sized the same way as the original entry. In the SPXL example above, the second unit triggered at $192.36, a genuine 0.5N move above the $188.00 entry.

The logic: a trade that's already proving itself right earns a bigger bet, rather than every trade getting exactly the same size regardless of how well it's working. When any unit sells, the *whole stack* sells together, at once — not partial exits.

---

## 9. The machinery — what actually runs, and when

- **Alpaca** — the brokerage. The account is currently a **paper account**: real market prices, real order mechanics, fake money. Same code would place real trades on a real account if that switch were ever deliberately flipped (there's a hard safeguard in the code specifically preventing this from happening by accident).
- **Supabase** — the database. Every signal, trade, and account snapshot gets logged here — this is the system's permanent record, and what feeds the results dashboard.
- **GitHub Actions** — the automatic trigger. Runs once a day, **weekdays only, at 20:30 UTC** (4:30pm ET), thirty minutes after the stock market closes. This changed from the crypto era's 24/7, every-day schedule specifically because ETFs only trade during market hours, Monday through Friday — if the config ever switches back to `strategy_master_crypto_v36.yaml`, this schedule needs to switch back too (see that file's own header).
- **Manual runs** (`python live/run_live.py`) — can be run any time. Running it more often *won't* generate new buy/sell trend signals faster — those are locked to once a day, on purpose, since the whole strategy is built around daily-bar trends, not minute-by-minute noise. What extra runs *do* usefully catch sooner is a stop-loss breach (fixed or trailing) or a pyramid-add opportunity, since those specific checks use a live price, not the daily bar.

---

## 10. Where the backtest data actually comes from

Algo traders are right to care about this — bad or subtly-wrong historical data can make a strategy look great (or terrible) for reasons that have nothing to do with the strategy itself. Here's exactly what this project does, and where the real limitations are.

**Source: `yfinance`, a free library that pulls from Yahoo Finance.** No paid data subscription, no API key. `data/fetcher.py` calls it directly and returns Open/High/Low/Close/Volume for whatever ticker and date range is requested.

**Prices are automatically split- and dividend-adjusted.** This matters more than it sounds like. A stock that does a 10-for-1 split (NVDA did exactly this in June 2024) would otherwise show up in the raw data as a fake ~90% overnight "crash" — the price genuinely drops that much on paper, even though nothing happened to the actual value of anyone's holdings. Checked this directly against NVDA's real June 2024 split date: the adjusted price data flows smoothly through the split with no artificial cliff, confirming the adjustment is actually working, not just assumed. Dividend adjustment matters too, for a different reason — without it, a backtest would understate real returns, since a real investor holding a dividend-paying position earns that cash on top of the price movement.

**Caching**, in `data/cache/`: once a ticker/date-range combination is fetched, it's saved to a local CSV so repeated backtests don't keep re-downloading the same data, and so testing can continue offline once the cache is populated. The cache is smart enough to detect when a request needs a *wider* date range than what's cached and automatically refetches rather than silently returning an incomplete slice.

**A real, found-and-fixed limitation: this free pipeline had a genuine data gap.** While testing the ETF strategy, one ticker (FAS) was missing two trading days in its cached data — not a corporate action or a real market event, just a hiccup somewhere between Yahoo's servers and the local cache. The backtest engine's handling of that gap was *also* wrong (see Section 11) — it valued the open position at $0 for those two days instead of carrying forward its last known price, creating a fake ~40% one-day portfolio crash that "recovered" the moment data resumed. Both the data gap and the engine's mishandling of it are now understood and the engine side is fixed — but it's a live reminder that a free, unofficial data source can and does have real gaps, something a paid institutional data feed is less prone to.

**What's NOT modeled, honestly:**
- **No bid-ask spread or slippage.** Every backtest assumes a trade fills exactly at the day's closing price, which is never quite true in real trading — a real fill will be some amount worse, especially on a fast-moving day. `commission_pct` exists in every config and currently defaults to 0.
- **Survivorship bias risk, in principle.** Yahoo Finance serves data for currently-listed tickers — a ticker that existed historically but was later delisted or merged away generally isn't testable this way. Less of a concern for large, established ETFs like the current watchlist than it would be for, say, small individual stocks, but worth knowing as a general limitation of this data source.
- **Point-in-time reproducibility.** Because adjustments are applied retroactively, the exact "Close" value for a historical date can shift slightly if a new split or dividend happens *after* that date but before you re-fetch — this is the CORRECT behavior for accurate historical returns, but it does mean re-running the exact same backtest at two different points in time isn't guaranteed to produce byte-identical cached data, only the same effective returns.

---

## 11. Bugs found and fixed — what's solid now

Real problems, caught and closed out:

- **Pyramiding silently never ran live.** Every backtest assumed positions could grow via pyramiding, but the actual live/paper code had no implementation of it at all — fixed before real trading started.
- **Crypto ticker symbol mismatches** (three different formats for the same coin across the data source, the broker's order API, and the broker's positions API) — caught and fixed. Not relevant to the current ETF watchlist (equity tickers don't have this problem), but the fix stayed in place for if crypto is ever reactivated.
- **Stop-loss checks were using stale pricing.** The daily price data source sometimes lagged behind "now" — fixed by pulling a live quote from the broker specifically for stop-loss and pyramid-add checks (the buy/sell trend *signal* itself still correctly uses the daily bar, unchanged).
- **A silent mark-to-market bug in the backtest engine itself.** If a ticker's price data had a gap on a day it had an open position (found via a stale data cache, though the same class of bug could be triggered by any real data gap), the position was valued at $0 for that day instead of its last known price — creating a fake, dramatic drawdown that "recovered" the instant data resumed. Found while investigating an anomalous test result, fixed at the source in `backtest/engine.py`, and confirmed it doesn't change any of the multi-window numbers this guide reports (the corrupted case wasn't the worst point in any of those particular runs) — but it protects every future backtest from the same failure mode.
- **The trailing stop and the live stop-price reconstruction were built and validated together**, not backtest-only — `live/run_live.py` has its own separate, stateless stop-price logic (it has to reconstruct the stop fresh each run from trade records, since there's no persistent memory between daily runs), and it would have silently missed the trailing stop entirely if it hadn't been explicitly ported there too.

---

## 12. What's NOT resolved yet — honest open risks

- **No standing stop-loss order.** The stop (fixed or trailing) is only checked when the program runs. A missed automatic run combined with a sharp price move is a real, currently-unprotected gap.
- **Leverage risk through a real crash is now tested, and the result is a genuine yellow flag.** The 2020-2022 window (COVID rally + the 2022 crash) came back essentially flat — not a loss, but not the strength the other three windows showed either. 3x daily-reset leverage compounds badly in exactly this kind of environment, and this is real evidence of that, not just a theoretical concern anymore.
- **Even the strongest window doesn't clearly beat simple buy-and-hold on a risk-adjusted basis.** On the same recent-12-months window, plain S&P 500 buy-and-hold (SPY) made +21.99% with only -8.88% max drawdown — a much better return-per-unit-of-risk than this strategy's own +35.55%/-21.04% in that same stretch. Beating a benchmark's raw return isn't the same as adding real value beyond just being exposed to a rising market — see Section 13's Beta/Alpha explanation for how to check this directly on any given result.
- **Backtested returns lean on a handful of outlier trades**, not a smooth, evenly-distributed edge, same caveat as ever — treat headline return numbers as "what happened when a few big trades landed," not a typical-year expectation.
- **The live track record is effectively brand new** under this ETF configuration — almost all real-world confidence built up under the old crypto config doesn't carry over, since this is a materially different strategy now.

None of this means the system is broken — it means the honest state is "meaningfully better-tested than the crypto version was, with at least one real, newly-confirmed weakness," not "proven, no caveats."

---

## 13. How we judge "is this actually good" — every metric, plainly

There isn't one headline number anymore. Each metric below answers a genuinely different question, and a strategy can look great on one and mediocre on another — that's the point of tracking all of them, not picking a favorite.

| Metric | What it actually measures | How to read it |
|---|---|---|
| **Total Return %** | Total gain/loss over the whole tested period, as a percentage of starting money. | Bigger is better, but says nothing about *how bumpy* the ride was to get there. |
| **CAGR** (Compound Annual Growth Rate) | The steady year-over-year growth rate that would produce the same total return — "if this grew at the same % every single year, what would that rate be?" | Lets you compare a 6-month test and a 6-year test on equal footing. This is what the old guide called "Annualized." |
| **Max Drawdown** | The single worst peak-to-trough decline anywhere in the test — "at the worst possible moment, how far underwater would you have been?" | A bigger (more negative) number means a rougher psychological and financial ride, even if the strategy ultimately made money. |
| **Ulcer Index** | Like max drawdown, but accounts for *how long* you stayed underwater too, not just the single worst instant. A strategy that grinds sideways-down for months scores worse here than one with the same max drawdown that snaps back quickly. | Lower is better. Genuinely different information from max drawdown alone. |
| **Win Rate** | What % of closed trades made money. | Sounds important, but a strategy built to "cut losses short, let winners run" can have a win rate *under 50%* and still be very profitable — a few big wins can outweigh many small losses. Don't judge a strategy by this number alone. |
| **Trades** | How many positions were opened and closed. | Context, not a verdict — more trades isn't automatically better or worse. |
| **Avg R-multiple** | Every trade's profit or loss expressed as a multiple of what was originally risked on it — "+2R" means a trade made twice what was risked; "-1R" means it lost exactly the planned amount. This average is across every closed trade. | The core "edge per bet" number this whole system is built around, straight from *Way of the Turtle*'s own playbook. |
| **Profit Factor** | Total dollars won ÷ total dollars lost (both as positive numbers) — "for every dollar lost, how many dollars were won?" | Above 1 means profitable overall; above 2 is generally considered strong. |
| **System Quality Number (SQN)** | A Van Tharp metric: how big the average R-multiple is, *and* how consistent that pattern is — a big average with wildly unpredictable results scores worse than a smaller, steadier one. | Higher is better, roughly: below 1.6 poor, 2.0-2.4 average, 2.5-2.9 good, 3.0-5.0 excellent, 5.0+ superb. |
| **Sortino Ratio** | Annualized return divided by how much the *downside-only* volatility was — a version of "risk-adjusted return" that doesn't punish big, unpredictable *wins* the same way it punishes losses. This is the primary metric this project actually trusts for judging a strategy, chosen specifically because it has a real, externally-recognized scale. | Below 0 is bad (losing money risk-adjusted), 0-1 is sub-par, 1-2 is good, 2-3 is very good, above 3 is excellent. |
| **Calmar Ratio** | Annualized return ÷ worst-case drawdown — "how much return am I getting per unit of worst-case pain." | Directly comparable across strategies or against simple buy-and-hold, regardless of scale. Higher is better; this is the metric behind the "SPY beat this strategy on a risk-adjusted basis" comparison in Section 11. |
| **Beta (vs. S&P 500)** | How much this strategy's daily moves track the S&P 500's — a statistical measure of "how correlated is this with the broad market." | Near 0 means barely correlated; near 1 means it moves about as much as the market does; above 1 means it's more volatile than the market in the same direction. |
| **Alpha (vs. S&P 500)** | The extra return *left over* after accounting for that market correlation — "is this actually adding value beyond just being exposed to a rising market, or would a leveraged S&P 500 fund alone have done just as well?" | Positive alpha is the real prize — it means genuine, strategy-specific value, not just riding the market up. Negative alpha means the raw return looked fine but wasn't actually earning its keep. |
| **Best / Worst R** | The single best and single worst trade, in R-multiples. | Shows how much of the total result is riding on outlier trades — a huge gap between "average R" and "best R" is a sign returns are concentrated in a few big winners, not evenly spread. |
| **Longest Losing Streak** | The most consecutive losing trades in a row. | A gut-check for what a rough stretch actually feels like while it's happening, separate from the eventual math working out. |

**A worked example, from this guide's own trade walkthrough:** the SPXL trade in Section 7 closed at +1.03R on unit 1 and +0.51R on unit 2 — real, positive R-multiples that feed directly into the Avg R-multiple, Profit Factor, and SQN numbers for the whole backtest. Multiply that pattern across every trade in a given window, and that's where every number in the table above actually comes from — none of it is estimated or modeled, it's all a direct roll-up of real, individual trade outcomes (or, for the metrics based on the day-by-day account value like Max Drawdown, Ulcer Index, Sortino, and Calmar, a direct roll-up of the daily account value itself).

---

## 14. Where things honestly stand right now

**What's solid:** the mechanism itself (entry rules, position sizing, pyramiding, exits including the new trailing stop) is tested across all four standard historical windows, not just the ones that happened to look good, and every real bug found along the way — including a subtle one in the backtest engine itself — got fixed and verified rather than assumed away.

**What's genuinely unproven:** whether this specific ETF configuration has a repeatable edge worth real capital, long-term. The strongest test result (the most recent 12 months) is real and encouraging, but it's one window, it doesn't clearly beat simple buy-and-hold on a risk-adjusted basis, and the 2020-2022 window is a genuine, newly-confirmed weak spot from real leverage risk, not a hypothetical one anymore.

**The honest next step isn't "commit real capital" yet** — it's letting a live paper track record actually accumulate under this new configuration (the crypto-era live history doesn't transfer, this is functionally a different strategy now), and deciding deliberately, with the Section 12 metrics in hand, whether the risk-adjusted case is actually there.

---

## 15. Glossary

- **Backtest** — simulating the strategy against historical prices, no real money involved
- **Paper trading** — running for real, in real time, against a broker, using fake money
- **Signal** — a computed BUY or SELL trigger for a specific ticker on a specific day
- **Position** — a currently-held (open) trade
- **Entry / Exit** — opening / closing a position
- **Stop-loss (fixed)** — an automatic sell if a position falls too far below its entry price, capping the loss
- **Trailing stop** — a stop-loss that moves UP as a position climbs, protecting gains instead of just capping losses — see Section 7
- **Trend exit** — a sell triggered by the trend itself reversing (here: a new 10-day low), as opposed to either kind of stop-loss
- **Take-profit** — an automatic sell once a position is up a set amount (currently switched off — winners aren't capped)
- **N / ATR** — a rolling measure of how much a ticker typically moves; used to size positions and set stops relative to each ticker's own volatility
- **Pyramiding** — adding more to an already-winning position as it proves itself right
- **R-multiple** — a trade's profit or loss expressed as a multiple of what was originally risked (e.g. "+3R" = made 3 times the amount risked)
- **CAGR** — Compound Annual Growth Rate; the steady yearly growth rate equivalent to the actual (often lumpier) result
- **Drawdown** — a decline from a peak account value; *max drawdown* is the worst such decline observed
- **Ulcer Index** — like max drawdown, but also accounts for how long a decline lasted, not just how deep
- **SQN (System Quality Number)** — a score for how consistent a strategy's edge is, not just how big
- **Sortino Ratio** — annualized return divided by downside-only volatility; this project's primary trusted risk-adjusted metric
- **Calmar Ratio** — annualized return divided by max drawdown; "return per unit of worst-case pain"
- **Profit Factor** — total dollars won divided by total dollars lost
- **Beta** — how correlated a strategy's returns are with a benchmark (here, the S&P 500)
- **Alpha** — the return left over after removing what Beta alone would predict; the real measure of added value
- **Leveraged ETF** — a fund that aims to deliver a multiple (here, 3x) of a benchmark's daily return, using derivatives/debt — amplifies both gains and losses, and can decay in choppy or declining markets even if the underlying benchmark is roughly flat

---

## 16. Ready-made explanations, at different depths

**10 seconds:** "It's a rules-based trading program for leveraged ETFs, currently running with fake money to prove itself before we'd ever consider using real money."

**1 minute:** "We built a computer program that watches six leveraged ETFs and buys or sells based on fixed, tested rules — never a gut call. It only risks a small, fixed percentage of the account on any one trade, and every trade has a predetermined exit plan before it's even placed, including a trailing stop that locks in gains as a winning position climbs. It's running on a real brokerage account right now, but with fake money, specifically so we can watch it handle real market conditions with zero actual risk before deciding whether it's earned the right to use real money. This used to trade crypto instead — that version is preserved separately, but the current live strategy switched to ETFs after crypto's backtested numbers turned out to lean heavily on a historic bull market rather than durable, repeatable edge."

**5 minutes:** everything in Sections 5 through 8 above, using the real SPXL trade as the walkthrough — how it decided to buy, how much it bought, how the trailing stop protected the gain, and how pyramiding added to the winning position.
