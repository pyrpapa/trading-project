"""
Converts the config-defined rule into buy/sell signals on a price DataFrame.

Nothing in here is hardcoded strategy logic — every threshold comes from
config/strategy.yaml. To change the strategy, edit the YAML, not this file.
"""
import pandas as pd


def add_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()
    ma_period = cfg["entry"]["ma_period"]
    vol_period = cfg["entry"]["volume_ma_period"]

    df["ma"] = df["Close"].rolling(ma_period).mean()
    df["volume_ma"] = df["Volume"].rolling(vol_period).mean()
    return df


def generate_signals(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    Adds a 'signal' column: 'BUY', 'SELL', or None for each row.
    This only decides ENTRY and trend-based EXIT. Stop-loss / take-profit
    are handled by the backtester since they depend on the entry price of
    an open position, not just the indicator values.
    """
    df = add_indicators(df, cfg)
    entry_cfg = cfg["entry"]
    exit_cfg = cfg["exit"]

    df["signal"] = None

    above_ma = df["Close"] > df["ma"]
    below_ma = df["Close"] < df["ma"]

    if entry_cfg["volume_confirmation"]:
        vol_ok = df["Volume"] > df["volume_ma"]
    else:
        vol_ok = True

    # Buy signal: price crosses above MA (wasn't above yesterday) + volume confirms
    crossed_up = above_ma & (~above_ma.shift(1).fillna(False))
    buy_signal = crossed_up & vol_ok

    # Trend-exit signal: price crosses below MA
    if exit_cfg["ma_exit"]:
        crossed_down = below_ma & (~below_ma.shift(1).fillna(False))
        sell_signal = crossed_down
    else:
        sell_signal = pd.Series(False, index=df.index)

    df.loc[buy_signal, "signal"] = "BUY"
    df.loc[sell_signal, "signal"] = "SELL"
    return df
