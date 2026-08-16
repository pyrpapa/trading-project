"""
Converts the config-defined rule into buy/sell signals on a price DataFrame.

Nothing in here is hardcoded strategy logic — every threshold comes from
config/strategy.yaml. To change the strategy, edit the YAML, not this file.
"""
import numpy as np
import pandas as pd


def add_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()
    entry_cfg = cfg["entry"]
    exit_cfg = cfg.get("exit", {})
    ma_period = entry_cfg["ma_period"]
    vol_period = entry_cfg["volume_ma_period"]
    atr_period = cfg.get("risk", {}).get("atr_period", 20)
    breakout_period = entry_cfg.get("breakout_period", 20)
    exit_breakout_period = exit_cfg.get("exit_breakout_period", 10)

    df["ma"] = df["Close"].rolling(ma_period).mean()
    df["volume_ma"] = df["Volume"].rolling(vol_period).mean()

    # Regime filter (optional, opt-in via entry.regime_filter_period) --
    # a much slower moving average than the entry ma_period. When set,
    # the fast crossover entry additionally requires price to be above
    # THIS slower average too -- don't take the fast signal unless the
    # macro trend agrees. Only computed when configured (unlike
    # donchian/atr above) since its period is typically much longer
    # (e.g. 200 days) and would otherwise inflate the warm-up buffer
    # for every config, not just ones that use it.
    regime_filter_period = entry_cfg.get("regime_filter_period")
    if regime_filter_period:
        df["regime_ma"] = df["Close"].rolling(regime_filter_period).mean()

    # Donchian channel high — the highest High over the `breakout_period`
    # days BEFORE today (shift(1) excludes today itself, so today's own
    # high can't count toward its own breakout threshold — no lookahead).
    # Computed unconditionally (cheap), same "always available" pattern as
    # ATR below, so switching entry.type doesn't require touching this
    # function again. Only used when entry.type is "donchian_breakout",
    # but harmless to compute either way.
    df["donchian_high"] = df["High"].shift(1).rolling(breakout_period).max()

    # Donchian channel low — the lowest Low over the `exit_breakout_period`
    # days BEFORE today (same no-lookahead shift(1) pattern as the high
    # above). Only used when exit.type is "donchian_low" (see
    # generate_signals below), but computed unconditionally so switching
    # exit.type is a pure config change, no code path needs re-touching.
    df["donchian_low"] = df["Low"].shift(1).rolling(exit_breakout_period).min()

    # ATR ("N" in Turtle terms) — average true range, a volatility measure
    # used for N/ATR-based position sizing and stops (risk.sizing_method:
    # atr_unit). Computed unconditionally (cheap) so it's available the
    # moment a config switches sizing methods, with no other code changes.
    prev_close = df["Close"].shift(1)
    true_range = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = true_range.rolling(atr_period).mean()

    # Choppiness Index (optional, opt-in via entry.choppiness_filter_period)
    # -- Dreiss's own formula: 100 * log10(sum of True Range over n days /
    # (n-day High - n-day Low)) / log10(n). Measures how EFFICIENTLY price
    # covered ground, not which direction -- if price traveled a lot of
    # total distance (big True Range sum) but the NET high-to-low range is
    # small, that's a choppy/ranging market (CI near 100); if the True
    # Range sum is close to the net range, price moved efficiently in one
    # direction (CI near 0, a real trend). Deliberately a DIFFERENT
    # question than the regime filter above -- regime_filter_period asks
    # "which direction is the slow trend," this asks "is there actually a
    # trend to follow right now, regardless of direction." Built in direct
    # response to the last-12-months diagnosis: the regime filter was
    # already blocking entries 79.6% of the time that year (vs 42.9%
    # historically) -- it correctly avoided most of the downtrend, but of
    # the ~20% of days it DID allow an entry, 32 of 33 trades still ended
    # in a stop-loss with short hold times, the signature of choppiness
    # WITHIN a nominally-eligible stretch, not a direction problem the
    # regime filter could ever catch. Computed unconditionally (cheap,
    # reuses true_range from the ATR calc above) so switching this on is a
    # pure config change, same "always available" pattern as everything
    # else in this function.
    choppiness_period = entry_cfg.get("choppiness_filter_period", 14)
    high_n = df["High"].rolling(choppiness_period).max()
    low_n = df["Low"].rolling(choppiness_period).min()
    price_range = high_n - low_n
    atr_sum = true_range.rolling(choppiness_period).sum()
    with np.errstate(divide="ignore", invalid="ignore"):
        df["choppiness_index"] = np.where(
            price_range > 0,
            100 * np.log10(atr_sum / price_range) / np.log10(choppiness_period),
            np.nan,
        )

    return df


def entry_reason_text(cfg: dict) -> str:
    """
    Human-readable description of WHY the current entry rule would fire,
    built entirely from config so it stays accurate as the rule changes.
    `entry.type` selects which wording applies — "ma_crossover" (default,
    v1-v7 behavior) or "donchian_breakout" (see generate_signals below).
    """
    entry_cfg = cfg["entry"]
    entry_type = entry_cfg.get("type", "ma_crossover")

    if entry_type == "always":
        return "no entry timing filter -- bought back in as soon as eligible (v21 always-in test)"
    elif entry_type == "donchian_breakout":
        breakout_period = entry_cfg.get("breakout_period", 20)
        reason = f"price closed above its {breakout_period}-day high (Donchian breakout)"
    else:
        reason = f"price closed above its {entry_cfg['ma_period']}-day moving average"

    if entry_cfg.get("volume_confirmation"):
        reason += (
            f", with volume above its {entry_cfg['volume_ma_period']}-day "
            "average (volume confirmation)"
        )
    regime_filter_period = entry_cfg.get("regime_filter_period")
    if regime_filter_period:
        reason += f", with price above its {regime_filter_period}-day regime-filter average"
    choppiness_threshold = entry_cfg.get("choppiness_threshold")
    if choppiness_threshold:
        choppiness_period = entry_cfg.get("choppiness_filter_period", 14)
        reason += (
            f", with its {choppiness_period}-day choppiness index at or below "
            f"{choppiness_threshold} (market judged to be trending, not choppy)"
        )
    return reason


def trend_exit_reason_text(cfg: dict) -> str:
    """
    Human-readable description of the trend-exit rule, if it fires.
    `exit.type` selects the wording, same pattern as `entry_reason_text`
    above — "ma_crossover" (default, v1-v10 behavior) or "donchian_low".
    """
    exit_cfg = cfg.get("exit", {})
    exit_type = exit_cfg.get("type", "ma_crossover")
    if exit_type == "donchian_low":
        exit_breakout_period = exit_cfg.get("exit_breakout_period", 10)
        return f"price closed below its {exit_breakout_period}-day low (Donchian exit)"
    return f"price closed back below its {cfg['entry']['ma_period']}-day moving average (trend exit)"


def generate_signals(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    Adds a 'signal' column: 'BUY', 'SELL', or None for each row, and a
    'reason' column with a human-readable explanation for each signal
    (used to build the trade journal — see strategy/journal.py).
    This only decides ENTRY and trend-based EXIT. Stop-loss / take-profit
    are handled by the backtester since they depend on the entry price of
    an open position, not just the indicator values.

    entry.type selects the entry rule: "ma_crossover" (default) or
    "donchian_breakout". exit.type independently selects the trend-exit
    rule: "ma_crossover" (default, v1-v10 behavior — price closes back
    below its own N-day moving average) or "donchian_low" (Turtle-style —
    price closes below its N-day low, a genuine new short-term low rather
    than a moving-average crossunder, which lets winners give back more
    before exiting; see config/strategy_v11_donchian_exit.yaml). The two
    are fully independent — a config can change either, both, or neither,
    same isolate-one-variable discipline as every other vN config.
    """
    df = add_indicators(df, cfg)
    entry_cfg = cfg["entry"]
    exit_cfg = cfg["exit"]
    entry_type = entry_cfg.get("type", "ma_crossover")

    df["signal"] = None
    df["reason"] = None

    above_ma = df["Close"] > df["ma"]
    below_ma = df["Close"] < df["ma"]

    if entry_cfg["volume_confirmation"]:
        vol_ok = df["Volume"] > df["volume_ma"]
    else:
        vol_ok = True

    if entry_type == "always":
        # Unconditional entry -- no timing filter at all, not even volume
        # confirmation. Buys back in on the very next eligible day after
        # any exit (or on day one), regardless of price/MA/volume state.
        # Exists purely to isolate a question: does the ENTRY rule add
        # value, or does all of this system's edge come from the
        # exit/stop/sizing machinery instead? Everything else (exits,
        # ATR sizing, pyramiding) is unchanged -- only the entry filter
        # is removed. See config/strategy_v21_always_in.yaml.
        buy_signal = pd.Series(True, index=df.index)
    elif entry_type == "donchian_breakout":
        # Buy whenever price closes above the highest high of the prior
        # breakout_period days — a genuine new price extreme, not a
        # smoothed average crossing. Unlike the MA rule below, this isn't
        # restricted to the FIRST day the condition is true: any day price
        # closes above that rolling threshold is a valid Turtle-style
        # breakout signal. That can't cause a duplicate entry — the
        # backtest engine and live runner both already skip tickers with
        # an open position.
        buy_signal = (df["Close"] > df["donchian_high"]) & vol_ok
    else:
        # Buy signal: price crosses above MA (wasn't above yesterday) + volume confirms
        crossed_up = above_ma & (~above_ma.shift(1).fillna(False))
        buy_signal = crossed_up & vol_ok

    # Regime filter (optional, see add_indicators) -- don't take the fast
    # entry signal unless price is ALSO above a much slower moving
    # average. Applied as an additional AND on top of whatever entry_type
    # produced, independent of which entry rule is active -- same
    # composability discipline as every other independent config knob.
    #
    # OR fallback for assets too new to have regime_filter_period days of
    # history yet: regime_ma is NaN for that entire stretch, and NaN
    # comparisons are always False in pandas -- without this fallback, a
    # newly-listed, more speculative asset would be fully locked out of
    # trading for its first ~regime_filter_period days, exactly the
    # window where its first big move is most likely to happen. Applied
    # as (regime confirms) OR (not enough history to judge it at all) --
    # an established asset still has to clear the filter; a brand-new one
    # falls back to the plain crossover+volume signal until it's old
    # enough to have an opinion.
    regime_filter_period = entry_cfg.get("regime_filter_period")
    if regime_filter_period:
        regime_confirmed = df["Close"] > df["regime_ma"]
        regime_unavailable = df["regime_ma"].isna()
        buy_signal = buy_signal & (regime_confirmed | regime_unavailable)

    # Choppiness filter (optional, see add_indicators) -- don't take the
    # entry signal unless the market is actually TRENDING right now
    # (low choppiness_index), independent of and in addition to whatever
    # the regime filter already decided about direction. Same composability
    # and OR-fallback discipline as the regime filter: an established
    # asset still has to clear the filter, an asset without
    # choppiness_filter_period days of history yet falls back to letting
    # the signal through rather than being permanently locked out.
    choppiness_threshold = entry_cfg.get("choppiness_threshold")
    if choppiness_threshold:
        trending_enough = df["choppiness_index"] <= choppiness_threshold
        choppiness_unavailable = df["choppiness_index"].isna()
        buy_signal = buy_signal & (trending_enough | choppiness_unavailable)

    # Trend-exit signal. exit.type selects HOW it's detected; exit.ma_exit
    # still gates whether any trend-exit is active at all (independent of
    # which type), same as before.
    exit_type = exit_cfg.get("type", "ma_crossover")
    if exit_cfg["ma_exit"]:
        if exit_type == "donchian_low":
            # Exit the first day price closes below the lowest Low of the
            # PRIOR exit_breakout_period days — a genuine new short-term
            # low, not a smoothed-average crossing. Structurally more
            # tolerant of ordinary pullbacks within an intact trend than
            # the MA-crossunder rule below, since price has to actually
            # revisit a real prior support level, not just dip under its
            # own trailing mean.
            below_low = df["Close"] < df["donchian_low"]
            crossed_below_low = below_low & (~below_low.shift(1).fillna(False))
            sell_signal = crossed_below_low
        else:
            crossed_down = below_ma & (~below_ma.shift(1).fillna(False))
            sell_signal = crossed_down
    else:
        sell_signal = pd.Series(False, index=df.index)

    df.loc[buy_signal, "signal"] = "BUY"
    df.loc[buy_signal, "reason"] = entry_reason_text(cfg)
    df.loc[sell_signal, "signal"] = "SELL"
    df.loc[sell_signal, "reason"] = trend_exit_reason_text(cfg)
    return df
