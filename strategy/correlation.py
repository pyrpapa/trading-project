"""
Correlation-based circuit breaker -- a portfolio-level risk check on top
of the existing per-position sizing (N/ATR-based or flat %) and stop-loss
logic. Nothing here changes how BIG a single position is; it changes
whether a NEW position is allowed to open at all, based on how correlated
it already is with what's currently held.

Way of the Turtle's own version of this was simple hard-coded unit caps
per correlated market group (e.g. "at most 6 units across a closely
correlated group of currencies"). This implementation computes actual
rolling correlation from price history instead of hand-assigned groups,
so it adapts automatically as the watchlist changes -- including once
the portfolio selection algorithm (still unbuilt) starts choosing
tickers dynamically instead of the current static SPY/AAPL/MSFT list.

Config (risk.correlation_breaker in strategy YAML):
    enabled: true
    lookback_period: 60          # trading days of returns used to compute correlation
    correlation_threshold: 0.7   # Pearson correlation at/above this counts as "correlated"
    max_correlated_positions: 2  # how many ALREADY-OPEN correlated positions
                                  # trip the breaker for a NEW entry (see
                                  # correlated_position_count below)
"""
import pandas as pd


def trailing_correlation(price_data: dict, ticker_a: str, ticker_b: str, date, lookback: int):
    """
    Pearson correlation between ticker_a's and ticker_b's daily returns,
    computed over the `lookback` trading days up to and including `date`.

    Returns None if either ticker doesn't have `date` in its price history,
    or doesn't have enough trailing history yet to compute a reliable
    number -- callers should treat None as "not enough data to judge,
    don't block the trade", the same fail-open behavior N-based sizing
    already uses when ATR isn't available yet (see backtest/engine.py).
    """
    df_a = price_data.get(ticker_a)
    df_b = price_data.get(ticker_b)
    if df_a is None or df_b is None:
        return None
    if date not in df_a.index or date not in df_b.index:
        return None

    idx_a = df_a.index.get_loc(date)
    idx_b = df_b.index.get_loc(date)
    if idx_a < lookback or idx_b < lookback:
        return None  # not enough trailing history yet for either ticker

    returns_a = df_a["Close"].iloc[idx_a - lookback: idx_a + 1].pct_change().dropna()
    returns_b = df_b["Close"].iloc[idx_b - lookback: idx_b + 1].pct_change().dropna()

    aligned = pd.concat([returns_a, returns_b], axis=1, join="inner")
    aligned.columns = ["a", "b"]
    if len(aligned) < lookback // 2:
        return None  # not enough overlapping history to trust the number

    corr = aligned["a"].corr(aligned["b"])
    return float(corr) if pd.notna(corr) else None


def correlated_position_count(candidate_ticker: str, open_tickers, price_data: dict, date, lookback: int, threshold: float) -> int:
    """
    Counts how many currently-open positions have trailing correlation
    >= threshold with candidate_ticker as of `date`. Pairs where
    trailing_correlation() can't compute a number (not enough shared
    history yet) don't count against the candidate -- fails open, not closed.
    """
    count = 0
    for other in open_tickers:
        if other == candidate_ticker:
            continue
        corr = trailing_correlation(price_data, candidate_ticker, other, date, lookback)
        if corr is not None and corr >= threshold:
            count += 1
    return count


def breaker_reason(candidate_ticker: str, corr_count: int, threshold: float, max_correlated: int) -> str:
    """Plain-English reason text for the trade journal (see strategy/journal.py)."""
    return (
        f"{corr_count} already-open position(s) are correlated {threshold:.2f}+ "
        f"with {candidate_ticker} (circuit breaker cap: {max_correlated})"
    )
