"""
Daily check-and-trade cycle for the trend + dip-buy blend
(config/strategy_blend.yaml) on its OWN Alpaca paper account, alongside
live/run_live.py's master strategy on the original one.

Same rules the backtest measured (strategy/blend.py, shared with
strategy_lab.py), same timing: signals come from the last completed
daily bar, orders go in the next morning.

Two sleeves share one account, and both can trade SPY/QQQ, so Alpaca
alone can't say which sleeve owns what. Each sleeve's positions are
tracked in Supabase (trades.strategy = 'blend_trend' / 'blend_dip'), and
orders for the same ticker are NETTED into one order per run -- a sell
from one sleeve and a buy from the other in the same ticker would
otherwise be rejected as a potential wash trade (what crashed master's
2026-09-24 run).

Credentials: ALPACA_BLEND_API_KEY / ALPACA_BLEND_SECRET_KEY (the second
paper account) -- deliberately separate names, and it refuses to run if
they're missing or equal to master's keys. SUPABASE_URL /
SUPABASE_SERVICE_KEY are required: without the sleeve records it can't
know what it owns.

Usage:
    python live/run_blend.py             # trade (paper)
    python live/run_blend.py --dry-run   # show what it WOULD do; no orders, no writes
"""
import datetime as dt
import math
import os
import sys

import pandas as pd
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from data import fetcher
from strategy import blend

SLEEVE_TAGS = {"trend": "blend_trend", "dip": "blend_dip"}
MIN_ORDER_USD = 1.0


def sleeve_tickers(name, cfg):
    return cfg["universe"] if name == "trend" else cfg["tickers"]


def sleeve_signals(name, df, cfg):
    return blend.trend_signals(df, cfg) if name == "trend" else blend.dip_signals(df, cfg)


def plan_sleeve(name, cfg, equity, open_rows, history, prices):
    """
    Decides one sleeve's exits and entries -- pure logic, no I/O, so it's
    unit-testable. Mirrors backtest/engine.py's next_open bookkeeping for
    a sleeve sized as `weight` of total equity:
      exits:   held tickers whose last completed bar signals SELL
      entries: unheld tickers signalling BUY, sized
               min(sleeve * position weight, room under the invested cap,
                   sleeve cash left)
    Returns {"exits": [...], "entries": [...]}.
    """
    budget = cfg["weight"] * equity
    held = {}
    for row in open_rows:
        held.setdefault(row["ticker"], []).append(row)
    value = {t: sum(r["shares"] for r in rows) * prices[t] for t, rows in held.items() if t in prices}
    invested = sum(value.values())

    exits, entries = [], []
    for ticker, rows in held.items():
        df = history.get(ticker)
        if df is None or ticker not in prices:
            continue
        sig = sleeve_signals(name, df, cfg).iloc[-1]
        if sig["signal"] == "SELL":
            exits.append({"ticker": ticker, "rows": rows, "qty": sum(r["shares"] for r in rows),
                          "reason": sig["reason"]})
            invested -= value[ticker]

    cash_left = budget - invested
    cap = budget * cfg["max_invested_pct"] / 100
    for ticker in sleeve_tickers(name, cfg):
        if ticker in held:
            continue
        df = history.get(ticker)
        if df is None or ticker not in prices:
            continue
        sig = sleeve_signals(name, df, cfg).iloc[-1]
        if sig["signal"] != "BUY":
            continue
        weight = blend.trend_weight(df, cfg) if name == "trend" else cfg["max_position_pct"] / 100
        if weight is None:
            continue
        allocation = min(budget * weight, cap - invested, cash_left)
        if allocation < MIN_ORDER_USD:
            continue
        entries.append({"ticker": ticker, "usd": allocation, "reason": sig["reason"], "weight": weight})
        invested += allocation
        cash_left -= allocation
    return {"exits": exits, "entries": entries}


def net_orders(plans, prices, broker_qty):
    """
    Collapses every sleeve's exits and entries into ONE order per ticker.
    Returns {ticker: ("buy", usd) | ("sell", qty)}; tickers whose sells
    and buys cancel out to under $1 get no order at all (the sleeve
    records still change hands at the current price). Sell qty is capped
    at what the account actually holds.
    """
    sell_qty, buy_usd = {}, {}
    for plan in plans.values():
        for x in plan["exits"]:
            sell_qty[x["ticker"]] = sell_qty.get(x["ticker"], 0.0) + x["qty"]
        for e in plan["entries"]:
            buy_usd[e["ticker"]] = buy_usd.get(e["ticker"], 0.0) + e["usd"]
    orders = {}
    for ticker in set(sell_qty) | set(buy_usd):
        net_usd = buy_usd.get(ticker, 0.0) - sell_qty.get(ticker, 0.0) * prices[ticker]
        if net_usd >= MIN_ORDER_USD:
            orders[ticker] = ("buy", round(net_usd, 2))
        elif net_usd <= -MIN_ORDER_USD:
            qty = min(-net_usd / prices[ticker], broker_qty.get(ticker, 0.0))
            if qty >= 1e-6:
                orders[ticker] = ("sell", math.floor(qty * 1e6) / 1e6)  # never round UP past what's held
    return orders


def main():
    dry_run = "--dry-run" in sys.argv
    cfg_path = os.environ.get("BLEND_CONFIG", os.path.join(os.path.dirname(__file__), "..", "config", "strategy_blend.yaml"))
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    sleeves = {name: cfg[name] for name in SLEEVE_TAGS}

    api_key = os.environ.get("ALPACA_BLEND_API_KEY")
    secret_key = os.environ.get("ALPACA_BLEND_SECRET_KEY")
    if not api_key or not secret_key:
        sys.exit("ALPACA_BLEND_API_KEY / ALPACA_BLEND_SECRET_KEY not set -- the blend needs its own paper account.")
    if api_key == os.environ.get("ALPACA_API_KEY"):
        sys.exit("ALPACA_BLEND_API_KEY is the same as master's ALPACA_API_KEY -- refusing to trade the blend "
                 "on master's account.")

    from broker.alpaca_client import AlpacaBroker
    broker = AlpacaBroker(api_key=api_key, secret_key=secret_key, paper=True)

    store = None
    if os.environ.get("SUPABASE_URL"):
        from storage.supabase_client import SupabaseStore
        store = SupabaseStore(strategy="blend")
    elif not dry_run:
        sys.exit("SUPABASE_URL not set -- the blend can't trade without its sleeve records.")

    print(f"{'[DRY RUN] ' if dry_run else ''}Blend check -- {dt.date.today()} ({cfg_path})")
    account = broker.get_account()
    positions = broker.get_positions()
    equity = account["equity"]
    print(f"Account equity: ${equity:,.2f} | Cash: ${account['cash']:,.2f}")
    if store and not dry_run:
        store.save_account_snapshot(equity=equity, cash=account["cash"], portfolio_value=account["portfolio_value"],
                                    buying_power=account["buying_power"])

    if not broker.is_market_open("SPY"):
        print("Market is closed -- orders would queue and fill at an unknown open price. Not trading.")
        return

    tickers = sorted({t for name, c in sleeves.items() for t in sleeve_tickers(name, c)})
    lookback = max(c.get("ma_period", 0) for c in sleeves.values()) + 30
    lookback = max(lookback, max(c.get("trend_ma_period", 0) for c in sleeves.values()) + 30)
    start = (dt.date.today() - dt.timedelta(days=lookback * 2)).isoformat()
    end = dt.date.today().isoformat()
    history, prices = {}, {}
    for t in tickers:
        try:
            history[t] = fetcher.fetch(t, start, end, force_refresh=True, namespace="live_blend")
        except Exception as e:
            print(f"  Skipping {t}: no price history ({e})")
            continue
        try:
            prices[t] = broker.get_latest_price(t)
        except Exception as e:
            prices[t] = float(history[t]["Close"].iloc[-1])
            print(f"  Note: live quote for {t} unavailable ({e}) -- using last close ${prices[t]:.2f}")

    open_rows = {name: (store.find_all_open_trades(tag) if store else []) for name, tag in SLEEVE_TAGS.items()}

    # Sleeve records vs what the account really holds -- they only drift
    # if an order failed after being recorded or someone traded by hand.
    recorded = {}
    for rows in open_rows.values():
        for r in rows:
            recorded[r["ticker"]] = recorded.get(r["ticker"], 0.0) + r["shares"]
    for t in set(recorded) | set(positions):
        have, want = positions.get(t, {}).get("qty", 0.0), recorded.get(t, 0.0)
        if abs(have - want) > max(0.01 * max(have, want), 1e-6):
            print(f"  WARNING {t}: account holds {have:.6f} sh but sleeve records say {want:.6f} -- check manually")

    plans = {name: plan_sleeve(name, c, equity, open_rows[name], history, prices) for name, c in sleeves.items()}
    for name, plan in plans.items():
        for x in plan["exits"]:
            print(f"  [{name}] SELL {x['ticker']} {x['qty']:.6f} sh @ ~${prices[x['ticker']]:.2f} -- {x['reason']}")
        for e in plan["entries"]:
            print(f"  [{name}] BUY {e['ticker']} ${e['usd']:,.2f} @ ~${prices[e['ticker']]:.2f} -- {e['reason']}")
    if not any(p["exits"] or p["entries"] for p in plans.values()):
        print("No actions today.")
        return

    broker_qty = {t: p["qty"] for t, p in positions.items()}
    orders = net_orders(plans, prices, broker_qty)
    failed = {}
    for ticker, (side, amount) in sorted(orders.items()):
        print(f"  ORDER {ticker}: {side} {'$' if side == 'buy' else ''}{amount}{'' if side == 'buy' else ' sh'}")
        if dry_run:
            continue
        try:
            if side == "buy":
                broker.submit_market_order(ticker, notional_usd=amount, side="buy")
            else:
                broker.submit_market_order(ticker, qty=amount, side="sell")
        except Exception as e:
            print(f"  ORDER FAILED {ticker}: {e}")
            failed[ticker] = str(e)

    if dry_run or not store:
        return

    today = dt.date.today()
    recorded_count = 0
    for name, plan in plans.items():
        tag = SLEEVE_TAGS[name]
        for x in plan["exits"]:
            if x["ticker"] in failed:
                continue
            px = prices[x["ticker"]]
            for r in x["rows"]:
                ret = (px - r["entry_price"]) / r["entry_price"] * 100
                store.close_trade(r["id"], exit_date=today, exit_price=px, pnl=(px - r["entry_price"]) * r["shares"],
                                  return_pct=ret, exit_reason=f"{name}_exit", exit_reason_detail=x["reason"],
                                  exit_log=f"Exited {x['ticker']} at ${px:.2f} ({ret:+.2f}%): {x['reason']}.")
            store.save_signal(x["ticker"], today, "SELL", px, reason=x["reason"])
            recorded_count += 1
        for e in plan["entries"]:
            if e["ticker"] in failed:
                continue
            px = prices[e["ticker"]]
            store.open_trade(e["ticker"], entry_date=today, entry_price=px, shares=e["usd"] / px, source="paper",
                             entry_reason=e["reason"], sizing_method=f"blend_{name}",
                             entry_log=f"Entered {e['ticker']} at ${px:.2f} ({e['weight'] * 100:.1f}% of the "
                                       f"{name} sleeve): {e['reason']}.",
                             strategy=tag)
            store.save_signal(e["ticker"], today, "BUY", px, reason=e["reason"])
            recorded_count += 1
    print(f"Recorded {recorded_count} action(s) to Supabase.")

    if failed:
        print(f"\n{len(failed)} order(s) FAILED:")
        for t, err in failed.items():
            print(f"  {t}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
