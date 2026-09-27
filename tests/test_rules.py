"""
Pins strategy/rules.py's MA entry / trend-exit behavior: signals fire on
ANY day the condition holds, not just the first day. That's the behavior
every documented strategy_master.yaml backtest was measured under -- it
used to depend on a pandas-3 quirk (see generate_signals), so these guard
against it silently changing again with a library upgrade or refactor.

Run: python -m pytest tests/
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strategy import rules

CFG = {
    "entry": {"ma_period": 20, "volume_confirmation": True, "volume_ma_period": 20},
    "exit": {"ma_exit": True, "type": "donchian_low", "exit_breakout_period": 10},
    "risk": {"atr_period": 20},
}
N_FLAT = 25


def _frame(close, volume):
    idx = pd.date_range("2026-01-01", periods=len(close), freq="B")
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": volume},
        index=idx,
    )


def test_ma_entry_fires_every_day_above_ma_with_volume():
    # Flat, then price jumps above the 20-day MA and STAYS there with high
    # volume -- the SOXL/TQQQ 2026-09 pattern. BUY on every one of those
    # days, not only the first.
    n_up = 6
    df = _frame([100.0] * N_FLAT + [110.0 + i for i in range(n_up)],
                [1_000] * N_FLAT + [5_000] * n_up)
    sig = rules.generate_signals(df, CFG)
    assert list(sig.index[sig["signal"] == "BUY"]) == list(df.index[N_FLAT:])


def test_ma_entry_needs_volume_confirmation():
    df = _frame([100.0] * N_FLAT + [110.0, 111.0], [1_000] * N_FLAT + [5_000, 10])
    sig = rules.generate_signals(df, CFG)
    assert list(sig.index[sig["signal"] == "BUY"]) == [df.index[N_FLAT]]


def test_donchian_exit_fires_every_day_below_prior_low():
    n_down = 4
    df = _frame([100.0] * N_FLAT + [90.0 - i for i in range(n_down)], [1_000] * (N_FLAT + n_down))
    sig = rules.generate_signals(df, CFG)
    assert list(sig.index[sig["signal"] == "SELL"]) == list(df.index[N_FLAT:])
