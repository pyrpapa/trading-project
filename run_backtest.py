"""
Run a full backtest using the config in config/strategy.yaml (or a
different config file passed via --config).

Usage:
    python run_backtest.py                                  # real data, config/strategy.yaml
    python run_backtest.py --synthetic                       # offline test data
    python run_backtest.py --save                            # also save results to Supabase
    python run_backtest.py --save --label "v2"                # save with a run label
    python run_backtest.py --config config/strategy_v2.yaml   # use a different config file
    python run_backtest.py --chart                           # also write an HTML chart report
"""
import sys
import os
import datetime as dt
import yaml

sys.path.insert(0, os.path.dirname(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional; env vars can be set another way

from data import fetcher, synthetic
from strategy import rules, portfolio_selection
from backtest import engine


def main():
    use_synthetic = "--synthetic" in sys.argv
    save_to_supabase = "--save" in sys.argv
    make_chart = "--chart" in sys.argv
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

    tickers = portfolio_selection.universe_tickers(cfg)
    start = cfg["backtest"]["start_date"]
    end = cfg["backtest"]["end_date"]

    ps_enabled = (cfg.get("portfolio_selection") or {}).get("enabled", False)
    universe_note = (
        f"{len(tickers)} candidates, target size {cfg['portfolio_selection'].get('target_size')}"
        if ps_enabled else str(tickers)
    )
    # Fetch extra history BEFORE start_date so every rolling window (MA,
    # volume MA, ATR, Donchian breakout/exit, portfolio-selection
    # liquidity+correlation, correlation circuit breaker) already has a
    # full lookback's worth of real data by the first simulated day,
    # instead of warming up DURING the backtest period itself. Without
    # this, portfolio_selection configs in particular start with an EMPTY
    # active set for the first ~lookback_period trading days (see
    # strategy_v7_portfolio_selection.yaml's "known startup quirk") --
    # same fix pattern already used in live/run_live.py, just applied to
    # the backtest fetch too so the two stay consistent.
    corr_cfg = cfg.get("risk", {}).get("correlation_breaker") or {}
    lookback_days = max(
        cfg["entry"]["ma_period"], cfg["entry"]["volume_ma_period"],
        cfg["entry"].get("breakout_period", 0),
        cfg["entry"].get("regime_filter_period", 0),
        cfg["entry"].get("choppiness_filter_period", 14),
        cfg.get("exit", {}).get("exit_breakout_period", 0),
        cfg.get("risk", {}).get("atr_period", 20),
        cfg["portfolio_selection"].get("lookback_period", 0) if ps_enabled else 0,
        corr_cfg.get("lookback_period", 0) if corr_cfg.get("enabled") else 0,
    ) + 30
    fetch_start = (dt.date.fromisoformat(start) - dt.timedelta(days=lookback_days * 2)).isoformat()  # *2 for weekends/holidays

    print(f"{'[SYNTHETIC DATA]' if use_synthetic else '[REAL DATA]'} Using {config_path} — {universe_note} "
          f"from {start} to {end} (fetching from {fetch_start} for {lookback_days}-trading-day warm-up)...")

    if use_synthetic:
        price_data = synthetic.generate_watchlist(tickers, fetch_start, end)
    else:
        price_data = fetcher.fetch_watchlist(tickers, fetch_start, end)

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

    # SPY as the default benchmark for metrics["beta"]/["alpha_pct"] --
    # answers "is this adding real value beyond just being correlated with
    # a rising market," not just "did it beat SPY's raw number." Skipped
    # for synthetic data (no real benchmark to compare against) and fails
    # open on any fetch error (a benchmark hiccup shouldn't block the
    # backtest itself) -- beta/alpha just come back None in that case,
    # same as every other optional metric in compute_metrics.
    benchmark_returns = None
    if not use_synthetic:
        try:
            spy_df = fetcher.fetch("SPY", fetch_start, end)
            benchmark_returns = spy_df.loc[start:end, "Close"].pct_change().dropna()
        except Exception as e:
            print(f"  Note: SPY benchmark fetch failed ({e}) — beta/alpha will be None this run.")

    print("Running backtest...")
    result = engine.run_backtest(price_data, signals, cfg, benchmark_returns=benchmark_returns)

    print("\n=== METRICS ===")
    for k, v in result["metrics"].items():
        print(f"  {k}: {v}")

    print(f"\n=== TRADES ({len(result['trades'])}) ===")
    for t in result["trades"][:20]:
        print(f"  {t['ticker']}: {t['entry_date'].date()} @ {t['entry_price']:.2f} -> "
              f"{t['exit_date'].date()} @ {t['exit_price']:.2f}  "
              f"({t['return_pct']:+.2f}%, {t['exit_reason']})")
        if t.get("entry_log"):
            print(f"      {t['entry_log']}")
        if t.get("exit_log"):
            print(f"      {t['exit_log']}")
    if len(result["trades"]) > 20:
        print(f"  ... and {len(result['trades']) - 20} more")

    blocked = result.get("blocked_signals") or []
    if blocked:
        print(f"\n=== CIRCUIT BREAKER ({len(blocked)} signal(s) blocked) ===")
        for b in blocked[:10]:
            print(f"  {b['ticker']} on {b['date'].date()}: {b['reason']}")
        if len(blocked) > 10:
            print(f"  ... and {len(blocked) - 10} more")

    rebalances = result.get("rebalance_log") or []
    if rebalances:
        print(f"\n=== PORTFOLIO SELECTION ({len(rebalances)} rebalance(s)) ===")
        for r in rebalances:
            added = f", +{r['added']}" if r["added"] else ""
            dropped = f", -{r['dropped']}" if r["dropped"] else ""
            print(f"  {r['date'].date()}: {r['selected']}{added}{dropped}")

    pyramid_adds = result.get("pyramid_log") or []
    if pyramid_adds:
        print(f"\n=== PYRAMIDING ({len(pyramid_adds)} unit(s) added) ===")
        for p in pyramid_adds[:20]:
            print(f"  {p['date'].date()}: {p['log']}")
        if len(pyramid_adds) > 20:
            print(f"  ... and {len(pyramid_adds) - 20} more")

    store = None
    if save_to_supabase:
        from storage.supabase_client import SupabaseStore
        print("\nSaving to Supabase...")
        store = SupabaseStore()
        run = store.save_backtest_run(cfg, result["metrics"], run_label=run_label)
        if run:
            store.save_trades(result["trades"], source="backtest", backtest_run_id=run["id"])
            print(f"  Saved as backtest_runs.id = {run['id']} ({len(result['trades'])} trades)")

    if make_chart:
        import report
        safe_label = (run_label or os.path.splitext(os.path.basename(config_path))[0]).replace(" ", "_")
        out_path = os.path.join("results", f"{safe_label}_report.html")
        # Trim off the pre-start_date warm-up buffer for the chart only --
        # the engine needs it for indicator lookback, but the chart should
        # show the actual requested period, not the extra history fetched
        # to warm it up.
        chart_price_data = {t: df.loc[start:end] for t, df in price_data.items()}
        report.generate_html_report(result, cfg, chart_price_data, run_label or safe_label, out_path)
        print(f"\nWrote chart report to {out_path}")

        # Uploaded (not just written locally) whenever Supabase is also in
        # play -- a GitHub Actions runner's filesystem disappears when the
        # job ends, so the local file alone is useless to anyone outside
        # that run. object_name matches out_path's own basename exactly so
        # the dashboard can construct the same public URL from a run_label
        # alone (see storage/supabase_client.py's upload_report). Fails
        # open (warns, doesn't raise) -- the backtest itself already
        # succeeded and its metrics/trades are already saved by this
        # point, so a missing/misconfigured Storage bucket (e.g. it
        # hasn't been created yet -- see README's Supabase setup step 4)
        # shouldn't mark the whole run as failed over a report nobody's
        # blocked on.
        if store:
            try:
                report_url = store.upload_report(out_path, os.path.basename(out_path))
                print(f"  Uploaded report: {report_url}")
            except Exception as e:
                print(f"  Note: report upload failed ({e}) -- metrics/trades were still saved above. "
                      f"Check that the '{store.REPORTS_BUCKET}' Storage bucket exists and is public.")

    return result


if __name__ == "__main__":
    main()
