"""
Manually closes an open Alpaca position for ONE specific ticker, on
demand -- not tied to the daily strategy signal at all. Built as a
faster, less error-prone alternative to Alpaca's own UI for "I just
want to exit this one position right now."

Mirrors live/run_live.py's own close-and-log pattern exactly (same
close_position() call, same per-unit Supabase trade closing) so a
manual close shows up in the trade history / dashboard identically to
an automatic one, just tagged with exit_reason="manual_close" instead
of "stop_loss"/"trend_exit"/"take_profit". A pyramided position closes
as a WHOLE STACK, same "the broker only ever sees one aggregate
position" invariant run_live.py already uses -- there's no partial-unit
close here, same as everywhere else in this project.

Usage:
    python live/close_position.py --ticker LINK-USD                # real close
    python live/close_position.py --ticker LINK-USD --dry-run      # show what it would do, close nothing
    python live/close_position.py --list                           # just list current positions, take no action
"""
import sys
import os
import datetime as dt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from strategy import journal
from broker.alpaca_client import AlpacaBroker


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    list_only = "--list" in args

    ticker = None
    if "--ticker" in args:
        idx = args.index("--ticker")
        if idx + 1 < len(args):
            ticker = args[idx + 1]

    broker = AlpacaBroker()
    positions = broker.get_positions()

    if list_only or not ticker:
        if not positions:
            print("No open positions.")
        else:
            print("Current open positions:")
            for t, p in positions.items():
                print(f"  {t}: qty={p['qty']}, avg_entry=${p['avg_entry_price']:,.2f}, "
                      f"market_value=${p['market_value']:,.2f}, unrealized={p['unrealized_plpc']:+.2f}%")
        if not ticker:
            print("\nUsage: python live/close_position.py --ticker TICKER [--dry-run]")
        return

    if ticker not in positions:
        print(f"ERROR: no open position in {ticker!r}.")
        if positions:
            print(f"Currently held: {sorted(positions.keys())}")
        else:
            print("No positions are currently open at all.")
        sys.exit(1)

    pos = positions[ticker]
    current_price = broker.get_latest_price(ticker)
    entry_price = pos["avg_entry_price"]
    change_pct = (current_price - entry_price) / entry_price * 100
    pnl = (current_price - entry_price) * pos["qty"]

    print(f"{'[DRY RUN] ' if dry_run else ''}Closing {ticker}:")
    print(f"  qty={pos['qty']}, avg_entry=${entry_price:,.2f}, current=${current_price:,.2f}")
    print(f"  market_value=${pos['market_value']:,.2f}, unrealized P&L={change_pct:+.2f}% (${pnl:+,.2f})")

    if dry_run:
        print("\nDry run -- no order placed, no records changed.")
        return

    order = broker.close_position(ticker)
    exit_reason = "manual_close"
    exit_reason_detail = "a manual close was requested directly (live/close_position.py), not a strategy signal"
    exit_log = journal.format_exit(ticker, current_price, change_pct, exit_reason_detail)
    print(f"\nOrder submitted: {order}")
    print(f"  {exit_log}")

    if os.environ.get("SUPABASE_URL"):
        from storage.supabase_client import SupabaseStore
        store = SupabaseStore()
        # Same "source=paper" convention live/run_live.py already uses
        # throughout, for consistency -- see that file if this project
        # ever moves to source="live".
        open_units = store.find_open_trades(ticker, source="paper")
        if not open_units:
            print(f"  Note: no open Supabase trade record(s) found for {ticker} -- "
                  f"the broker position is closed, but there's nothing here to mark closed.")
        for unit in open_units:
            unit_pnl = (current_price - unit["entry_price"]) * unit["shares"]
            unit_r = (
                unit_pnl / unit["initial_risk_dollars"]
                if unit.get("initial_risk_dollars") else None
            )
            store.close_trade(
                unit["id"], exit_date=dt.date.today(), exit_price=current_price,
                pnl=unit_pnl, return_pct=change_pct, exit_reason=exit_reason,
                exit_reason_detail=exit_reason_detail, exit_log=exit_log, r_multiple=unit_r,
            )
            store.save_signal(ticker, dt.date.today(), "SELL", current_price, reason=exit_reason_detail)
        print(f"  Closed {len(open_units)} Supabase trade record(s).")
    else:
        print("  Note: SUPABASE_URL not set -- broker position closed, but no trade record was updated.")


if __name__ == "__main__":
    main()
