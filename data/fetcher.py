"""
Fetches historical price data for backtesting.

Real data source: yfinance (free, no API key needed).
Results are cached to CSV in data/cache/ so repeated backtests don't
re-download, and so the strategy can be tested offline once cached.

Run this file directly on a machine with internet access to populate
the cache: `python fetcher.py`
"""
import os
import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")


def _cache_path(ticker: str, namespace: str = "default") -> str:
    subdir = os.path.join(CACHE_DIR, namespace)
    os.makedirs(subdir, exist_ok=True)
    return os.path.join(subdir, f"{ticker}.csv")


def fetch(ticker: str, start: str, end: str, force_refresh: bool = False, namespace: str = "default") -> pd.DataFrame:
    """
    Returns a DataFrame with columns: Open, High, Low, Close, Volume
    indexed by date, for the given ticker and date range.

    `namespace` keeps caches separate for different use cases (e.g. a
    long backtest history cache vs. a short rolling live-check cache)
    so one doesn't overwrite the other.

    The cache is only used if it actually covers the requested date
    range — a cache built for 2019-2024 won't be silently reused (and
    silently sliced to empty) for a 2012-2018 request. It refetches
    automatically if the cached range doesn't cover what's asked for.
    """
    path = _cache_path(ticker, namespace)

    if not force_refresh and os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        cache_covers_range = (
            not df.empty
            and df.index.min() <= pd.Timestamp(start)
            and df.index.max() >= pd.Timestamp(end)
        )
        if cache_covers_range:
            return df.loc[start:end]
        # else: fall through and refetch — cache exists but doesn't cover this range

    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError(
            "yfinance is not installed. Run: pip install yfinance\n"
            "(This sandbox has no internet access to Yahoo Finance — "
            "run this on your own machine to fetch real data.)"
        )

    df = yf.download(ticker, start=start, end=end, progress=False)
    if df.empty:
        raise RuntimeError(f"No data returned for {ticker}. Check the ticker symbol.")

    # yfinance sometimes returns multi-index columns (e.g. ('Close', 'AAPL'))
    # even for a single ticker, depending on version; flatten if so.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Keep only the columns the rest of the codebase expects, in a
    # consistent order.
    keep_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep_cols]

    df.to_csv(path)

    return df.loc[start:end]


def fetch_watchlist(tickers: list, start: str, end: str, namespace: str = "default") -> dict:
    """
    Fetches price data for every ticker in a watchlist. Returns
    {ticker: DataFrame}. Uses fetch() per ticker under the hood, so
    caching behavior is identical to fetching a single ticker.
    """
    return {ticker: fetch(ticker, start, end, namespace=namespace) for ticker in tickers}


if __name__ == "__main__":
    # Populate the cache for a reasonable default range when run directly,
    # e.g.: python data/fetcher.py
    import yaml

    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "strategy.yaml")
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    tickers = cfg["watchlist"]
    start = cfg["backtest"]["start_date"]
    end = cfg["backtest"]["end_date"]

    print(f"Fetching {tickers} from {start} to {end}...")
    for ticker in tickers:
        df = fetch(ticker, start, end, force_refresh=True)
        print(f"  {ticker}: {len(df)} rows cached")