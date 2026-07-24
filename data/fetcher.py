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
    """
    path = _cache_path(ticker, namespace)

    if not force_refresh and os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df.loc[start:end]

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

    # yfinance sometimes returns multi-index columns; flatten if so
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close", "Volume"]]
    df.to_csv(path)
    return df.loc[start:end]


def fetch_watchlist(tickers: list, start: str, end: str) -> dict:
    """Returns {ticker: DataFrame} for every ticker in the watchlist."""
    return {t: fetch(t, start, end) for t in tickers}


if __name__ == "__main__":
    # Manual run: populate the cache for the default watchlist
    import yaml
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "strategy.yaml")
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    for ticker in cfg["watchlist"]:
        print(f"Fetching {ticker}...")
        df = fetch(ticker, cfg["backtest"]["start_date"], cfg["backtest"]["end_date"], force_refresh=True)
        print(f"  {len(df)} rows cached to {_cache_path(ticker, 'default')}")
