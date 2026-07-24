"""
Generates realistic-ish synthetic price data for offline testing of the
strategy/backtester logic, since this sandbox can't reach Yahoo Finance.

This is ONLY for testing that the code works. Real decisions must use
real historical data via fetcher.py, run on your own machine.
"""
import numpy as np
import pandas as pd


def generate(ticker_seed: int, start: str, end: str, start_price: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(ticker_seed)
    dates = pd.bdate_range(start=start, end=end)
    n = len(dates)

    # Random walk with slight upward drift, occasional volatility regimes
    daily_returns = rng.normal(loc=0.0003, scale=0.012, size=n)
    # inject a couple of drawdown periods to make backtest metrics meaningful
    if n > 300:
        daily_returns[100:140] -= 0.01
        daily_returns[400:430] -= 0.015 if n > 430 else 0

    price = start_price * np.cumprod(1 + daily_returns)
    close = price
    open_ = close * (1 + rng.normal(0, 0.002, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    # occasional volume spikes
    spike_idx = rng.choice(n, size=max(1, n // 40), replace=False)
    volume[spike_idx] *= rng.uniform(1.5, 3.0, size=len(spike_idx))

    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )
    return df


def generate_watchlist(tickers: list, start: str, end: str) -> dict:
    return {t: generate(seed, start, end, start_price=50 + seed * 30) for seed, t in enumerate(tickers, start=1)}
