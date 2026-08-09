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
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from data import fetcher
from strategy import rules, journal, correlation, portfolio_selection
from broker.alpaca_client import AlpacaBroker


def _stop_price_for_open_position(store, ticker, entry_price, qty, sizing_method, cfg):
    """
    Reconstructs the stop price for an already-open position, so the exit
    check works the same way live as it does in the backtester.

    Flat-% sizing (pct mode) is derivable from config alone. N-based sizing
    (atr_unit mode) fixed the stop at whatever N was on the day the
    position was opened, so it has to be looked up from the trade record
    Supabase saved at entry time — there's no way to recompute "N as of
    entry day" from today's data alone.
    """
    if sizing_method == "atr_unit":
        if store is None:
            return None  # no Supabase credentials — can't reconstruct, see caller
        open_trade = store.find_open_trade(ticker, source="paper")
        if open_trade and open_trade.get("initial_risk_dollars") and qty:
            risk_per_share = open_trade["initial_risk_dollars"] / qty
            return entry_price - risk_per_share
        return None

    stop_loss_pct = cfg["exit"].get("stop_loss_pct")
    return entry_price * (1 - stop_loss_pct / 100) if stop_loss_pct else None


def main():
    dry_run = "--dry-run" in sys.argv

    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "strategy.yaml")
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    tickers = portfolio_selection.universe_tickers(cfg)  # candidate_universe if portfolio_selection is on, else watchlist
    take_profit_pct = cfg["exit"].get("take_profit_pct")
    max_position_pct = cfg["risk"]["max_position_pct"] / 100
    max_invested_pct = cfg["risk"]["max_invested_pct"] / 100
    sizing_method = cfg["risk"].get("sizing_method", "pct")  # "pct" (v1-v4) or "atr_unit" (Turtle-style)

    correlation_cfg = cfg["risk"].get("correlation_breaker") or {}
    correlation_enabled = correlation_cfg.get("enabled", False)
    corr_lookback = correlation_cfg.get("lookback_period", 60)
    corr_threshold = correlation_cfg.get("correlation_threshold", 0.7)
    corr_max_correlated = correlation_cfg.get("max_correlated_positions", 2)

    ps_cfg = cfg.get("portfolio_selection") or {}
    ps_enabled = ps_cfg.get("enabled", False)
    ps_target_size = ps_cfg.get("target_size", 3)
    ps_min_avg_dollar_volume = ps_cfg.get("min_avg_dollar_volume", 0)
    ps_lookback = ps_cfg.get("lookback_period", 90)

    print(f"{'[DRY RUN] ' if dry_run else ''}Live check — {dt.date.today()}")

    broker = AlpacaBroker()
    account = broker.get_account()
    positions = broker.get_positions()
    print(f"Account equity: ${account['equity']:,.2f} | Cash: ${account['cash']:,.2f}")
    print(f"Open positions: {list(positions.keys()) or 'none'}")

    # Created whenever credentials exist, even in --dry-run, so N-based
    # stop reconstruction (see _stop_price_for_open_position) can still
    # READ prior trade records. Actual writes stay gated by `not dry_run`
    # at each call site below — dry-run never mutates Supabase.
    store = None
    if os.environ.get("SUPABASE_URL"):
        from storage.supabase_client import SupabaseStore
        store = SupabaseStore()
        if not dry_run:
            store.save_account_snapshot(
                equity=account["equity"], cash=account["cash"],
                portfolio_value=account["portfolio_value"], buying_power=account["buying_power"],
            )

    # Pull enough history for the MA/volume/ATR/portfolio-selection windows
    # to be valid (plus buffer)
    lookback_days = max(
        cfg["entry"]["ma_period"], cfg["entry"]["volume_ma_period"],
        cfg["entry"].get("breakout_period", 0),
        cfg["risk"].get("atr_period", 20),
        ps_lookback if ps_enabled else 0,
    ) + 30
    start = (dt.date.today() - dt.timedelta(days=lookback_days * 2)).isoformat()  # *2 for weekends/holidays
    end = dt.date.today().isoformat()

    actions = []
    # Price history cache, shared by the exit loop, the correlation breaker
    # check, and portfolio selection (which needs the FULL candidate
    # universe, not just currently-held tickers) -- fetched once per
    # ticker per run and reused everywhere below instead of re-fetching.
    # A value of None means the fetch failed for that ticker this run.
    price_history = {}

    def get_price_history(ticker):
        if ticker not in price_history:
            try:
                price_history[ticker] = fetcher.fetch(ticker, start, end, force_refresh=True, namespace="live")
            except RuntimeError as e:
                print(f"  Skipping {ticker}: {e}")
                price_history[ticker] = None
        return price_history[ticker]

    # exited_tickers tracks which of today's open positions just got closed
    # in this same cycle, so the correlation breaker check (further down)
    # only counts positions that are STILL open by the time entries are
    # considered.
    exited_tickers = set()

    # --- Check exits on open positions ---
    for ticker, pos in positions.items():
        if ticker not in tickers:
            continue  # position not managed by this strategy
        df = get_price_history(ticker)
        if df is None:
            continue

        sig_df = rules.generate_signals(df, cfg)
        current_price = df["Close"].iloc[-1]
        entry_price = pos["avg_entry_price"]
        change_pct = (current_price - entry_price) / entry_price * 100

        stop_price = _stop_price_for_open_position(store, ticker, entry_price, pos["qty"], sizing_method, cfg)
        if sizing_method == "atr_unit" and stop_price is None:
            print(f"  Note: {ticker} used N-based sizing but its stop couldn't be "
                  f"reconstructed (no Supabase trade record found) — stop-loss check skipped this run.")

        exit_reason = None
        trend_reason = None
        if stop_price is not None and current_price <= stop_price:
            exit_reason = "stop_loss"
        elif take_profit_pct and change_pct >= take_profit_pct:
            exit_reason = "take_profit"
        elif sig_df["signal"].iloc[-1] == "SELL":
            exit_reason = "trend_exit"
            trend_reason = sig_df["reason"].iloc[-1]

        if exit_reason:
            pnl = (current_price - entry_price) * pos["qty"]
            risk_per_share = (entry_price - stop_price) if stop_price is not None else None
            initial_risk_dollars = risk_per_share * pos["qty"] if risk_per_share else None
            r_multiple = pnl / initial_risk_dollars if initial_risk_dollars else None

            exit_reason_detail = journal.exit_reason_text(exit_reason, cfg, trend_reason=trend_reason)
            exit_log = journal.format_exit(ticker, current_price, change_pct, exit_reason_detail, r_multiple=r_multiple)
            print(f"  EXIT {ticker}: {change_pct:+.2f}% ({exit_reason})")
            print(f"    {exit_log}")
            actions.append(("SELL", ticker, exit_reason_detail, current_price))
            exited_tickers.add(ticker)
            if not dry_run:
                broker.close_position(ticker)
                if store:
                    open_trade = store.find_open_trade(ticker, source="paper")
                    if open_trade:
                        store.close_trade(
                            open_trade["id"], exit_date=dt.date.today(), exit_price=current_price,
                            pnl=pnl, return_pct=change_pct, exit_reason=exit_reason,
                            exit_reason_detail=exit_reason_detail, exit_log=exit_log, r_multiple=r_multiple,
                        )

    # --- Portfolio selection: which candidates are eligible for NEW
    # entries today (see strategy/portfolio_selection.py). Unlike the
    # backtester (which holds a selection fixed between quarterly
    # rebalance checkpoints to simulate realistic turnover), live mode
    # has no cross-run state to track a rebalance schedule against, so
    # it simply recomputes fresh from today's trailing data every run --
    # simplest correct thing, though it means live selections could in
    # principle change more often than the backtest's quarterly cadence
    # implies. Existing open positions are never force-closed by this;
    # it only gates NEW entries below. ---
    if ps_enabled:
        for ticker in tickers:
            get_price_history(ticker)
        universe_price_data = {t: df for t, df in price_history.items() if df is not None}
        if universe_price_data:
            ref_date = max(df.index[-1] for df in universe_price_data.values())
            active_tickers = set(portfolio_selection.select_portfolio(
                list(universe_price_data.keys()), universe_price_data, ref_date,
                ps_lookback, ps_min_avg_dollar_volume, ps_target_size,
            ))
        else:
            active_tickers = set()
        print(f"Portfolio selection: {sorted(active_tickers) or 'none'} "
              f"(from {len(universe_price_data)}/{len(tickers)} candidate(s) with usable data)")
    else:
        active_tickers = set(tickers)

    # --- Check entries for tickers not currently held ---
    for ticker in tickers:
        if ticker in positions:
            continue
        if ps_enabled and ticker not in active_tickers:
            continue
        df = get_price_history(ticker)
        if df is None:
            continue

        sig_df = rules.generate_signals(df, cfg)
        if sig_df["signal"].iloc[-1] != "BUY":
            continue

        if correlation_enabled:
            still_open = [t for t in positions if t in tickers and t not in exited_tickers]
            corr_count = correlation.correlated_position_count(
                ticker, still_open, price_history, df.index[-1], corr_lookback, corr_threshold
            )
            if corr_count >= corr_max_correlated:
                reason = correlation.breaker_reason(ticker, corr_count, corr_threshold, corr_max_correlated)
                print(f"  {journal.format_blocked(ticker, reason)}")
                continue

        current_price = df["Close"].iloc[-1]
        invested_value = sum(p["market_value"] for p in positions.values())
        portfolio_value = account["equity"]

        max_position_value = portfolio_value * max_position_pct
        room_left = (portfolio_value * max_invested_pct) - invested_value
        atr = sig_df["atr"].iloc[-1] if "atr" in sig_df.columns else None
        sizing_note = None
        risk_per_share = None

        if sizing_method == "atr_unit" and atr is not None and pd.notna(atr) and atr > 0:
            stop_atr_multiple = cfg["risk"]["stop_atr_multiple"]
            risk_pct_per_unit = cfg["risk"]["risk_pct_per_unit"]
            risk_per_share = stop_atr_multiple * atr
            dollar_risk_budget = portfolio_value * (risk_pct_per_unit / 100)
            atr_allocation = (dollar_risk_budget / risk_per_share) * current_price
            allocation = min(atr_allocation, max_position_value, room_left, account["cash"])
            sizing_note = (
                f"sized to risk {risk_pct_per_unit:.1f}% of equity "
                f"(N=${atr:.2f}, stop {stop_atr_multiple:.1f}N away)"
            )
        else:
            allocation = min(max_position_value, room_left, account["cash"])

        if allocation <= 1:  # not worth trading under $1
            print(f"  Skipping BUY {ticker}: no allocation room left")
            continue

        if risk_per_share is None:
            stop_loss_pct_cfg = cfg["exit"].get("stop_loss_pct")
            risk_per_share = current_price * (stop_loss_pct_cfg / 100) if stop_loss_pct_cfg else None
        initial_risk_dollars = risk_per_share * (allocation / current_price) if risk_per_share else None

        entry_reason = sig_df["reason"].iloc[-1]
        entry_log = journal.format_entry(ticker, current_price, entry_reason, sizing_note=sizing_note)
        print(f"  BUY {ticker}: ${allocation:,.2f} @ ~${current_price:.2f}")
        print(f"    {entry_log}")
        actions.append(("BUY", ticker, entry_reason, current_price))
        if not dry_run:
            broker.submit_market_order(ticker, notional_usd=allocation, side="buy")
            if store:
                shares = allocation / current_price
                store.open_trade(
                    ticker, entry_date=dt.date.today(), entry_price=current_price, shares=shares,
                    source="paper", entry_reason=entry_reason, entry_log=entry_log,
                    sizing_method=sizing_method, initial_risk_dollars=initial_risk_dollars,
                )

    if not actions:
        print("No actions today.")

    if store:
        for action_type, ticker, reason, price in actions:
            store.save_signal(ticker, dt.date.today(), action_type, price, reason=reason)
        print(f"Logged {len(actions)} action(s) to Supabase.")

    return actions


if __name__ == "__main__":
    main()
