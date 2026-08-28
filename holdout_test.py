"""
Tests candidate tickers OUTSIDE the live watchlist against the exact same,
UNMODIFIED strategy rules (config/strategy_master.yaml) -- a genuine
out-of-sample check for "does this strategy's edge generalize beyond the
hand-picked live tickers," not a search for what to add to the watchlist
next. These candidates are never traded live by this script -- backtest
only.

For each candidate, for each of the 4 standard windows this project
already validates everything else against (see parameter_sweep.py), runs
the SAME baseline watchlist backtest (computed once per window, reused
across every candidate) and a second backtest with just that one
candidate added -- mirroring exactly how ERX/TMF/YINN/DRN/CURE/GLD were
each evaluated before being added to (or rejected from) the live config
(see config/strategy_master.yaml's own header for that history). Flags
any candidate whose ADDITION improves Calmar AND Sortino in at least 3 of
the 4 windows -- the same "not just the best window" discipline used
everywhere else in this project, not a single-window cherry-pick.

The candidate list is chosen for asset-class/structural reasons (a
deliberately different flavor from the live watchlist's all-3x-leveraged-
equity-ETF makeup: unleveraged bonds, metals, commodities, REITs,
international equities), NOT because they were pre-screened by
backtesting -- picking candidates based on how they already backtest
would defeat the entire point of a holdout set.

GLD is deliberately EXCLUDED even though it fits the "traditional asset"
theme: it was already tested (and rejected) for this exact live config,
see config/strategy_v38_add_gold*.yaml / config/strategy_v39_gold_capped*.yaml
-- including it here would not be a blind test, just a re-confirmation.

Usage:
    python holdout_test.py                       # full candidate list, real data
    python holdout_test.py --tickers TLT,SLV      # subset
    python holdout_test.py --synthetic            # offline test data

Writes results/holdout-test/holdout_results.csv (baseline vs. with-
candidate metrics for every ticker x window) and prints a FLAG line for
any candidate that clears the bar.
"""
import sys
import os
import copy
import csv
import datetime as dt
import yaml

sys.path.insert(0, os.path.dirname(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from data import fetcher
from strategy import rules, portfolio_selection
from backtest import engine

BASE_CONFIG_PATH = "config/strategy_master.yaml"
OUT_DIR = os.path.join("results", "holdout-test")

# Same 4 standard windows used throughout this project (parameter_sweep.py,
# the ERX/TMF/YINN/DRN/CURE/GLD candidate writeups in strategy_master.yaml)
# -- kept identical so results here are directly comparable to those.
WINDOWS = {
    "2019-2024": ("2019-01-01", "2024-12-31"),
    "2020-2022-crisis": ("2020-06-01", "2022-12-31"),
    "2023-2026-crisis": ("2023-01-01", "2026-08-09"),
    "last-12mo": ("2025-08-15", "2026-08-15"),
}
WARMUP_DAYS = (250 + 30) * 2  # same generous fixed warm-up pattern as parameter_sweep.py

# Traditional / lower-volatility asset classes, deliberately DIFFERENT in
# kind from the live watchlist (which is all 3x-leveraged equity ETFs) --
# picked for asset-class diversity, not backtested performance. None of
# these have been tested against this config before (see module docstring
# re: GLD's deliberate exclusion).
HOLDOUT_TICKERS = [
    "TLT",  # 20+yr Treasury bonds, unleveraged -- TMF is this same exposure at 3x, already tested/rejected
    "AGG",  # broad aggregate bond market, lower volatility than TLT alone
    "SLV",  # silver
    "DBC",  # broad commodities index
    "VNQ",  # REITs, unleveraged -- DRN is this same exposure at 3x, already tested/rejected
    "VEA",  # developed-market international equities
]

# Only these two drive the FLAG decision (both must improve in >=3/4
# windows) -- return alone is too easy to game with more leverage/risk,
# and this project's own settled goal is risk-adjusted outperformance,
# not raw return (see project goals: Calmar/Sortino/alpha vs SPY, not
# headline return alone).
FLAG_METRICS = ["calmar_ratio", "sortino_ratio"]
FLAG_MIN_WINDOWS = 3  # out of len(WINDOWS) == 4

METRIC_COLUMNS = [
    "total_return_pct", "annualized_return_pct", "max_drawdown_pct",
    "calmar_ratio", "sortino_ratio", "beta", "alpha_pct",
    "system_quality_number", "win_rate_pct", "n_trades",
    "avg_r_multiple", "longest_losing_streak",
]


def fetch_window_data(tickers: list, start: str, end: str, use_synthetic: bool) -> dict:
    fetch_start = (dt.date.fromisoformat(start) - dt.timedelta(days=WARMUP_DAYS)).isoformat()
    if use_synthetic:
        from data import synthetic
        return synthetic.generate_watchlist(tickers, fetch_start, end)
    return fetcher.fetch_watchlist(tickers, fetch_start, end)


def run_one(cfg: dict, price_data: dict, start: str, end: str, benchmark_returns=None) -> dict:
    cfg = copy.deepcopy(cfg)
    cfg["backtest"]["start_date"] = start
    cfg["backtest"]["end_date"] = end
    signals = {t: rules.generate_signals(df, cfg) for t, df in price_data.items()}
    result = engine.run_backtest(price_data, signals, cfg, benchmark_returns=benchmark_returns)
    return result["metrics"]


def main():
    use_synthetic = "--synthetic" in sys.argv
    candidates = HOLDOUT_TICKERS
    if "--tickers" in sys.argv:
        idx = sys.argv.index("--tickers")
        if idx + 1 < len(sys.argv):
            candidates = sys.argv[idx + 1].split(",")

    with open(BASE_CONFIG_PATH) as f:
        base_cfg = yaml.safe_load(f)
    base_tickers = portfolio_selection.universe_tickers(base_cfg)

    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"Baseline (live) watchlist: {base_tickers}")
    print(f"Holdout candidate(s): {candidates}")
    print(f"Fetching baseline price data for {len(WINDOWS)} window(s)...")

    baseline_metrics = {}
    window_benchmark = {}
    window_base_data = {}
    for window_name, (start, end) in WINDOWS.items():
        print(f"  {window_name}: {start} to {end}")
        window_base_data[window_name] = fetch_window_data(base_tickers, start, end, use_synthetic)
        window_benchmark[window_name] = None
        if not use_synthetic:
            try:
                fetch_start = (dt.date.fromisoformat(start) - dt.timedelta(days=WARMUP_DAYS)).isoformat()
                spy_df = fetcher.fetch("SPY", fetch_start, end)
                window_benchmark[window_name] = spy_df.loc[start:end, "Close"].pct_change().dropna()
            except Exception as e:
                print(f"    Note: SPY benchmark fetch failed for {window_name} ({e}) -- beta/alpha will be None.")
        baseline_metrics[window_name] = run_one(
            base_cfg, window_base_data[window_name], start, end, window_benchmark[window_name]
        )

    print("\n=== BASELINE (live watchlist, config unmodified) ===")
    for window_name in WINDOWS:
        m = baseline_metrics[window_name]
        print(f"  [{window_name:>16}]  return={m.get('total_return_pct')}%  DD={m.get('max_drawdown_pct')}%  "
              f"calmar={m.get('calmar_ratio')}  sortino={m.get('sortino_ratio')}  alpha={m.get('alpha_pct')}")

    all_rows = []
    flagged = []
    for ticker in candidates:
        print(f"\n=== {ticker} ===")
        wins = {m: 0 for m in FLAG_METRICS}
        windows_compared = 0
        for window_name, (start, end) in WINDOWS.items():
            try:
                candidate_data = fetch_window_data([ticker], start, end, use_synthetic)
                candidate_df = candidate_data[ticker]
                if candidate_df is None or candidate_df.empty:
                    raise RuntimeError("no data returned")
            except Exception as e:
                print(f"  [{window_name:>16}]  SKIPPED -- {ticker} data unavailable ({e})")
                continue

            combined_data = dict(window_base_data[window_name])
            combined_data[ticker] = candidate_df
            with_metrics = run_one(base_cfg, combined_data, start, end, window_benchmark[window_name])
            base_m = baseline_metrics[window_name]
            windows_compared += 1

            row = {"ticker": ticker, "window": window_name}
            for col in METRIC_COLUMNS:
                row[f"baseline_{col}"] = base_m.get(col)
                row[f"with_candidate_{col}"] = with_metrics.get(col)
            all_rows.append(row)

            deltas = []
            for m in FLAG_METRICS:
                b, w = base_m.get(m), with_metrics.get(m)
                improved = b is not None and w is not None and w > b
                if improved:
                    wins[m] += 1
                deltas.append(f"{m}: {b} -> {w}{'  UP' if improved else ''}")
            print(f"  [{window_name:>16}]  " + "   ".join(deltas))

        if windows_compared == 0:
            print(f"  {ticker}: no usable data in any window, skipping flag check")
            continue

        if all(wins[m] >= FLAG_MIN_WINDOWS for m in FLAG_METRICS):
            flagged.append(ticker)
            print(f"  >>> FLAG: {ticker} improved {' and '.join(FLAG_METRICS)} "
                  f"in >= {FLAG_MIN_WINDOWS}/{len(WINDOWS)} windows -- worth a closer look")

    if all_rows:
        out_path = os.path.join(OUT_DIR, "holdout_results.csv")
        fieldnames = (["ticker", "window"]
                      + [f"baseline_{c}" for c in METRIC_COLUMNS]
                      + [f"with_candidate_{c}" for c in METRIC_COLUMNS])
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\nWrote {out_path}")

    print("\n=== SUMMARY ===")
    if flagged:
        print(f"Flagged candidate(s) worth a closer look: {flagged}")
        print("Reminder: a flag here is backtest-only evidence, same caveats as any other "
              "backtest in this project -- it should go through the same live/paper validation "
              "as every other config change before being trusted, not get fast-tracked to the "
              "live watchlist off this result alone.")
    else:
        print(f"No candidate cleared the >= {FLAG_MIN_WINDOWS}/{len(WINDOWS)}-window bar this run.")


if __name__ == "__main__":
    main()
