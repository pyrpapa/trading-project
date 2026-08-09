"""
Run a full backtest using the config in config/strategy.yaml (or a
different config file passed via --config).

Usage:
    python run_backtest.py                                  # real data, config/strategy.yaml
    python run_backtest.py --synthetic                       # offline test data
    python run_backtest.py --save                            # also save results to Supabase
    python run_backtest.py --save --label "v2"                # save with a run label
    python run_backtest.py --config config/strategy_v2.yaml   # use a different config file
"""
import sys
import os
import yaml

sys.path.insert(0, os.path.dirname(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional; env vars can be set another way

from data import fetcher, synthetic
from strategy import rules
from backtest import engine


def main():
    use_synthetic = "--synthetic" in sys.argv
    save_to_supabase = "--save" in sys.argv
    run_label = None
    if "--label" in sys.argv:
        idx = sys.argv.index("--label")
        if idx + 1 < len(sys.argv):
            run_label = sys.argv[idx + 1]

    config_path = "config/strategy.yaml"
    if "--config" in sys.argv:
        idx = sys.argv.index("--config")
        if idx + 1 < len(sys.argv):
            config_path = sys.argv[idx + 1]

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    tickers = cfg["watchlist"]
    start = cfg["backtest"]["start_date"]
    end = cfg["backtest"]["end_date"]

    print(f"{'[SYNTHETIC DATA]' if use_synthetic else '[REAL DATA]'} Using {config_path} — {tickers} from {start} to {end}...")

    if use_synthetic:
        price_data = synthetic.generate_watchlist(tickers, start, end)
    else:
        price_data = fetcher.fetch_watchlist(tickers, start, end)

    # Fail fast with a clear message instead of a cryptic crash deep in
    # the backtest engine if any ticker came back with no usable data
    # for the requested range.
    for ticker, df in price_data.items():
        print(f"  {ticker}: {len(df)} rows ({df.index.min().date() if not df.empty else 'n/a'} to {df.index.max().date() if not df.empty else 'n/a'})")
    empty_tickers = [t for t, df in price_data.items() if df.empty]
    if empty_tickers:
        print(f"\nERROR: no data for {empty_tickers} in range {start} to {end}.")
        print("Try: delete data/cache/ and rerun, or check the ticker symbols and dates are valid.")
        sys.exit(1)

    signals = {t: rules.generate_signals(df, cfg) for t, df in price_data.items()}

    print("Running backtest...")
    result = engine.run_backtest(price_data, signals, cfg)

    print("\n=== METRICS ===")
    for k, v in result["metrics"].items():
        print(f"  {k}: {v}")

    print(f"\n=== TRADES ({len(result['trades'])}) ===")
    for t in result["trades"][:20]:
        print(f"  {t['ticker']}: {t['entry_date'].date()} @ {t['entry_price']:.2f} -> "
              f"{t['exit_date'].date()} @ {t['exit_price']:.2f}  "
              f"({t['return_pct']:+.2f}%, {t['exit_reason']})")
    if len(result["trades"]) > 20:
        print(f"  ... and {len(result['trades']) - 20} more")

    if save_to_supabase:
        from storage.supabase_client import SupabaseStore
        print("\nSaving to Supabase...")
        store = SupabaseStore()
        run = store.save_backtest_run(cfg, result["metrics"], run_label=run_label)
        if run:
            store.save_trades(result["trades"], source="backtest", backtest_run_id=run["id"])
            print(f"  Saved as backtest_runs.id = {run['id']} ({len(result['trades'])} trades)")

    return result


if __name__ == "__main__":
    main()
