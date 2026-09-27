"""
Pins backtest/engine.py's execution timing: "signal_close" fills at the
signal bar's own close, "next_open" fills at the following bar's open.

Run: python -m pytest tests/
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtest import engine

IDX = pd.date_range("2026-01-05", periods=6, freq="B")
# Open deliberately differs from the prior Close (an overnight gap) so the
# two execution modes can't accidentally produce the same fill.
PRICES = pd.DataFrame({
    "Open":   [100.0, 101.0, 106.0, 108.0, 112.0, 115.0],
    "High":   [101.0, 105.0, 108.0, 111.0, 114.0, 116.0],
    "Low":    [99.0, 100.0, 105.0, 107.0, 110.0, 113.0],
    "Close":  [100.0, 104.0, 107.0, 110.0, 113.0, 114.0],
    "Volume": [1_000] * 6,
}, index=IDX)
SIGNALS = pd.DataFrame({
    "signal": [None, "BUY", None, "SELL", None, None],
    "reason": [None, "test buy", None, "test sell", None, None],
    "atr":    [2.0] * 6,
}, index=IDX)


def _cfg(execution, commission_pct=0.0):
    return {
        "backtest": {"starting_cash": 10_000, "start_date": "2026-01-05",
                     "commission_pct": commission_pct, "execution": execution},
        "exit": {"take_profit_pct": None, "stop_loss_pct": None},
        "risk": {"max_position_pct": 50.0, "max_invested_pct": 100.0, "sizing_method": "pct"},
    }


def _only_trade(execution, commission_pct=0.0):
    result = engine.run_backtest({"X": PRICES}, {"X": SIGNALS}, _cfg(execution, commission_pct))
    assert len(result["trades"]) == 1
    return result["trades"][0], result


def test_signal_close_fills_at_the_signal_bars_close():
    trade, _ = _only_trade("signal_close")
    assert (trade["entry_date"], trade["entry_price"]) == (IDX[1], 104.0)
    assert (trade["exit_date"], trade["exit_price"]) == (IDX[3], 110.0)


def test_next_open_fills_at_the_following_bars_open():
    trade, _ = _only_trade("next_open")
    assert (trade["entry_date"], trade["entry_price"]) == (IDX[2], 106.0)
    assert (trade["exit_date"], trade["exit_price"]) == (IDX[4], 112.0)


def test_next_open_equity_marks_the_real_holding_each_night():
    trade, result = _only_trade("next_open")
    eq = result["equity_curve"]["portfolio_value"]
    shares = trade["shares"]
    assert eq.loc[IDX[1]] == pytest.approx(10_000)           # BUY decided, nothing bought yet
    assert eq.loc[IDX[2]] == pytest.approx(10_000 + shares * (107.0 - 106.0))
    assert eq.loc[IDX[5]] == pytest.approx(10_000 + trade["pnl"])  # flat after the exit


def test_commission_applies_on_both_sides_in_next_open():
    trade, result = _only_trade("next_open", commission_pct=0.1)
    shares = trade["shares"]
    expected = 10_000 + shares * (112.0 - 106.0) - shares * 106.0 * 0.001 - shares * 112.0 * 0.001
    assert result["equity_curve"]["portfolio_value"].iloc[-1] == pytest.approx(expected, rel=1e-12)


def test_unknown_execution_mode_is_rejected():
    with pytest.raises(ValueError):
        engine.run_backtest({"X": PRICES}, {"X": SIGNALS}, _cfg("next_close"))


def _long_frame(n=80, daily_move=0.01):
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    # alternating +/- moves: steady, known realized volatility
    close = 100 * pd.Series([(1 + daily_move) if i % 2 else (1 - daily_move) for i in range(n)]).cumprod().values
    df = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": [1_000] * n}, index=idx)
    sig = pd.DataFrame({"signal": [None] * n, "reason": [None] * n, "atr": [1.0] * n}, index=idx)
    return idx, df, sig


def test_inverse_vol_sizes_to_target_over_realized_vol():
    idx, df, sig = _long_frame()
    sig.loc[idx[70], ["signal", "reason"]] = ["BUY", "test"]
    cfg = _cfg("signal_close")
    cfg["backtest"]["start_date"] = "2025-01-01"
    cfg["risk"].update(sizing_method="inverse_vol", max_position_pct=100.0,
                       inverse_vol={"target_position_vol_pct": 4.0, "lookback_days": 60})
    result = engine.run_backtest({"X": df}, {"X": sig}, cfg)
    realized = df["Close"].pct_change().rolling(60).std().iloc[70] * (252 ** 0.5)
    position_value = result["equity_curve"]["portfolio_value"].iloc[70] - result["equity_curve"]["cash"].iloc[70]
    assert position_value / 10_000 == pytest.approx(0.04 / realized, rel=1e-9)


def test_vol_target_only_throttles_new_buys():
    idx, df, sig = _long_frame(daily_move=0.02)  # ~32% annual vol
    sig.loc[idx[5], ["signal", "reason"]] = ["BUY", "test"]
    sig.loc[idx[60], ["signal", "reason"]] = ["SELL", "test"]
    sig.loc[idx[70], ["signal", "reason"]] = ["BUY", "test"]

    def entry_values(vol_target):
        cfg = _cfg("signal_close")
        cfg["backtest"]["start_date"] = "2025-01-01"
        cfg["risk"]["max_position_pct"] = 100.0
        if vol_target:
            cfg["risk"]["vol_target"] = {"enabled": True, "target_annual_pct": vol_target, "lookback_days": 20}
        eq = engine.run_backtest({"X": df}, {"X": sig}, cfg)["equity_curve"]
        return [(eq["portfolio_value"] - eq["cash"]).iloc[i] / eq["portfolio_value"].iloc[i] for i in (5, 70)]

    plain = entry_values(None)
    targeted = entry_values(8.0)
    assert targeted[0] == pytest.approx(plain[0])   # too little history yet: full size
    assert targeted[1] < 0.5 * plain[1]              # account running ~4x hotter than target: much smaller
