"""
Sweeps every tunable parameter in config/strategy_master.yaml one at a time
(holding everything else at its current live-config value), against the same
three historical windows the project's other multi-window validations use
(see config/strategy_master.yaml's header):

    2019-2024       calm/bull, plus BTC's own 2017-2019-adjacent warm-up
    2020-2022-crisis  Terra/FTX crash window
    2023-2026-crisis  the most recent, most sobering window (ATH -> June 2026 crash)

For each (parameter, test value, window) combination: deep-copies the base
config, overrides just that one key, runs the exact same
fetch -> generate_signals -> engine.run_backtest pipeline run_backtest.py
uses, and records the resulting metrics. Price data is fetched ONCE per
window (with a lookback buffer generous enough to cover every value being
tested for every parameter) and reused across all parameter variants for
that window -- only the config changes per run, not the underlying data.

Usage:
    python parameter_sweep.py                  # full sweep, real data
    python parameter_sweep.py --params ma_period,risk_pct_per_unit  # subset

Writes one CSV per parameter plus a combined CSV into results/parameter-sweep/.
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
OUT_DIR = os.path.join("results", "parameter-sweep")

WINDOWS = {
    "2019-2024": ("2019-01-01", "2024-12-31"),
    "2020-2022-crisis": ("2020-06-01", "2022-12-31"),
    "2023-2026-crisis": ("2023-01-01", "2026-08-09"),
    "last-12mo": ("2025-08-15", "2026-08-15"),
}

# Generous fixed warm-up so ONE fetch per window covers every parameter
# value tested below (largest regime_filter_period candidate is 250 days;
# +30 slack same as run_backtest.py's own lookback_days pattern, doubled
# for weekends/holidays same as run_backtest.py).
WARMUP_DAYS = (250 + 30) * 2

# (section, key): list of values to test. Baseline (current live-config)
# value is included in each list so it always appears as a reference row.
PARAM_GRID = {
    "ma_period": ("entry", "ma_period", [10, 15, 20, 30, 40]),
    "volume_confirmation": ("entry", "volume_confirmation", [True, False]),
    "volume_ma_period": ("entry", "volume_ma_period", [10, 20, 30]),
    "regime_filter_period": ("entry", "regime_filter_period", [0, 100, 150, 200, 250]),
    "ma_exit": ("exit", "ma_exit", [True, False]),
    "exit_breakout_period": ("exit", "exit_breakout_period", [5, 10, 15, 20]),
    "stop_loss_pct": ("exit", "stop_loss_pct", [4.0, 8.0, 12.0]),
    "take_profit_pct": ("exit", "take_profit_pct", [None, 10.0, 20.0, 30.0]),
    "atr_period": ("risk", "atr_period", [10, 20, 30, 40]),
    "risk_pct_per_unit": ("risk", "risk_pct_per_unit", [1.0, 1.5, 2.0, 2.5, 3.0]),
    "stop_atr_multiple": ("risk", "stop_atr_multiple", [1.5, 2.0, 2.5, 3.0]),
    "max_position_pct": ("risk", "max_position_pct", [20.0, 35.0, 50.0]),
    "max_invested_pct": ("risk", "max_invested_pct", [60.0, 80.0, 100.0]),
    "pyramiding_enabled": ("risk.pyramiding", "enabled", [True, False]),
    "pyramiding_unit_interval_n": ("risk.pyramiding", "unit_interval_n", [0.25, 0.5, 1.0]),
    "pyramiding_max_units": ("risk.pyramiding", "max_units", [2, 4, 6]),
    "trailing_stop_atr_multiple": ("risk.trailing_stop", "atr_multiple", [1.0, 1.5, 2.0, 2.5, 3.0]),
}

METRIC_COLUMNS = [
    "total_return_pct", "annualized_return_pct", "max_drawdown_pct",
    "calmar_ratio", "sortino_ratio", "beta", "alpha_pct",
    "system_quality_number", "win_rate_pct", "n_trades",
    "avg_r_multiple", "longest_losing_streak",
]


def set_nested(cfg: dict, section: str, key: str, value):
    """section may be 'risk' or a dotted path like 'risk.pyramiding'."""
    node = cfg
    for part in section.split("."):
        node = node[part]
    node[key] = value


def fetch_window_data(base_cfg: dict, tickers: list, start: str, end: str, use_synthetic: bool):
    fetch_start = (dt.date.fromisoformat(start) - dt.timedelta(days=WARMUP_DAYS)).isoformat()
    if use_synthetic:
        from data import synthetic
        return fetcher_result_or_synthetic(synthetic.generate_watchlist(tickers, fetch_start, end))
    return fetcher.fetch_watchlist(tickers, fetch_start, end)


def fetcher_result_or_synthetic(data):
    return data


def run_one(cfg: dict, price_data: dict, start: str, end: str, benchmark_returns=None) -> dict:
    cfg = copy.deepcopy(cfg)
    cfg["backtest"]["start_date"] = start
    cfg["backtest"]["end_date"] = end
    signals = {t: rules.generate_signals(df, cfg) for t, df in price_data.items()}
    result = engine.run_backtest(price_data, signals, cfg, benchmark_returns=benchmark_returns)
    return result["metrics"]


def main():
    use_synthetic = "--synthetic" in sys.argv
    only_params = None
    if "--params" in sys.argv:
        idx = sys.argv.index("--params")
        if idx + 1 < len(sys.argv):
            only_params = set(sys.argv[idx + 1].split(","))

    with open(BASE_CONFIG_PATH) as f:
        base_cfg = yaml.safe_load(f)
    tickers = portfolio_selection.universe_tickers(base_cfg)

    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"Fetching price data for {len(WINDOWS)} window(s), {len(tickers)} tickers, "
          f"{WARMUP_DAYS}-day warm-up buffer each...")
    window_data = {}
    window_benchmark = {}
    for window_name, (start, end) in WINDOWS.items():
        print(f"  {window_name}: {start} to {end}")
        window_data[window_name] = fetch_window_data(base_cfg, tickers, start, end, use_synthetic)
        # SPY benchmark for metrics["beta"]/["alpha_pct"] -- see run_backtest.py
        # for the same pattern. Skipped for synthetic data; fails open on
        # any fetch error (beta/alpha just come back None for that window).
        window_benchmark[window_name] = None
        if not use_synthetic:
            try:
                fetch_start = (dt.date.fromisoformat(start) - dt.timedelta(days=WARMUP_DAYS)).isoformat()
                spy_df = fetcher.fetch("SPY", fetch_start, end)
                window_benchmark[window_name] = spy_df.loc[start:end, "Close"].pct_change().dropna()
            except Exception as e:
                print(f"    Note: SPY benchmark fetch failed for {window_name} ({e}) — beta/alpha will be None.")

    params_to_run = {
        name: spec for name, spec in PARAM_GRID.items()
        if only_params is None or name in only_params
    }

    all_rows = []
    for param_name, (section, key, values) in params_to_run.items():
        print(f"\n=== Sweeping {param_name} ({section}.{key}) -- {len(values)} value(s) x {len(WINDOWS)} window(s) ===")
        param_rows = []
        for value in values:
            cfg = copy.deepcopy(base_cfg)
            set_nested(cfg, section, key, value)
            for window_name, (start, end) in WINDOWS.items():
                metrics = run_one(cfg, window_data[window_name], start, end, benchmark_returns=window_benchmark[window_name])
                row = {
                    "parameter": param_name,
                    "value": value,
                    "window": window_name,
                }
                for col in METRIC_COLUMNS:
                    row[col] = metrics.get(col)
                param_rows.append(row)
                all_rows.append(row)
                print(f"  {key}={value!r:>8} [{window_name:>16}]  "
                      f"return={row['total_return_pct']!s:>10}%  "
                      f"DD={row['max_drawdown_pct']!s:>8}%  "
                      f"calmar={row['calmar_ratio']!s:>6}  "
                      f"sortino={row['sortino_ratio']!s:>6}  "
                      f"alpha={row['alpha_pct']!s:>7}  "
                      f"trades={row['n_trades']}")

        out_path = os.path.join(OUT_DIR, f"{param_name}.csv")
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["parameter", "value", "window"] + METRIC_COLUMNS)
            writer.writeheader()
            writer.writerows(param_rows)
        print(f"  Wrote {out_path}")

    combined_path = os.path.join(OUT_DIR, "all_results.csv")
    with open(combined_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["parameter", "value", "window"] + METRIC_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"\nWrote combined results to {combined_path} ({len(all_rows)} rows)")


if __name__ == "__main__":
    main()
