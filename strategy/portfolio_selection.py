"""
Portfolio selection -- the third pillar of "system edge" alongside
entries and exits (Way of the Turtle's own framing: portfolio selection
+ entry signals + exit signals). Chooses WHICH markets from a larger
candidate pool are actually tradable right now, instead of trading a
fixed, hand-picked watchlist forever.

This is a direct response to the circuit breaker result: blocking
trades AFTER the fact because two open positions turned out to be
correlated cost more than it protected (see PROJECT_STATUS.md).
Portfolio selection attacks the same problem earlier -- by choosing a
genuinely less-correlated set of markets to trade in the first place,
instead of policing an already-correlated static list.

Two-stage process, recomputed periodically (see backtest/engine.py's
rebalance loop, or live/run_live.py which recomputes fresh every run)
using only TRAILING data as of the selection date -- no lookahead:

  1. Liquidity filter: drop any candidate whose trailing average
     DOLLAR volume (price * volume, not raw share count -- comparable
     across tickers at very different price levels) is below
     min_avg_dollar_volume. Avoids ending up holding something too
     thin to trade cleanly.
  2. Greedy diversification: seed with the most liquid surviving
     candidate, then repeatedly add whichever remaining candidate has
     the LOWEST average correlation to everything already selected,
     until target_size is reached (or candidates run out).

Config (see config/strategy_v7_portfolio_selection.yaml):
    portfolio_selection:
      enabled: true
      candidate_universe: [SPY, AAPL, MSFT, ...]
      target_size: 3
      min_avg_dollar_volume: 20000000
      lookback_period: 90
      rebalance_frequency_months: 3
"""
from strategy.correlation import trailing_correlation


def universe_tickers(cfg: dict) -> list:
    """
    The full set of tickers a strategy needs price history for: the
    candidate_universe when portfolio_selection is enabled, otherwise
    the plain watchlist (v1-v6 behavior, unchanged). Callers that need
    to know "what should I fetch / what am I allowed to ever trade"
    should use this instead of reading cfg["watchlist"] directly.
    """
    ps_cfg = cfg.get("portfolio_selection") or {}
    if ps_cfg.get("enabled"):
        return ps_cfg["candidate_universe"]
    return cfg.get("watchlist", [])


def _avg_dollar_volume(ticker: str, price_data: dict, date, lookback: int):
    df = price_data[ticker]
    idx = df.index.get_loc(date)
    window = df.iloc[max(0, idx - lookback): idx + 1]
    value = (window["Close"] * window["Volume"]).mean()
    return float(value) if value == value else 0.0  # NaN guard without importing pandas/numpy here


def liquidity_filter(candidates, price_data: dict, date, lookback: int, min_avg_dollar_volume: float) -> list:
    """
    Returns the subset of `candidates` with enough trailing average
    dollar volume AND enough trailing history to judge it. Candidates
    without enough history yet are excluded (fails closed, not open --
    unlike the circuit breaker, picking a market to trade with
    insufficient data is a worse mistake than temporarily under-filling
    the portfolio).
    """
    eligible = []
    for ticker in candidates:
        df = price_data.get(ticker)
        if df is None or date not in df.index:
            continue
        idx = df.index.get_loc(date)
        if idx < lookback:
            continue
        if _avg_dollar_volume(ticker, price_data, date, lookback) >= min_avg_dollar_volume:
            eligible.append(ticker)
    return eligible


def select_diversified_subset(candidates, price_data: dict, date, lookback: int, target_size: int) -> list:
    """
    Greedy minimum-average-correlation selection. Returns up to
    target_size tickers from `candidates`, picked to be as mutually
    UNcorrelated as possible using trailing_correlation() -- the same
    function the circuit breaker uses, so "correlated" means the same
    thing in both places.

    Seeded with the most liquid candidate (by trailing dollar volume)
    -- arbitrary but deterministic, and a reasonable "core holding"
    starting point. Each subsequent slot goes to whichever remaining
    candidate has the lowest average correlation to everything already
    selected so far (pairs with no computable correlation yet -- not
    enough shared history -- are treated as correlation 0, i.e. don't
    penalize a candidate just because it's harder to measure).
    """
    if not candidates:
        return []

    remaining = list(candidates)
    remaining.sort(key=lambda t: _avg_dollar_volume(t, price_data, date, lookback), reverse=True)
    selected = [remaining.pop(0)]

    while remaining and len(selected) < target_size:
        best_ticker = None
        best_avg_corr = None
        for candidate in remaining:
            corrs = [
                trailing_correlation(price_data, candidate, s, date, lookback)
                for s in selected
            ]
            corrs = [c for c in corrs if c is not None]
            avg_corr = (sum(corrs) / len(corrs)) if corrs else 0.0
            if best_avg_corr is None or avg_corr < best_avg_corr:
                best_avg_corr = avg_corr
                best_ticker = candidate
        selected.append(best_ticker)
        remaining.remove(best_ticker)

    return selected


def select_portfolio(candidates, price_data: dict, date, lookback: int, min_avg_dollar_volume: float, target_size: int) -> list:
    """One call: liquidity filter, then diversified selection."""
    eligible = liquidity_filter(candidates, price_data, date, lookback, min_avg_dollar_volume)
    return select_diversified_subset(eligible, price_data, date, lookback, target_size)
