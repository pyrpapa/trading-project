"""
Strategy lab -- scores candidate strategies side by side against simple
baselines, all under the SAME realistic settings (fills at the next day's
open, 0.05%/side cost -- see backtest/engine.py's `execution`), so a
candidate only "wins" if it beats what a much simpler strategy already
gets on equal terms.

Development happens on the project's 4 standard windows. 2012-2018 is a
HOLDOUT: strategy_master was never tuned on it, so it's the one honest
out-of-sample check left -- run it (--holdout) once per finalist, at the
end, not while iterating.

Metrics are computed here from each strategy's daily equity curve (not
engine.compute_metrics) so every row, including blends of two
strategies, is scored by the same formulas. "pos_months" and
"worst_month" measure consistency directly -- the stated goal for this
project is small, steady gains, which Calmar alone doesn't capture.

Usage:
    python strategy_lab.py                 # 4 development windows
    python strategy_lab.py --holdout       # 2012-2018 holdout (spent on round 1)
    python strategy_lab.py --holdout2      # 2006-2011 holdout (reserved for round 2)
    python strategy_lab.py --only master,spy_200d
"""
import copy
import datetime as dt
import os
import sys
import warnings

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest import engine
from data import fetcher
from strategy import blend, portfolio_selection, rules

warnings.filterwarnings("ignore")

DEV_WINDOWS = {
    "2019-2024": ("2019-01-01", "2024-12-31"),
    "2020-2022-crisis": ("2020-06-01", "2022-12-31"),
    "2023-2026-crisis": ("2023-01-01", "2026-08-09"),
    "last-12mo": ("2025-08-15", "2026-08-15"),
}
HOLDOUT_WINDOWS = {"holdout-2012-2018": ("2012-01-01", "2018-12-31")}
# Second, fresh holdout (reserved 2026-09-27 after the first was spent on
# round-1 candidates). Covers the 2008 crash. Most 3x ETFs didn't exist
# yet, so it only suits strategies built on plain ETFs. Run it once, at
# the end of a round (--holdout2).
HOLDOUT2_WINDOWS = {"holdout-2006-2011": ("2006-01-01", "2011-12-31")}
WARMUP_DAYS = 560  # calendar days -- covers the 252-day momentum lookback plus buffer

REALISTIC = {"commission_pct": 0.05, "execution": "next_open"}
MASTER_CONFIG = "config/strategy_master.yaml"

# Unleveraged, liquid ETFs spanning asset classes that tend to trend at
# DIFFERENT times -- US large/small cap, international, emerging, long and
# intermediate Treasuries, gold, broad commodities, REITs. A research
# universe for the diversified-trend candidates only; not the live
# watchlist.
DIVERSIFIED = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC", "VNQ"]


# ---------------------------------------------------------------- helpers

def fetch(tickers, start, end):
    fetch_start = (dt.date.fromisoformat(start) - dt.timedelta(days=WARMUP_DAYS)).isoformat()
    out = {}
    for t in tickers:
        try:
            out[t] = fetcher.fetch(t, fetch_start, end)
        except RuntimeError:
            pass  # e.g. not listed yet in an early window -- skipped, not fatal
    return out


def simple_cfg(start, end, max_position_pct, sizing_method="pct", **risk):
    return {
        "backtest": {"starting_cash": 10_000, "start_date": start, "end_date": end, **REALISTIC},
        "exit": {"take_profit_pct": None, "stop_loss_pct": None},
        "risk": {"max_position_pct": max_position_pct, "max_invested_pct": 99.0,
                 "sizing_method": sizing_method, **risk},
    }


def signal_frame(index, buy, sell, reason="lab signal"):
    """BUY/SELL frame the engine understands. SELL wins if both are true."""
    sig = pd.DataFrame(index=index)
    sig["signal"] = None
    sig["reason"] = None
    buy = pd.Series(buy, index=index).fillna(False).astype(bool)
    sell = pd.Series(sell, index=index).fillna(False).astype(bool)
    sig.loc[buy, ["signal", "reason"]] = ["BUY", reason]
    sig.loc[sell, ["signal", "reason"]] = ["SELL", reason]
    sig["atr"] = np.nan
    return sig


def rsi(close, period):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss)


def month_ends(index):
    s = pd.Series(index, index=index)
    return s.groupby([index.year, index.month]).transform("max") == s


def run(price_data, signals, cfg):
    result = engine.run_backtest(price_data, signals, cfg)
    return result["equity_curve"]["portfolio_value"], len(result["trades"])


# ------------------------------------------------------------- strategies
# Each takes (start, end) and returns (daily equity Series, trade count).

def spy_buy_hold(start, end):
    data = fetch(["SPY"], start, end)
    idx = data["SPY"].index
    return run(data, {"SPY": signal_frame(idx, True, False)}, simple_cfg(start, end, 99.0))


def spy_200d(start, end):
    data = fetch(["SPY"], start, end)
    c = data["SPY"]["Close"]
    ma = c.rolling(200).mean()
    return run(data, {"SPY": signal_frame(c.index, c > ma, c < ma)}, simple_cfg(start, end, 99.0))


def master(start, end, vol_target=None):
    with open(MASTER_CONFIG) as f:
        cfg = yaml.safe_load(f)
    cfg["backtest"].update(start_date=start, end_date=end, **REALISTIC)
    if vol_target:
        cfg["risk"]["vol_target"] = {"enabled": True, "target_annual_pct": vol_target, "lookback_days": 20}
    data = fetch(portfolio_selection.universe_tickers(cfg), start, end)
    signals = {t: rules.generate_signals(df.copy(), cfg) for t, df in data.items()}
    return run(data, signals, cfg)


def trend_200d(start, end, sizing="equal", vol_target=None):
    """Hold each diversified-universe ETF while it's above its 200-day
    average (Faber-style trend filter), cash otherwise."""
    data = fetch(DIVERSIFIED, start, end)
    signals = {}
    for t, df in data.items():
        c = df["Close"]
        ma = c.rolling(200).mean()
        signals[t] = signal_frame(c.index, c > ma, c < ma, "above 200-day average")
    return run(data, signals, _diversified_cfg(start, end, len(data), sizing, vol_target))


def momentum_12m(start, end, sizing="equal", vol_target=None):
    """Time-series momentum (Moskowitz/Ooi/Pedersen 2012): at each month
    end, hold an ETF if its trailing 12-month return is positive, cash
    if not. Checked monthly only -- low turnover by design."""
    data = fetch(DIVERSIFIED, start, end)
    signals = {}
    for t, df in data.items():
        c = df["Close"]
        mom = c / c.shift(252) - 1
        me = month_ends(c.index)
        signals[t] = signal_frame(c.index, me & (mom > 0), me & (mom <= 0), "12-month return positive")
    return run(data, signals, _diversified_cfg(start, end, len(data), sizing, vol_target))


def _diversified_cfg(start, end, n_assets, sizing, vol_target):
    if sizing == "inverse_vol":
        cfg = simple_cfg(start, end, 30.0, sizing_method="inverse_vol",
                         inverse_vol={"target_position_vol_pct": 4.0, "lookback_days": 60})
    else:
        cfg = simple_cfg(start, end, 99.0 / n_assets)
    if vol_target:
        cfg["risk"]["vol_target"] = {"enabled": True, "target_annual_pct": vol_target, "lookback_days": 20}
    return cfg


def dip_buy(start, end, tickers=("SPY", "QQQ")):
    """Short-term mean reversion (Connors-style RSI-2): buy after a sharp
    2-day selloff (RSI(2) < 10) but only while the ETF is still above its
    200-day average; sell on the first close back above the 5-day
    average. Many small wins, frequent trades."""
    data = fetch(list(tickers), start, end)
    signals = {}
    for t, df in data.items():
        c = df["Close"]
        buy = (c > c.rolling(200).mean()) & (rsi(c, 2) < 10)
        sell = c > c.rolling(5).mean()
        signals[t] = signal_frame(c.index, buy & ~sell, sell, "RSI(2) dip in an uptrend")
    return run(data, signals, simple_cfg(start, end, 99.0 / len(data)))


def rotation(start, end, tickers, pick, monthly=False, reason="rotation"):
    """Holds exactly one ticker at a time: `pick(closes, date)` returns
    which, from a DataFrame of every ticker's closes up to that date.
    monthly=True only re-decides at month ends (fewer, slower switches)."""
    data = fetch(tickers, start, end)
    closes = pd.DataFrame({t: df["Close"] for t, df in data.items()}).dropna()
    choice = pd.Series(index=closes.index, dtype=object)
    for i, date in enumerate(closes.index):
        if i < 260:
            continue
        choice.iloc[i] = pick(closes.iloc[: i + 1])
    if monthly:
        me = month_ends(closes.index)
        choice = choice.where(me).ffill()
    signals = {t: signal_frame(closes.index, choice == t, choice.notna() & (choice != t), reason)
               for t in data}
    return run({t: df.loc[closes.index] for t, df in data.items()}, signals, simple_cfg(start, end, 99.0))


def spy_200d_safe(start, end):
    """SPY while it's above its 200-day average, otherwise short-term
    Treasuries (SHY) instead of zero-yield cash."""
    return rotation(start, end, ["SPY", "SHY"],
                    lambda c: "SPY" if c["SPY"].iloc[-1] > c["SPY"].iloc[-200:].mean() else "SHY",
                    reason="SPY vs its 200-day average")


def faber_monthly(start, end):
    """Faber (2007): SPY vs its 10-month (~210-day) average, checked only
    at month ends; SHY otherwise."""
    return rotation(start, end, ["SPY", "SHY"],
                    lambda c: "SPY" if c["SPY"].iloc[-1] > c["SPY"].iloc[-210:].mean() else "SHY",
                    monthly=True, reason="SPY vs its 10-month average (monthly)")


def dual_momentum(start, end):
    """Antonacci's Global Equities Momentum: monthly, if US stocks' 12-month
    return beats T-bills' (SHY), hold whichever of US (SPY) or
    international (EFA) stocks has the stronger 12-month return;
    otherwise hold aggregate bonds (AGG)."""
    def pick(c):
        ret = c.iloc[-1] / c.iloc[-253] - 1
        if ret["SPY"] <= ret["SHY"]:
            return "AGG"
        return "SPY" if ret["SPY"] >= ret["EFA"] else "EFA"
    return rotation(start, end, ["SPY", "EFA", "AGG", "SHY"], pick, monthly=True, reason="dual momentum")


def _blend_cfg():
    with open("config/strategy_blend.yaml") as f:
        return yaml.safe_load(f)


def blend_trend_sleeve(start, end):
    """Trend sleeve exactly as live/run_blend.py trades it (strategy/blend.py)."""
    cfg = _blend_cfg()["trend"]
    data = fetch(cfg["universe"], start, end)
    signals = {t: blend.trend_signals(df, cfg) for t, df in data.items()}
    return run(data, signals, blend.engine_cfg(cfg, start, end, "inverse_vol"))


def blend_dip_sleeve(start, end):
    """Dip sleeve exactly as live/run_blend.py trades it (strategy/blend.py)."""
    cfg = _blend_cfg()["dip"]
    data = fetch(cfg["tickers"], start, end)
    signals = {t: blend.dip_signals(df, cfg) for t, df in data.items()}
    return run(data, signals, blend.engine_cfg(cfg, start, end, "pct"))


STRATEGIES = {
    "spy_buy_hold":        ("SPY buy & hold", spy_buy_hold),
    "spy_200d":            ("SPY > 200d avg, else cash", spy_200d),
    "master":              ("Master (live strategy)", master),
    "master_vt25":         ("Master + vol target 25%", lambda s, e: master(s, e, vol_target=25)),
    "master_vt15":         ("Master + vol target 15%", lambda s, e: master(s, e, vol_target=15)),
    "trend_200d":          ("Diversified trend 200d, equal wt", trend_200d),
    "trend_200d_iv":       ("Diversified trend 200d, inv-vol", lambda s, e: trend_200d(s, e, "inverse_vol")),
    "momentum_12m":        ("Diversified 12m momentum, equal wt", momentum_12m),
    "momentum_12m_iv":     ("Diversified 12m momentum, inv-vol", lambda s, e: momentum_12m(s, e, "inverse_vol")),
    "dip_buy":             ("Dip-buy RSI(2), SPY+QQQ", dip_buy),
    "spy_200d_safe":       ("SPY > 200d avg, else SHY", spy_200d_safe),
    "faber_monthly":       ("SPY > 10-mo avg monthly, else SHY", faber_monthly),
    "dual_momentum":       ("Dual momentum SPY/EFA/AGG", dual_momentum),
    "blend_trend_sleeve":  ("Blend config: trend sleeve", blend_trend_sleeve),
    "blend_dip_sleeve":    ("Blend config: dip sleeve", blend_dip_sleeve),
}

# name -> {strategy_key: weight}; daily-rebalanced blend of return streams
BLENDS = {
    "blend_config":      ("Blend (config/strategy_blend.yaml)", {"blend_trend_sleeve": 0.5, "blend_dip_sleeve": 0.5}),
    "blend_trend_dip":   ("Blend: 50% trend 200d iv + 50% dip-buy", {"trend_200d_iv": 0.5, "dip_buy": 0.5}),
    "blend_master_trend": ("Blend: 50% master + 50% trend 200d iv", {"master": 0.5, "trend_200d_iv": 0.5}),
    "blend_spy200safe_dip": ("Blend: 50% SPY 200d/SHY + 50% dip-buy", {"spy_200d_safe": 0.5, "dip_buy": 0.5}),
    "blend_faber_dip":    ("Blend: 50% Faber monthly + 50% dip-buy", {"faber_monthly": 0.5, "dip_buy": 0.5}),
    "blend_dualmom_dip":  ("Blend: 50% dual momentum + 50% dip-buy", {"dual_momentum": 0.5, "dip_buy": 0.5}),
}


# ---------------------------------------------------------------- scoring

def score(equity, spy_returns, start, end):
    equity = equity.loc[start:end]
    r = equity.pct_change().dropna()
    years = len(r) / 252
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    dd = (equity / equity.cummax() - 1).min()
    downside = r[r < 0].std() * np.sqrt(252)
    monthly = equity.resample("ME").last().pct_change().dropna()
    aligned = pd.concat([r, spy_returns], axis=1, join="inner").dropna()
    if len(aligned) > 20 and aligned.iloc[:, 1].var() > 0:
        beta = aligned.iloc[:, 0].cov(aligned.iloc[:, 1]) / aligned.iloc[:, 1].var()
        alpha = (aligned.iloc[:, 0].mean() - beta * aligned.iloc[:, 1].mean()) * 252
    else:
        alpha = np.nan
    return {
        "CAGR%": round(cagr * 100, 1),
        "vol%": round(r.std() * np.sqrt(252) * 100, 1),
        "maxDD%": round(dd * 100, 1),
        "Calmar": round(cagr / abs(dd), 2) if dd < 0 else np.nan,
        "Sortino": round(r.mean() * 252 / downside, 2) if downside > 0 else np.nan,
        "alpha%": round(alpha * 100, 1),
        "pos_months%": round((monthly > 0).mean() * 100),
        "worst_month%": round(monthly.min() * 100, 1),
    }


def main():
    if "--holdout2" in sys.argv:
        windows, tag = HOLDOUT2_WINDOWS, "holdout2"
    elif "--holdout" in sys.argv:
        windows, tag = HOLDOUT_WINDOWS, "holdout"
    else:
        windows, tag = DEV_WINDOWS, "dev"
    keys = list(STRATEGIES) + list(BLENDS)
    if "--only" in sys.argv:
        keys = sys.argv[sys.argv.index("--only") + 1].split(",")

    rows = []
    for window, (start, end) in windows.items():
        print(f"Running {window} ...", flush=True)
        spy = fetch(["SPY"], start, end)["SPY"]["Close"].loc[start:end].pct_change().dropna()
        curves, trades = {}, {}
        needed = set(k for k in keys if k in STRATEGIES)
        for k in keys:
            if k in BLENDS:
                needed |= set(BLENDS[k][1])
        for k in needed:
            curves[k], trades[k] = STRATEGIES[k][1](start, end)
        for k in keys:
            if k in STRATEGIES:
                label, eq, n = STRATEGIES[k][0], curves[k], trades[k]
            else:
                label, weights = BLENDS[k]
                rets = sum(w * pd.DataFrame({s: curves[s] for s in weights}).ffill()[s].pct_change().fillna(0)
                           for s, w in weights.items())
                eq, n = (1 + rets).cumprod() * 10_000, sum(trades[s] for s in weights)
            rows.append({"window": window, "strategy": label, **score(eq, spy, start, end), "trades": n})

    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 20)
    for window, group in df.groupby("window", sort=False):
        print(f"\n=== {window} ===")
        print(group.drop(columns="window").to_string(index=False))

    if len(windows) > 1:
        summary = df.groupby("strategy", sort=False)[["Calmar", "Sortino", "pos_months%", "maxDD%"]].median()
        print("\n=== Median across windows ===")
        print(summary.sort_values("Calmar", ascending=False).to_string())

    out_dir = os.path.join("results", "strategy_lab")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, tag + ".csv")
    df.to_csv(out, index=False)
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
