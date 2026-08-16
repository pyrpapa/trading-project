"""
Runs the blended ETF/crypto portfolio -- majority weight to a leveraged
ETF sleeve (SPXL/TQQQ/SOXL/FAS/TNA/TECL, master's signal + trailing
stop), a SMALL FIXED allocation to crypto (config/strategy_master.yaml,
v36), not a momentum-driven rotation. This is the strategy this project
landed on after the "crypto's headline backtest numbers are mostly a
historic bull-market artifact" reassessment -- built to be resilient
first, not to chase crypto's peak returns.

Unlike rotation_backtest.py's momentum-driven weight (which flexes the
crypto allocation up to 90%+ when crypto is trending), CRYPTO_WEIGHT
here is a constant, deliberately small fraction of the portfolio --
"crypto as a small piece of the pot," matching what was actually asked
for, not something that grows back into the majority during a rally.

Same blending approach as rotation_backtest.py: each sleeve runs its
own full, independent backtest (its own entries/exits/sizing, as if it
alone had the full starting capital), then the two DAILY RETURN series
get blended at a fixed weight and compounded into one equity curve.
Valid because both sleeves size positions as a % of their own equity --
we're blending percentage returns, not dollar amounts.

Usage:
    python blend_backtest.py                          # last-12mo window, $5,000
    python blend_backtest.py --start 2019-01-01 --end 2024-12-31
    python blend_backtest.py --crypto-weight 0.20
    python blend_backtest.py --chart                  # also write an HTML report
"""
import sys
import os
import copy
import datetime as dt
import yaml
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from data import fetcher
from strategy import rules, portfolio_selection
from backtest import engine

ETF_CONFIG = "config/strategy_v22_leveraged_etfs.yaml"
ETF_WATCHLIST = ["SPXL", "TQQQ", "SOXL", "FAS", "TNA", "TECL"]
CRYPTO_CONFIG = "config/strategy_master.yaml"
WARMUP_DAYS = 560


def run_sleeve(cfg_path, overrides, start, end):
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    cfg = copy.deepcopy(cfg)
    for path, value in overrides.items():
        parts = path.split(".")
        node = cfg
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = value
    cfg["backtest"]["start_date"] = start
    cfg["backtest"]["end_date"] = end
    tickers = portfolio_selection.universe_tickers(cfg)
    fetch_start = (dt.date.fromisoformat(start) - dt.timedelta(days=WARMUP_DAYS)).isoformat()
    price_data = fetcher.fetch_watchlist(tickers, fetch_start, end)
    signals = {t: rules.generate_signals(df, cfg) for t, df in price_data.items()}
    result = engine.run_backtest(price_data, signals, cfg)
    return result, cfg


def run_blend(start, end, crypto_weight=0.15, starting_cash=5000):
    etf_result, etf_cfg = run_sleeve(
        ETF_CONFIG,
        {"watchlist": ETF_WATCHLIST, "risk.trailing_stop": {"enabled": True, "atr_multiple": 2.0}},
        start, end,
    )
    crypto_result, crypto_cfg = run_sleeve(CRYPTO_CONFIG, {}, start, end)

    calendar = etf_result["equity_curve"].index
    etf_ret = etf_result["equity_curve"]["portfolio_value"].pct_change().reindex(calendar).fillna(0)
    crypto_ret = (
        crypto_result["equity_curve"]["portfolio_value"]
        .reindex(calendar).ffill().pct_change().reindex(calendar).fillna(0)
    )
    blended_ret = (1 - crypto_weight) * etf_ret + crypto_weight * crypto_ret
    blended_value = starting_cash * (1 + blended_ret).cumprod()
    blended_eq = pd.DataFrame({"portfolio_value": blended_value}, index=calendar)

    try:
        spy_df = fetcher.fetch("SPY", start, end)
        benchmark_returns = spy_df.loc[start:end, "Close"].pct_change().dropna()
    except Exception:
        benchmark_returns = None

    metrics = engine.compute_metrics(blended_eq, [], starting_cash, benchmark_returns=benchmark_returns)
    return {
        "metrics": metrics, "equity_curve": blended_eq,
        "etf_result": etf_result, "etf_cfg": etf_cfg,
        "crypto_result": crypto_result, "crypto_cfg": crypto_cfg,
        "crypto_weight": crypto_weight, "starting_cash": starting_cash,
    }


def main():
    args = sys.argv[1:]

    def get_flag(name, default):
        if name in args:
            idx = args.index(name)
            if idx + 1 < len(args):
                return args[idx + 1]
        return default

    start = get_flag("--start", "2025-08-15")
    end = get_flag("--end", "2026-08-15")
    crypto_weight = float(get_flag("--crypto-weight", "0.15"))
    starting_cash = float(get_flag("--starting-cash", "5000"))
    make_chart = "--chart" in args

    print(f"Blended ETF/crypto backtest: {start} to {end}, crypto weight {crypto_weight:.0%}, "
          f"starting cash ${starting_cash:,.0f}")
    print(f"  ETF sleeve: {ETF_WATCHLIST} + trailing stop (weight {1 - crypto_weight:.0%})")
    print(f"  Crypto sleeve: config/strategy_master.yaml, v36 (weight {crypto_weight:.0%})")
    print()

    result = run_blend(start, end, crypto_weight, starting_cash)

    print("=== BLENDED METRICS ===")
    for k, v in result["metrics"].items():
        print(f"  {k}: {v}")

    print()
    print("=== FOR CONTEXT: each sleeve alone over the same window ===")
    etf_m = result["etf_result"]["metrics"]
    crypto_m = result["crypto_result"]["metrics"]
    print(f"  ETF alone:    return {etf_m['total_return_pct']}%  DD {etf_m['max_drawdown_pct']}%  "
          f"Sortino {etf_m['sortino_ratio']}  Calmar {etf_m.get('calmar_ratio')}")
    print(f"  Crypto alone: return {crypto_m['total_return_pct']}%  DD {crypto_m['max_drawdown_pct']}%  "
          f"Sortino {crypto_m['sortino_ratio']}  Calmar {crypto_m.get('calmar_ratio')}")

    if make_chart:
        import report
        safe_label = f"blend-{start}-to-{end}".replace(":", "")
        out_path = os.path.join("results", f"{safe_label}_report.html")
        report.generate_blend_html_report(result, safe_label, out_path)
        print(f"\nWrote chart report to {out_path}")

    return result


if __name__ == "__main__":
    main()
