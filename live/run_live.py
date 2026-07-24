"""
Runs one check-and-trade cycle against Alpaca paper trading:
  1. Pull recent price data for the watchlist
  2. Generate today's signal for each ticker (same rules.py as backtest)
  3. Check open Alpaca positions against exit rules (stop-loss / take-profit / trend-exit)
  4. Open new positions for tickers with a BUY signal, sized per config risk rules
  5. Log everything to Supabase if credentials are present

Meant to be run once per trading day, ideally shortly before market close
so the day's full price/volume data is available. Schedule it with cron,
a systemd timer, or GitHub Actions — see README for examples.

Usage:
    python live/run_live.py            # run for real (paper account)
    python live/run_live.py --dry-run  # show what it WOULD do, place no orders
"""
import sys
import os
import datetime as dt
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from data import fetcher
from strategy import rules
from broker.alpaca_client import AlpacaBroker


def main():
    dry_run = "--dry-run" in sys.argv

    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "strategy.yaml")
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    tickers = cfg["watchlist"]
    stop_loss_pct = cfg["exit"]["stop_loss_pct"]
    take_profit_pct = cfg["exit"].get("take_profit_pct")
    max_position_pct = cfg["risk"]["max_position_pct"] / 100
    max_invested_pct = cfg["risk"]["max_invested_pct"] / 100

    print(f"{'[DRY RUN] ' if dry_run else ''}Live check — {dt.date.today()}")

    broker = AlpacaBroker()
    account = broker.get_account()
    positions = broker.get_positions()
    print(f"Account equity: ${account['equity']:,.2f} | Cash: ${account['cash']:,.2f}")
    print(f"Open positions: {list(positions.keys()) or 'none'}")

    store = None
    if os.environ.get("SUPABASE_URL") and not dry_run:
        from storage.supabase_client import SupabaseStore
        store = SupabaseStore()
        store.save_account_snapshot(
            equity=account["equity"], cash=account["cash"],
            portfolio_value=account["portfolio_value"], buying_power=account["buying_power"],
        )

    # Pull enough history for the MA/volume windows to be valid (plus buffer)
    lookback_days = max(cfg["entry"]["ma_period"], cfg["entry"]["volume_ma_period"]) + 30
    start = (dt.date.today() - dt.timedelta(days=lookback_days * 2)).isoformat()  # *2 for weekends/holidays
    end = dt.date.today().isoformat()

    actions = []

    # --- Check exits on open positions ---
    for ticker, pos in positions.items():
        if ticker not in tickers:
            continue  # position not managed by this strategy
        try:
            df = fetcher.fetch(ticker, start, end, force_refresh=True, namespace="live")
        except RuntimeError as e:
            print(f"  Skipping {ticker}: {e}")
            continue

        sig_df = rules.generate_signals(df, cfg)
        current_price = df["Close"].iloc[-1]
        entry_price = pos["avg_entry_price"]
        change_pct = (current_price - entry_price) / entry_price * 100

        exit_reason = None
        if stop_loss_pct and change_pct <= -stop_loss_pct:
            exit_reason = "stop_loss"
        elif take_profit_pct and change_pct >= take_profit_pct:
            exit_reason = "take_profit"
        elif sig_df["signal"].iloc[-1] == "SELL":
            exit_reason = "trend_exit"

        if exit_reason:
            print(f"  EXIT {ticker}: {change_pct:+.2f}% ({exit_reason})")
            actions.append(("SELL", ticker, exit_reason, current_price))
            if not dry_run:
                broker.close_position(ticker)
                if store:
                    open_trade = store.find_open_trade(ticker, source="paper")
                    if open_trade:
                        pnl = (current_price - entry_price) * pos["qty"]
                        store.close_trade(
                            open_trade["id"], exit_date=dt.date.today(), exit_price=current_price,
                            pnl=pnl, return_pct=change_pct, exit_reason=exit_reason,
                        )

    # --- Check entries for tickers not currently held ---
    for ticker in tickers:
        if ticker in positions:
            continue
        try:
            df = fetcher.fetch(ticker, start, end, force_refresh=True, namespace="live")
        except RuntimeError as e:
            print(f"  Skipping {ticker}: {e}")
            continue

        sig_df = rules.generate_signals(df, cfg)
        if sig_df["signal"].iloc[-1] != "BUY":
            continue

        current_price = df["Close"].iloc[-1]
        invested_value = sum(p["market_value"] for p in positions.values())
        portfolio_value = account["equity"]

        max_position_value = portfolio_value * max_position_pct
        room_left = (portfolio_value * max_invested_pct) - invested_value
        allocation = min(max_position_value, room_left, account["cash"])

        if allocation <= 1:  # not worth trading under $1
            print(f"  Skipping BUY {ticker}: no allocation room left")
            continue

        print(f"  BUY {ticker}: ${allocation:,.2f} @ ~${current_price:.2f}")
        actions.append(("BUY", ticker, "signal", current_price))
        if not dry_run:
            broker.submit_market_order(ticker, notional_usd=allocation, side="buy")
            if store:
                shares = allocation / current_price
                store.open_trade(ticker, entry_date=dt.date.today(), entry_price=current_price, shares=shares, source="paper")

    if not actions:
        print("No actions today.")

    if store:
        for action_type, ticker, reason, price in actions:
            store.save_signal(ticker, dt.date.today(), action_type, price, reason=reason)
        print(f"Logged {len(actions)} action(s) to Supabase.")

    return actions


if __name__ == "__main__":
    main()
