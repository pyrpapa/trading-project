"""
Simulates the strategy over historical data, day by day, applying:
- entry/exit signals from strategy/rules.py
- stop-loss / take-profit (config-driven, checked every day a position is open)
- position sizing and max-invested caps (config-driven)

Outputs a full trade log and summary performance metrics.
"""
import pandas as pd
import numpy as np

from strategy import journal, correlation, portfolio_selection


class Position:
    """
    A single UNIT. A ticker with pyramiding enabled can have several Positions
    open at once (a "stack") -- see open_positions in run_backtest(), which
    maps ticker -> list[Position] rather than ticker -> Position so each
    pyramid unit keeps its own entry price/shares/risk for R-multiple
    accounting (Van Tharp convention: R is per-unit, not per-ticker), while
    stop_price is kept IDENTICAL across every unit in a stack (see the
    pyramid-add block in run_backtest(), which syncs it) so the whole stack
    exits together.
    """
    def __init__(
        self, ticker, entry_date, entry_price, shares, entry_reason=None, entry_log=None,
        stop_price=None, initial_risk_dollars=None, sizing_method="pct", unit_number=1,
    ):
        self.ticker = ticker
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.shares = shares
        self.entry_reason = entry_reason
        self.entry_log = entry_log
        self.stop_price = stop_price                    # None means no stop-loss configured
        self.initial_risk_dollars = initial_risk_dollars  # "1R" for this trade, in dollars
        self.sizing_method = sizing_method
        self.unit_number = unit_number                  # 1 = original entry, 2+ = pyramid adds

    def value(self, price):
        return self.shares * price


def run_backtest(price_data: dict, signals: dict, cfg: dict) -> dict:
    """
    price_data: {ticker: DataFrame with OHLCV}
    signals:    {ticker: DataFrame with 'signal' column, same index as price_data}
    cfg:        parsed strategy.yaml

    Returns dict with 'trades' (list of closed trades) and 'metrics' (summary stats)
    and 'equity_curve' (DataFrame of portfolio value over time).
    """
    starting_cash = cfg["backtest"]["starting_cash"]
    commission_pct = cfg["backtest"].get("commission_pct", 0.0) / 100
    take_profit_pct = cfg["exit"].get("take_profit_pct")
    take_profit_pct = take_profit_pct / 100 if take_profit_pct else None
    max_position_pct = cfg["risk"]["max_position_pct"] / 100
    max_invested_pct = cfg["risk"]["max_invested_pct"] / 100
    sizing_method = cfg["risk"].get("sizing_method", "pct")  # "pct" (v1-v4) or "atr_unit" (Turtle-style)

    # Pyramiding (Turtle-style: add units to an already-open, winning
    # position as price moves further in its favor). Requires atr_unit
    # sizing since the add-trigger and the re-sizing of each new unit are
    # both N-based -- silently a no-op under flat-% sizing, same pattern as
    # the other risk.* feature blocks below. Disabled unless a config
    # explicitly opts in via risk.pyramiding.enabled.
    pyramid_cfg = cfg["risk"].get("pyramiding") or {}
    pyramiding_enabled = pyramid_cfg.get("enabled", False) and sizing_method == "atr_unit"
    pyramid_unit_interval_n = pyramid_cfg.get("unit_interval_n", 0.5)
    pyramid_max_units = pyramid_cfg.get("max_units", 4)

    # Correlation-based circuit breaker (see strategy/correlation.py) — a
    # portfolio-level check on top of per-position sizing. Disabled unless
    # a config explicitly opts in via risk.correlation_breaker.enabled.
    correlation_cfg = cfg["risk"].get("correlation_breaker") or {}
    correlation_enabled = correlation_cfg.get("enabled", False)
    corr_lookback = correlation_cfg.get("lookback_period", 60)
    corr_threshold = correlation_cfg.get("correlation_threshold", 0.7)
    corr_max_correlated = correlation_cfg.get("max_correlated_positions", 2)

    # Portfolio selection (see strategy/portfolio_selection.py) -- chooses
    # WHICH tickers are even eligible for new entries, re-evaluated on a
    # rebalance schedule using only trailing data (no lookahead). When
    # disabled, every ticker in price_data is always eligible (v1-v6
    # behavior, unchanged).
    ps_cfg = cfg.get("portfolio_selection") or {}
    ps_enabled = ps_cfg.get("enabled", False)
    ps_candidates = ps_cfg.get("candidate_universe", [])
    ps_target_size = ps_cfg.get("target_size", 3)
    ps_min_avg_dollar_volume = ps_cfg.get("min_avg_dollar_volume", 0)
    ps_lookback = ps_cfg.get("lookback_period", 90)
    ps_rebalance_months = ps_cfg.get("rebalance_frequency_months", 3)

    # Union of all trading dates across tickers, restricted to the actual
    # requested backtest window. price_data itself may contain extra
    # history BEFORE start_date (see run_backtest.py) so rolling indicators
    # (MA/ATR/Donchian) and portfolio-selection's liquidity/correlation
    # lookback already have a full window by day one of the simulation
    # instead of warming up during it -- but the simulation (trades, equity
    # curve, rebalances) should only actually run over the configured
    # period, not the warm-up buffer.
    sim_start = pd.Timestamp(cfg["backtest"]["start_date"])
    all_dates = sorted(set.union(*[set(df.index) for df in price_data.values()]))
    all_dates = [d for d in all_dates if d >= sim_start]

    cash = starting_cash
    open_positions = {}  # ticker -> list[Position] (a "stack" -- len 1 unless pyramiding)
    closed_trades = []
    blocked_signals = []  # BUY signals the circuit breaker skipped
    rebalance_log = []    # portfolio selection's rebalance history
    pyramid_log = []      # pyramid-add events (see the pyramid-add block below)
    active_tickers = set(price_data.keys()) if not ps_enabled else set()
    next_rebalance_date = all_dates[0] if (ps_enabled and all_dates) else None
    equity_curve = []

    for date in all_dates:
        # Portfolio selection rebalance check -- happens BEFORE the day's
        # exits/entries, using only price history up to (and including)
        # `date`, so there's no lookahead. Existing open positions in a
        # ticker that drops out of the active set are NOT force-closed --
        # they're still managed normally by the exit checks below and
        # left to exit on their own stop/trend-exit/take-profit. Only
        # NEW entries are restricted to the active set.
        if ps_enabled and next_rebalance_date is not None and date >= next_rebalance_date:
            selected = portfolio_selection.select_portfolio(
                ps_candidates, price_data, date, ps_lookback, ps_min_avg_dollar_volume, ps_target_size,
            )
            previous_active = active_tickers
            active_tickers = set(selected)
            rebalance_log.append({
                "date": date,
                "selected": selected,
                "added": sorted(active_tickers - previous_active),
                "dropped": sorted(previous_active - active_tickers),
            })
            next_rebalance_date = date + pd.DateOffset(months=ps_rebalance_months)

        # Mark-to-market portfolio value at start of day
        invested_value = sum(
            pos.value(price_data[t].loc[date, "Close"])
            for t, stack in open_positions.items()
            for pos in stack
            if date in price_data[t].index
        )
        portfolio_value = cash + invested_value

        # --- Check exits first (stop-loss, take-profit, trend-exit signal) ---
        # A stack (1 unit, or several if pyramided) always exits TOGETHER --
        # one stop level and one trend-exit signal govern the whole ticker,
        # never per-unit. Each unit still becomes its own closed-trade record
        # with its own entry price/shares/R-multiple (Van Tharp convention:
        # R is per-unit, not per-ticker).
        for ticker in list(open_positions.keys()):
            df = price_data[ticker]
            if date not in df.index:
                continue
            stack = open_positions[ticker]
            price = df.loc[date, "Close"]

            exit_reason = None
            trend_reason = None
            # Stop-loss check works the same way regardless of sizing method —
            # stack[0].stop_price is kept in sync across every unit in the
            # stack (see the pyramid-add block below, which trails it up
            # whenever a new unit is added), so checking unit 0 is checking
            # the whole stack's current stop.
            stack_stop = stack[0].stop_price
            if stack_stop is not None and price <= stack_stop:
                exit_reason = "stop_loss"
            elif take_profit_pct:
                total_shares = sum(p.shares for p in stack)
                avg_entry_price = sum(p.entry_price * p.shares for p in stack) / total_shares
                change_pct = (price - avg_entry_price) / avg_entry_price
                if change_pct >= take_profit_pct:
                    exit_reason = "take_profit"
            if exit_reason is None and ticker in signals and date in signals[ticker].index:
                if signals[ticker].loc[date, "signal"] == "SELL":
                    exit_reason = "trend_exit"
                    trend_reason = signals[ticker].loc[date, "reason"]

            if exit_reason:
                for pos in stack:
                    unit_change_pct = (price - pos.entry_price) / pos.entry_price
                    proceeds = pos.shares * price * (1 - commission_pct)
                    cash += proceeds
                    return_pct = unit_change_pct * 100
                    pnl = proceeds - (pos.shares * pos.entry_price)
                    r_multiple = (
                        pnl / pos.initial_risk_dollars
                        if pos.initial_risk_dollars else None
                    )
                    exit_reason_detail = journal.exit_reason_text(exit_reason, cfg, trend_reason=trend_reason)
                    closed_trades.append({
                        "ticker": ticker,
                        "entry_date": pos.entry_date,
                        "entry_price": pos.entry_price,
                        "exit_date": date,
                        "exit_price": price,
                        "shares": pos.shares,
                        "pnl": pnl,
                        "return_pct": return_pct,
                        "exit_reason": exit_reason,
                        "entry_reason": pos.entry_reason,
                        "entry_log": pos.entry_log,
                        "exit_reason_detail": exit_reason_detail,
                        "exit_log": journal.format_exit(ticker, price, return_pct, exit_reason_detail, r_multiple=r_multiple),
                        "sizing_method": pos.sizing_method,
                        "initial_risk_dollars": pos.initial_risk_dollars,
                        "r_multiple": r_multiple,
                        "unit_number": pos.unit_number,
                        "units_in_stack": len(stack),
                    })
                del open_positions[ticker]

        # Recompute invested value after exits
        invested_value = sum(
            pos.value(price_data[t].loc[date, "Close"])
            for t, stack in open_positions.items()
            for pos in stack
            if date in price_data[t].index
        )
        portfolio_value = cash + invested_value

        # --- Check pyramid adds (existing open stacks only) ---
        # This is a PURE PRICE THRESHOLD check, not a fresh entry signal --
        # it runs regardless of what today's BUY/SELL signal says, same as
        # the stop-loss/take-profit checks above. Classic Turtle rule: add
        # one more unit every unit_interval_n * N the price moves further in
        # the position's favor since the LAST unit's own entry, up to
        # max_units total, re-sizing each new unit at CURRENT volatility (N)
        # and trailing the WHOLE stack's stop up (never down) to the new
        # unit's stop level every time a unit is added.
        if pyramiding_enabled:
            for ticker in list(open_positions.keys()):
                stack = open_positions[ticker]
                if len(stack) >= pyramid_max_units:
                    continue
                df = price_data[ticker]
                if date not in df.index:
                    continue
                sig_df = signals.get(ticker)
                if sig_df is None or date not in sig_df.index:
                    continue
                atr = sig_df.loc[date, "atr"] if "atr" in sig_df.columns else None
                if atr is None or pd.isna(atr) or atr <= 0:
                    continue
                price = df.loc[date, "Close"]
                if pd.isna(price):
                    continue

                last_unit = stack[-1]
                threshold_price = last_unit.entry_price + pyramid_unit_interval_n * atr
                if price < threshold_price:
                    continue

                invested_value = sum(
                    pos.value(price_data[t].loc[date, "Close"])
                    for t, s in open_positions.items()
                    for pos in s
                    if date in price_data[t].index
                )
                portfolio_value = cash + invested_value
                max_position_value = portfolio_value * max_position_pct
                stack_value = sum(p.value(price) for p in stack)
                room_in_position = max_position_value - stack_value
                room_left = (portfolio_value * max_invested_pct) - invested_value

                stop_atr_multiple = cfg["risk"]["stop_atr_multiple"]
                risk_pct_per_unit = cfg["risk"]["risk_pct_per_unit"]
                risk_per_share = stop_atr_multiple * atr
                dollar_risk_budget = portfolio_value * (risk_pct_per_unit / 100)
                atr_allocation = (dollar_risk_budget / risk_per_share) * price
                allocation = min(atr_allocation, room_in_position, room_left, cash)
                if allocation <= 0:
                    continue

                shares = allocation / price
                cost = shares * price * (1 + commission_pct)
                if cost > cash or shares <= 0:
                    continue

                new_unit_stop = price - risk_per_share
                # Trail the whole stack's stop up to the new unit's stop
                # level -- but only up, never down (stack[0].stop_price is
                # the stop every unit shares; see the exit check above).
                synced_stop = max(stack[0].stop_price, new_unit_stop) if stack[0].stop_price is not None else new_unit_stop
                for p in stack:
                    p.stop_price = synced_stop

                unit_number = len(stack) + 1
                initial_risk_dollars = risk_per_share * shares
                sizing_note = (
                    f"pyramid unit sized to risk {risk_pct_per_unit:.1f}% of equity "
                    f"(N=${atr:.2f}, stop {stop_atr_multiple:.1f}N away)"
                )
                add_reason = journal.pyramid_add_reason_text(unit_number, pyramid_max_units, pyramid_unit_interval_n)
                add_log = journal.format_pyramid_add(ticker, unit_number, pyramid_max_units, price, sizing_note=sizing_note)

                cash -= cost
                stack.append(Position(
                    ticker, date, price, shares, add_reason, add_log,
                    synced_stop, initial_risk_dollars, sizing_method, unit_number=unit_number,
                ))
                pyramid_log.append({
                    "date": date, "ticker": ticker, "unit_number": unit_number,
                    "price": price, "shares": shares, "log": add_log,
                })

            # Recompute invested value after pyramid adds
            invested_value = sum(
                pos.value(price_data[t].loc[date, "Close"])
                for t, stack in open_positions.items()
                for pos in stack
                if date in price_data[t].index
            )
            portfolio_value = cash + invested_value

        # --- Check entries ---
        for ticker, sig_df in signals.items():
            if ticker in open_positions:
                continue
            if ps_enabled and ticker not in active_tickers:
                continue
            if date not in sig_df.index:
                continue
            if sig_df.loc[date, "signal"] != "BUY":
                continue

            price = price_data[ticker].loc[date, "Close"]
            if pd.isna(price):
                continue

            if correlation_enabled:
                corr_count = correlation.correlated_position_count(
                    ticker, open_positions.keys(), price_data, date, corr_lookback, corr_threshold
                )
                if corr_count >= corr_max_correlated:
                    reason = correlation.breaker_reason(ticker, corr_count, corr_threshold, corr_max_correlated)
                    blocked_signals.append({
                        "ticker": ticker, "date": date, "reason": reason,
                        "log": journal.format_blocked(ticker, reason),
                    })
                    continue

            max_position_value = portfolio_value * max_position_pct
            room_left = (portfolio_value * max_invested_pct) - invested_value
            atr = sig_df.loc[date, "atr"] if "atr" in sig_df.columns else None
            sizing_note = None
            risk_per_share = None  # dollars of risk per share if stopped out = "1R" per share

            if sizing_method == "atr_unit" and atr is not None and not pd.isna(atr) and atr > 0:
                # Turtle-style: size so that a stop_atr_multiple*N move against
                # you costs exactly risk_pct_per_unit of account equity.
                stop_atr_multiple = cfg["risk"]["stop_atr_multiple"]
                risk_pct_per_unit = cfg["risk"]["risk_pct_per_unit"]
                risk_per_share = stop_atr_multiple * atr
                dollar_risk_budget = portfolio_value * (risk_pct_per_unit / 100)
                atr_allocation = (dollar_risk_budget / risk_per_share) * price
                # max_position_pct/max_invested_pct still apply as a ceiling on top.
                allocation = min(atr_allocation, max_position_value, room_left, cash)
                sizing_note = (
                    f"sized to risk {risk_pct_per_unit:.1f}% of equity "
                    f"(N=${atr:.2f}, stop {stop_atr_multiple:.1f}N away)"
                )
            else:
                # Flat % sizing (v1-v4 behavior), or atr_unit requested but ATR
                # isn't available yet (not enough history) — falls back safely.
                allocation = min(max_position_value, room_left, cash)

            if allocation <= 0:
                continue

            shares = allocation / price
            cost = shares * price * (1 + commission_pct)
            if cost > cash:
                continue

            if risk_per_share is None:
                # Flat % stop, expressed as a per-share dollar distance so the
                # stop-loss check and R-multiple math work the same way as
                # atr_unit mode (see the exit block above).
                stop_loss_pct_cfg = cfg["exit"].get("stop_loss_pct")
                risk_per_share = price * (stop_loss_pct_cfg / 100) if stop_loss_pct_cfg else None

            stop_price = (price - risk_per_share) if risk_per_share else None
            initial_risk_dollars = (risk_per_share * shares) if risk_per_share else None

            entry_reason = sig_df.loc[date, "reason"]
            entry_log = journal.format_entry(ticker, price, entry_reason, sizing_note=sizing_note)

            cash -= cost
            open_positions[ticker] = [Position(
                ticker, date, price, shares, entry_reason, entry_log,
                stop_price, initial_risk_dollars, sizing_method, unit_number=1,
            )]
            invested_value += shares * price

        portfolio_value = cash + invested_value
        equity_curve.append({"date": date, "portfolio_value": portfolio_value, "cash": cash})

    equity_df = pd.DataFrame(equity_curve).set_index("date")
    metrics = compute_metrics(equity_df, closed_trades, starting_cash, blocked_signals, rebalance_log, pyramid_log)

    return {
        "trades": closed_trades, "metrics": metrics, "equity_curve": equity_df,
        "blocked_signals": blocked_signals, "rebalance_log": rebalance_log, "pyramid_log": pyramid_log,
    }


def compute_metrics(
    equity_df: pd.DataFrame, trades: list, starting_cash: float,
    blocked_signals: list = None, rebalance_log: list = None, pyramid_log: list = None,
) -> dict:
    if equity_df.empty:
        return {}

    final_value = equity_df["portfolio_value"].iloc[-1]
    total_return_pct = (final_value / starting_cash - 1) * 100

    # Max drawdown
    running_max = equity_df["portfolio_value"].cummax()
    drawdown = (equity_df["portfolio_value"] - running_max) / running_max
    max_drawdown_pct = drawdown.min() * 100

    # Trade stats
    n_trades = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    win_rate = (len(wins) / n_trades * 100) if n_trades else 0

    # Longest losing streak
    streak = max_streak = 0
    for t in trades:
        if t["pnl"] <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    # Simple annualized return (approx, using calendar span)
    days = (equity_df.index[-1] - equity_df.index[0]).days
    years = days / 365.25 if days > 0 else 1
    annualized_return_pct = ((final_value / starting_cash) ** (1 / years) - 1) * 100 if years > 0 else 0

    # R-multiple stats — every trade's P&L expressed as a multiple of its
    # own initial risk (the Turtles' own yardstick: "+2.3R", "-1.0R").
    # Works whether trades used flat-% stops or N-based stops, since both
    # get converted to a per-trade dollar risk figure in the engine.
    r_multiples = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    if r_multiples:
        avg_r = float(np.mean(r_multiples))
        r_stdev = float(np.std(r_multiples, ddof=1)) if len(r_multiples) > 1 else 0.0
        # System Quality Number (Van Tharp): how consistent the edge is,
        # not just how big — a high average R with wildly varying R is a
        # worse system than a smaller, steadier average R.
        sqn = (avg_r / r_stdev * np.sqrt(len(r_multiples))) if r_stdev > 0 else None
    else:
        avg_r = r_stdev = sqn = None

    return {
        "starting_cash": starting_cash,
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return_pct, 2),
        "annualized_return_pct": round(annualized_return_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "n_trades": n_trades,
        "win_rate_pct": round(win_rate, 2),
        "avg_win_pct": round(np.mean([t["return_pct"] for t in wins]), 2) if wins else 0,
        "avg_loss_pct": round(np.mean([t["return_pct"] for t in losses]), 2) if losses else 0,
        "longest_losing_streak": max_streak,
        "trades_with_r_multiple": len(r_multiples),
        "avg_r_multiple": round(avg_r, 3) if avg_r is not None else None,
        "r_multiple_stdev": round(r_stdev, 3) if r_stdev is not None else None,
        "system_quality_number": round(sqn, 3) if sqn is not None else None,
        "best_r_multiple": round(max(r_multiples), 3) if r_multiples else None,
        "worst_r_multiple": round(min(r_multiples), 3) if r_multiples else None,
        "correlation_blocked_count": len(blocked_signals) if blocked_signals else 0,
        "portfolio_rebalances": len(rebalance_log) if rebalance_log else 0,
        "avg_active_portfolio_size": (
            round(sum(len(r["selected"]) for r in rebalance_log) / len(rebalance_log), 2)
            if rebalance_log else None
        ),
        "pyramid_adds": len(pyramid_log) if pyramid_log else 0,
        "positions_pyramided": (
            len(set(p["ticker"] for p in pyramid_log)) if pyramid_log else 0
        ),
    }
