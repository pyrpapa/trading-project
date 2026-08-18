# Master Leveraged-ETF Strategy — Complete Guide

*Reference for `config/strategy_master.yaml`, the config that actually runs live. Rewritten 2026-08-18 — the system pivoted from crypto to leveraged ETFs since the last version of this guide; nothing below assumes crypto.*

---

## 1. The 30-second version

We built a computer program that watches seven 3x-leveraged ETFs every day and follows a fixed, mechanical rulebook — no human judgment, no gut calls. It only buys when specific conditions line up, it knows exactly how much money to risk before it ever places a trade, and it has a predetermined exit plan for every position before that position even opens.

Right now it's running with fake money ("paper trading") on a real brokerage account. The strategy itself has been through a long design phase — including a real pivot away from crypto once the numbers showed that edge was mostly just leverage, not skill — and is now considered locked in for a while: no more parameter tuning against the same backtested history, just watching how it performs on data it's never seen before.

---

## 2. The cheat sheet

If you only read one section, make it this one.

**BUY** — checked once a day, per ticker not already held. Both must be true:
1. Price just crossed above its 20-day average (short-term trend turned up)
2. Today's volume is above normal (real interest, not noise)

**HOW MUCH TO BUY** — decided fresh every trade:
1. Risk budget: 1.0% of the total account, always.
2. Measure how choppy the ticker's been lately (call it "N").
3. Set the stop-loss 1.5×N below entry price.
4. Buy exactly enough that *if* the stop-loss hits, the loss equals that 1.0% — no more, no less.

**SELL** — checked daily, three possible triggers:
1. **Stop-loss** — price falls to the floor from step 3 → sell. Caps the loss.
2. **Trailing stop** — once a position is profitable, the floor rises with it (1.0×N below the highest price seen) → locks in gains as a winner runs.
3. **Trend exit** — price makes a new 10-day low → sell, the trend that justified buying is over.
4. **Take-profit — off.** No "sell once up X%" rule. Winners run uncapped until #2 or #3 fires.

**PYRAMID** — for a position already open and winning: every time price climbs another half-N above the last unit's own entry, buy more of that ticker (up to 4 units total), each freshly risk-sized. The whole stack shares one trailing stop and sells together, all at once.

**THE RATING METRICS** — not "did it make money," but "did it make money *worth the risk taken*":
- **Calmar ratio** = annualized return ÷ worst drawdown. How much return per unit of worst-case pain.
- **Sortino ratio** = annualized return ÷ typical "bad day" severity. Only counts downside, never punishes a big win.
- **Alpha vs. SPY** = how much return is left over after accounting for how much extra market risk (beta) this strategy is carrying, compared to simply owning SPY. The real test of "is this actually worth the extra risk."

---

## 3. What kind of system this actually is

**Mechanical, not discretionary.** A human isn't looking at charts and deciding "this feels right." The computer checks a fixed set of numeric conditions every day and acts identically regardless of mood, headlines, or how yesterday went.

**Tested before trusted.** Every rule was checked against years of real historical prices before ever running for real — replaying history and asking "if these exact rules had been running, what would have happened?" That's backtesting.

**One file controls everything.** The entire live system is `config/strategy_master.yaml`. Change a number in it and behavior changes — no programming required for most adjustments.

**Currently in a "watch, don't tune" phase.** After a long design process (see Section 4), the current config represents the durable, well-evidenced findings from that process — not every idea tried. Going forward, the plan is to let real paper results accumulate for months before making further changes, rather than continuing to search the same historical windows for marginal improvements. That's a deliberate methodology choice, not inactivity — see Section 12.

---

## 4. The watchlist, and how it got here

**Currently:** SPXL, TQQQ, SOXL, FAS, TNA, TECL, ERX — all ~3x daily-leveraged ETFs (S&P 500, Nasdaq-100, semiconductors, financials, small-caps, technology, and energy respectively).

**This started as crypto, and the pivot away from it is the single most important finding of the whole design process.** Crypto's backtested headline numbers looked spectacular (10,000%+ in the best windows) — but under closer inspection, that turned out to be mostly *beta* (just being exposed to a huge bull run) rather than durable strategy *skill*. Every defensive lever tried on crypto (trailing stops, tighter position caps, a rotation overlay, a choppiness filter) bought safety by giving up return, and crypto genuinely lost money over its most recent 12-month stretch with nothing found that fixed that without also gutting the windows that worked. Leveraged ETFs, tested the same rigorous way, showed real, mechanism-backed edge instead — see Section 12 for the actual numbers.

**The watchlist itself was widened deliberately, not just for its own sake:**
- Started at 3 tickers (SPXL/TQQQ/SOXL), widened to 6 (+FAS/TNA/TECL) — tested *without* a trailing stop first and it was a clear loss (ticker dilution, same lesson learned repeatedly this whole project). Only *with* the trailing stop does the wider basket pay off, and even then the 3-ticker version's return was dangerously concentrated in one ticker (SOXL, nearly the entire gain) — the 6-ticker version is a genuine diversification improvement, not just more names.
- **ERX (3x energy) was added after testing 5 candidates individually** — TMF (3x bonds), YINN (3x China), CURE (3x healthcare), DRN (3x real estate), all chosen specifically for having a genuinely *different* driver than the tech-heavy core. ERX was the only clean win: it improved 3 of 4 standard test windows, most dramatically the strategy's persistently weakest window, because energy genuinely moves differently from leveraged tech during a downturn. TMF was rejected after flipping a modest gain into an outright loss in that exact window — the classic "2022 broke the stock/bond hedge" risk, confirmed rather than assumed. CURE was worse on literally every metric tested. **Honest cost**: adding ERX didn't uniformly improve everything — it shifted the strategy's weakest window from 2020-2022 to 2023-2026 instead, which now has the deepest drawdown of the four.
- A plain gold (GLD) addition was also tested and rejected — it helped recent history but hurt older windows, traced to a real mechanism: gold's low volatility means the position-sizing math gives it an outsized dollar position relative to the leveraged tickers, unless specifically capped.

---

## 5. How it decides to BUY

Two conditions from `entry:`, both true the same day:

| Rule | Config value | Plain meaning |
|---|---|---|
| MA crossover | `ma_period: 20` | Price just crossed above its 20-day average |
| Volume confirmation | `volume_confirmation: true` | Today's volume is above its 20-day average |

### Real example — TECL, spring 2026

TECL's entry rule fired on 2026-04-30 at $146.13, and again on 2026-05-07 at $174.69 (a pyramid add — see Section 8). Both conditions were genuinely true both days: price had just crossed its 20-day average, and volume confirmed real buying interest, not noise.

**A finding worth knowing**: TECL's entry rule actually fired *correctly* six more times in the following weeks (5/8, 5/12, 5/18, 5/29, 6/1, 6/2) — but none of those were acted on, because the portfolio was pinned at its 80% capital ceiling from other tickers (SPXL, SOXL, TQQQ) riding the same rally simultaneously. The signal logic wasn't the problem; there was simply no capital left to deploy. This is a real, documented gap — see Section 10.

---

## 6. How much it buys — position sizing

Every trade is sized so that **if it hits its stop-loss, the loss costs a fixed, small slice of the account** — regardless of how volatile that particular ticker is. From `risk:`:

```
risk_pct_per_unit: 1.0       →  risk 1.0% of total account equity per trade
stop_atr_multiple: 1.5       →  stop-loss set 1.5× a volatility measure (N) from entry
```

**"N" (ATR)** is a rolling measure of a ticker's typical daily move. A choppier ticker has a bigger N, so the system automatically buys fewer shares of it — the dollar risk stays the same either way.

### Real example, continued (TECL)

- Entry price: $146.13, then $174.69 on the pyramid add
- Two ceilings apply on top regardless: no single position over **35%** of the account (`max_position_pct`), total invested never over **80%** (`max_invested_pct`)

---

## 7. How it decides to SELL — and what actually happens when it does

From `exit:`, checked every day a position is open. Two real trades from spring/summer 2026 tell both sides of this honestly.

### The win: TECL, April–May 2026

Bought at $146.13 and $174.69, the whole position exited together on 2026-05-12 at **$191.51** — **+31.05% and +9.63%** on the two units. The trailing stop did exactly its job: it locked in a large gain right before a sharp pullback that followed.

**A chart-reading note worth remembering**: on the price charts this project generates, a red "sell" marker means *a sell happened here* — it does not mean the trade lost money. This exact trade's sell marker sits well above both buy markers, because it was a big win, not a loss. Don't assume red = bad without checking the actual trade log.

### The loss: TQQQ, June 2026 — and how fast it happened

A 3-unit pyramid stack (entries at $75.17, $81.76, $83.49) was riding a real rally, up as much as 2.6R on the oldest unit by 2026-06-02. Then: **on 2026-06-3 the stock was still 3.3% above its trailing stop; by 6/4, still 1.6% above it — there was no visible weakness on either day.** Then it gapped down overnight and crashed intraday, closing 2026-06-05 at $72.88, well below the stop level. All three units exited that day: **-3.04%, -10.86%, -12.70%.**

The honest lesson: this wasn't the exit logic being slow. There was no signal to catch on 6/3 or 6/4 — the reversal was a genuine one-day violent move that jumped straight through the stop's buffer rather than grinding into it. The mechanism that *would* help here is one this project doesn't have yet: a live, resting stop-loss order at the broker, rather than a check that only happens once a day. See Section 10.

**A specific fix that was tested and rejected for this exact case**: uniformly tightening the trailing stop (to catch reversals like this sooner) was tested across all four historical windows and made results *worse* almost everywhere — it chops up far more ordinary trades than it saves from rare violent moves like this one. A narrower, profit-conditional version ("exit immediately on 2 down days once meaningfully profitable") was also built and tested — it fixed this exact TQQQ trade dramatically, but had almost no net effect once measured across everything else it also touched. Neither is currently active.

---

## 8. Pyramiding — growing a winning position

```
enabled: true
unit_interval_n: 0.5    →  add a unit every 0.5×N further in our favor
max_units: 4             →  cap the stack at 4 total units
```

A trade already proving itself right earns a bigger bet. When it's time to sell, the whole stack sells together — never partial exits.

**A real risk this surfaces**: the later, higher-priced units in a stack are consistently the most exposed to a sharp reversal, since they have the least room before the shared stop. TQQQ's worst-performing unit (-12.70%) was the third pyramid add, bought closest to the eventual top. Capping the stack at fewer units (tested at 2 instead of 4) removes this specific risk and improved 3 of 4 test windows — a real, evidence-backed candidate for a future change, not yet promoted.

---

## 9. The machinery — what runs, and when

- **Alpaca** — the brokerage. Currently a **paper account**: real prices, real order mechanics, fake money.
- **Supabase** — the database. Every signal, trade, and account snapshot is logged here.
- **GitHub Actions** — the automatic trigger, **weekdays at 20:30 UTC** (4:30pm ET, 30 minutes after market close) — back to equities market hours since the crypto pivot. *DST caveat*: this is a fixed UTC time, but market close is fixed in ET, and the gap between them shifts twice a year — once daylight saving ends (~early November), 20:30 UTC becomes 3:30pm ET, a half hour *before* the close instead of after. Worth revisiting the cron expression before that happens.
- **Manual runs** — can run any time; won't generate new trend signals faster (locked to daily, on purpose), but will catch a stop-loss breach sooner if run more often, since price checks use a live quote.

---

## 10. What's not resolved yet — honest open risks

- **No standing stop-loss order.** The stop is only checked when the program runs, once a day. TQQQ's June crash (Section 7) is a real, concrete example of what this costs: a violent overnight/intraday move can blow straight through the stop's buffer before it's ever checked.
- **A real capital-competition gap.** TECL's six missed entries (Section 5) show that when multiple tickers signal at once, the ones checked later in the day can lose out on capital entirely, even with a perfectly correct signal — the 80% investment cap is measured in *dollars*, not *risk*, so it can't tell a well-protected position from a loosely-stopped one when deciding what has "room." A risk-based capital cap (sometimes called portfolio heat, a concept straight from the Turtle trading rules this whole system is modeled on) would fix this directly; not built yet.
- **A real "chop tax."** A genuinely flat, sideways market (Nov 2025–Jan 2026, in earlier testing) produced dozens of small stop-losses with almost no net gain — the unavoidable cost of a trend-following system when there's no trend to follow. A purpose-built filter for this was tested and rejected; it blocked too many good trades along with the bad ones.
- **Overfitting risk from the design process itself.** A long list of parameters (both stop multiples, watchlist composition, entry period, pyramid caps, risk-per-unit, and more) were all tuned against the *same* four historical windows, repeatedly. The big, clean wins (tightened stops, ERX) are trustworthy — they were large, consistent across every window, and had a real causal story. The smaller, more marginal experiments were deliberately *not* promoted into this config, specifically to avoid over-fitting to that fixed history. See Section 12.
- **The live track record is essentially empty.** As of this writing, the current watchlist has had zero real trades — the pivot to leveraged ETFs happened on a weekend, and no scheduled weekday run had fired yet by the time this was written. Nothing about real forward performance can be said until that changes.
- **2020-2022 and 2023-2026 remain real weak points.** Even after every improvement found this session, 2020-2022 is still the weakest of the four standard test windows, and 2023-2026 (after ERX) now carries the deepest drawdown of the four (-35.93%).

None of this means the system is broken. It means: the plumbing works, the biggest known issues are documented rather than hidden, and what's genuinely unproven is whether any of this holds up on markets it hasn't seen yet — which is exactly what the current "watch, don't tune" phase exists to find out.

---

## 11. How we judge "is this actually good"

The old crypto-era version of this guide leaned heavily on the System Quality Number (SQN). For leveraged ETFs, three different metrics do more of the real work:

**Calmar ratio** = annualized return ÷ worst drawdown. "How much return per unit of worst-case pain." Current config: **0.93** (2019-2024), **0.92** (2020-2022), **0.80** (2023-2026), **4.66** (last 12 months).

**Sortino ratio** = annualized return ÷ typical downside severity, ignoring upside entirely (a huge win never counts against it, unlike a plain volatility measure). Has real external benchmarks: below 1 weak, 1-2 good, 2-3 very good, above 3 excellent. Current config: **1.25, 0.90, 1.53, 3.03** across the same four windows — solidly "good" to "excellent."

**Alpha vs. SPY** — the most important one for the actual question that matters: is the extra risk being taken here *actually* worth it, compared to simply owning the S&P 500? Alpha is the annualized return left over *after* accounting for how much extra market exposure (beta) this strategy carries. Current config: **+12.5, +9.9, +5.7, +33.6** — positive in every tested window, meaning yes, by this measure, the strategy is adding real value beyond just being a leveraged bet on the market, not merely riding extra beta the way the old crypto version mostly was.

---

## 12. The goals that now govern every decision

Settled explicitly during this design process, and the actual bar for judging anything from here forward:

- **More risk than plain buy-and-hold (SPY) is fine — but only if it's genuinely compensated, risk-adjusted.** Not just a higher raw-return number; Calmar, Sortino, and alpha vs. SPY have to actually improve, or the extra risk isn't earning its keep.
- **A personal drawdown ceiling of 15-30%** — elastic upward if the system is demonstrably earning real, risk-adjusted edge, not a hard wall on its own.
- **A 1-2 year judgment horizon.** Not weeks, not the first bad trade.
- **This represents a small, side-experiment allocation** — money fully prepared to be lost entirely without affecting anything else, in service of learning whether a systematic approach can actually work.

---

## 13. Where things honestly stand right now

**What's solid:** the mechanism (entries, ATR sizing, pyramiding, trailing stops) is well-tested across multiple historical windows, and the two big changes live in the current config (tightened stops, adding ERX) were both large, clean, mechanism-backed wins — not marginal parameter-search artifacts.

**What's genuinely unproven:** whether any of this holds up on real, unseen market conditions. The live track record is essentially zero. Two of the four backtested windows remain real, acknowledged weak points. Several smaller, evidence-mixed improvements (tighter pyramid caps, a different entry period, higher risk-per-unit) were found but deliberately left out, specifically to avoid compounding overfitting risk on top of an already heavily-tuned config.

**The plan from here**: stop tuning against the same backtested history, let the paper account actually run for a real stretch, and treat that — not another round of parameter search — as the next real source of insight.

---

## 14. Glossary

- **Backtest** — simulating against historical prices, no real money
- **Paper trading** — real-time, real broker, fake money
- **Signal** — a computed BUY/SELL trigger for a ticker on a given day
- **Position** — a currently-held (open) trade; a **stack** if pyramided
- **Stop-loss** — automatic sell if a position falls too far
- **Trailing stop** — a stop that rises as a winning position's peak price rises, locking in more gain over time
- **Trend exit** — sell triggered by the trend reversing (a new 10-day low)
- **N / ATR** — rolling measure of a ticker's typical move; sizes positions and stops
- **Pyramiding** — adding to an already-winning position
- **R-multiple** — profit/loss as a multiple of what was risked ("+3R" = 3× the risk)
- **Calmar ratio** — annualized return ÷ worst drawdown
- **Sortino ratio** — annualized return ÷ downside-only volatility
- **Alpha** — excess return beyond what's explained by extra market exposure (beta)
- **Beta** — how much a strategy's daily moves track the broader market's
- **Drawdown** — decline from a peak account value; *max drawdown* is the worst one
- **Market impact / spread** — real trading costs from crossing the bid-ask spread and moving the market with a large order; modeled as optional, off by default at this project's current small scale

---

## 15. How to explain this to someone else

**10 seconds:** "It's a rules-based trading program for leveraged ETFs, currently running with fake money to prove itself before we'd ever consider real money."

**1 minute:** "We built a computer program that watches seven leveraged ETFs and buys or sells based on fixed, tested rules — never a gut call. It only risks a small, fixed percentage of the account on any one trade, and it started out on crypto before we found that edge was mostly just riding a bull market, not real skill — so we moved to something that actually beats simple index investing after accounting for the extra risk. It's running on a real brokerage account right now, but with fake money, so we can watch it handle real conditions before deciding whether it's earned the right to use real money."

**5 minutes:** Sections 5 through 8 above, using the real TECL win and TQQQ loss as the walkthrough — how it decides to buy, how much, and both ways a trade can actually end.
