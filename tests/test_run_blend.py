"""
live/run_blend.py's pure planning logic: per-sleeve exits/entries and
netting overlapping orders into one per ticker.

Run: python -m pytest tests/
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "live"))
import run_blend  # noqa: E402

DIP = {"weight": 0.5, "tickers": ["SPY", "QQQ"], "max_position_pct": 49.5, "max_invested_pct": 99.0}
IDX = pd.date_range("2026-01-01", periods=3, freq="B")


@pytest.fixture
def fake_signals(monkeypatch):
    """Lets each test set the last-bar signal per ticker directly."""
    last = {}

    def signals(name, df, cfg):
        return pd.DataFrame({"signal": [None, None, last.get(df.attrs["ticker"])],
                             "reason": [None, None, "test"]}, index=IDX)
    monkeypatch.setattr(run_blend, "sleeve_signals", signals)
    return last


def _history(*tickers):
    out = {}
    for t in tickers:
        df = pd.DataFrame({"Close": [100.0, 100.0, 100.0]}, index=IDX)
        df.attrs["ticker"] = t
        out[t] = df
    return out


def test_dip_sleeve_exits_on_sell_and_sizes_new_entry(fake_signals):
    fake_signals.update({"SPY": "SELL", "QQQ": "BUY"})
    rows = [{"id": 1, "ticker": "SPY", "shares": 200.0, "entry_price": 95.0}]
    plan = run_blend.plan_sleeve("dip", DIP, 100_000, rows, _history("SPY", "QQQ"), {"SPY": 100.0, "QQQ": 100.0})
    assert [(x["ticker"], x["qty"]) for x in plan["exits"]] == [("SPY", 200.0)]
    # sleeve = $50,000; SPY's $20,000 is freed by the exit, so QQQ gets its
    # full 49.5% of the sleeve
    assert [(e["ticker"], e["usd"]) for e in plan["entries"]] == [("QQQ", pytest.approx(24_750.0))]


def test_entry_is_limited_by_the_sleeve_invested_cap(fake_signals):
    fake_signals.update({"SPY": None, "QQQ": "BUY"})
    rows = [{"id": 1, "ticker": "SPY", "shares": 400.0, "entry_price": 100.0}]  # $40k of the $50k sleeve
    plan = run_blend.plan_sleeve("dip", DIP, 100_000, rows, _history("SPY", "QQQ"), {"SPY": 100.0, "QQQ": 100.0})
    assert plan["exits"] == []
    # 99% of the $50k sleeve = $49,500 cap, minus $40k held -- tighter than
    # the $10k of cash left, same as the engine's room_left
    assert plan["entries"][0]["usd"] == pytest.approx(9_500.0)


def test_held_ticker_is_not_bought_again(fake_signals):
    fake_signals.update({"SPY": "BUY", "QQQ": None})
    rows = [{"id": 1, "ticker": "SPY", "shares": 10.0, "entry_price": 100.0}]
    plan = run_blend.plan_sleeve("dip", DIP, 100_000, rows, _history("SPY", "QQQ"), {"SPY": 100.0, "QQQ": 100.0})
    assert plan == {"exits": [], "entries": []}


def test_opposite_orders_in_one_ticker_are_netted():
    plans = {
        "dip": {"exits": [{"ticker": "SPY", "qty": 10.0}], "entries": []},
        "trend": {"exits": [], "entries": [{"ticker": "SPY", "usd": 600.0}]},
    }
    assert run_blend.net_orders(plans, {"SPY": 100.0}, {"SPY": 50.0}) == {"SPY": ("sell", 4.0)}


def test_orders_that_cancel_out_send_nothing():
    plans = {
        "dip": {"exits": [{"ticker": "SPY", "qty": 10.0}], "entries": []},
        "trend": {"exits": [], "entries": [{"ticker": "SPY", "usd": 1000.4}]},
    }
    assert run_blend.net_orders(plans, {"SPY": 100.0}, {"SPY": 50.0}) == {}


def test_sell_never_exceeds_the_account_position():
    plans = {"dip": {"exits": [{"ticker": "QQQ", "qty": 10.0000004}], "entries": []}}
    side, qty = run_blend.net_orders(plans, {"QQQ": 100.0}, {"QQQ": 10.0})["QQQ"]
    assert side == "sell" and qty <= 10.0
