"""
Signal and sizing rules for the trend + dip-buy blend
(config/strategy_blend.yaml). Shared by strategy_lab.py (backtests) and
live/run_blend.py (paper trading) so both run exactly the same logic.

Each *_signals function returns a DataFrame on the price index with a
'signal' column ('BUY' / 'SELL' / None) and a 'reason' column -- the
same shape backtest/engine.py consumes. SELL wins when both hold.
"""
import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss)


def _frame(index, buy, sell, buy_reason, sell_reason):
    sig = pd.DataFrame(index=index)
    sig["signal"] = None
    sig["reason"] = None
    buy = pd.Series(buy, index=index).fillna(False).astype(bool)
    sell = pd.Series(sell, index=index).fillna(False).astype(bool)
    sig.loc[buy & ~sell, ["signal", "reason"]] = ["BUY", buy_reason]
    sig.loc[sell, ["signal", "reason"]] = ["SELL", sell_reason]
    sig["atr"] = np.nan  # engine compatibility; unused by these rules
    return sig


def trend_signals(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """BUY while close > its ma_period average, SELL while below."""
    c = df["Close"]
    ma = c.rolling(cfg["ma_period"]).mean()
    n = cfg["ma_period"]
    return _frame(c.index, c > ma, c < ma,
                  f"closed above its {n}-day average (trend sleeve)",
                  f"closed below its {n}-day average (trend sleeve)")


def trend_weight(df: pd.DataFrame, cfg: dict, date=None):
    """Fraction of the trend sleeve to put in this ETF as of `date` (last
    row if None): target vol / realized vol, capped. None if there isn't
    enough history to measure its volatility yet."""
    vol = df["Close"].pct_change().rolling(cfg["vol_lookback_days"]).std() * np.sqrt(252)
    v = vol.iloc[-1] if date is None else vol.get(date)
    if v is None or pd.isna(v) or v <= 0:
        return None
    return min(cfg["target_position_vol_pct"] / 100 / v, cfg["max_position_pct"] / 100)


def dip_signals(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """BUY after an RSI dip while above the long average; SELL on the
    first close back above the short average."""
    c = df["Close"]
    buy = (c > c.rolling(cfg["trend_ma_period"]).mean()) & (rsi(c, cfg["rsi_period"]) < cfg["rsi_below"])
    sell = c > c.rolling(cfg["exit_ma_period"]).mean()
    return _frame(c.index, buy, sell,
                  f"RSI({cfg['rsi_period']}) below {cfg['rsi_below']} while above its "
                  f"{cfg['trend_ma_period']}-day average (dip sleeve)",
                  f"closed back above its {cfg['exit_ma_period']}-day average (dip sleeve)")


def engine_cfg(sleeve_cfg: dict, start: str, end: str, sizing: str, commission_pct: float = 0.05,
               execution: str = "next_open") -> dict:
    """backtest/engine.py config reproducing one sleeve on its own."""
    risk = {"max_position_pct": sleeve_cfg["max_position_pct"],
            "max_invested_pct": sleeve_cfg["max_invested_pct"], "sizing_method": sizing}
    if sizing == "inverse_vol":
        risk["inverse_vol"] = {"target_position_vol_pct": sleeve_cfg["target_position_vol_pct"],
                               "lookback_days": sleeve_cfg["vol_lookback_days"]}
    return {
        "backtest": {"starting_cash": 10_000, "start_date": start, "end_date": end,
                     "commission_pct": commission_pct, "execution": execution},
        "exit": {"take_profit_pct": None, "stop_loss_pct": None},
        "risk": risk,
    }
