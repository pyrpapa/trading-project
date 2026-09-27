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


def run_backtest(price_data: dict, signals: dict, cfg: dict, benchmark_returns: pd.Series = None) -> dict:
    """
    price_data: {ticker: DataFrame with OHLCV}
    signals:    {ticker: DataFrame with 'signal' column, same index as price_data}
    cfg:        parsed strategy.yaml
    benchmark_returns: optional daily % return Series (e.g. SPY) for
        metrics["beta"]/["alpha_pct"] -- see compute_metrics. Pure
        pass-through, engine.py itself never fetches data.

    Returns dict with 'trades' (list of closed trades) and 'metrics' (summary stats)
    and 'equity_curve' (DataFrame of portfolio value over time).
    """
    starting_cash = cfg["backtest"]["starting_cash"]
    commission_pct = cfg["backtest"].get("commission_pct", 0.0) / 100

    # Execution timing. "signal_close" (default, every pre-2026-09-27
    # result): decide AND fill at the same daily close -- a price nobody
    # can actually trade at, since the close is only known once it's
    # printed. "next_open": decide on day t's close exactly as before
    # (signals, stop/trend-exit checks, pyramid thresholds, sizing), but
    # queue the orders and fill them at day t+1's OPEN -- what
    # live/run_live.py actually does (acts on the last completed daily
    # bar, trades the next morning). Re-testing strategy_master under a
    # 1-day lag roughly halved its Calmar in 3 of the 4 standard windows,
    # so this is the setting to judge real edge with.
    execution = cfg["backtest"].get("execution", "signal_close")
    if execution not in ("signal_close", "next_open"):
        raise ValueError(f"backtest.execution must be 'signal_close' or 'next_open', got {execution!r}")
    next_open = execution == "next_open"
    take_profit_pct = cfg["exit"].get("take_profit_pct")
    take_profit_pct = take_profit_pct / 100 if take_profit_pct else None
    max_position_pct = cfg["risk"]["max_position_pct"] / 100
    max_invested_pct = cfg["risk"]["max_invested_pct"] / 100
    sizing_method = cfg["risk"].get("sizing_method", "pct")  # "pct" (v1-v4) or "atr_unit" (Turtle-style)

    # Per-ticker position-size override -- the shared ATR-based sizing
    # formula (risk_pct_per_unit / (stop_atr_multiple * N) * price) gives
    # BIGGER dollar positions to LOWER-volatility tickers, since it's
    # solving for constant dollar RISK, not constant dollar SIZE. Mixing
    # one calm asset (e.g. GLD) into a watchlist of much choppier ones
    # (3x leveraged ETFs) means that calm asset's positions can end up
    # 2-4x bigger, in dollars, than everything else -- confirmed directly
    # on strategy_v38_add_gold.yaml (GLD's avg position ran $4,031 vs
    # TQQQ's $1,775 in the 2019-2024 window), which both ties up an
    # outsized share of capital in the lowest-conviction ticker AND
    # crowds out room for the better-performing ones. This lets a config
    # cap specific tickers below the shared max_position_pct ceiling,
    # without touching the ATR math itself or affecting any other
    # ticker. Falls back to the shared max_position_pct when a ticker
    # has no override (or the block is absent) -- v1-v37 configs behave
    # identically with zero changes.
    ticker_overrides_cfg = cfg["risk"].get("ticker_overrides") or {}

    def max_position_pct_for(ticker):
        override = (ticker_overrides_cfg.get(ticker) or {}).get("max_position_pct")
        return (override / 100) if override is not None else max_position_pct

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

    # Peak-based trailing stop -- pulls a stack's stop up toward its
    # highest CLOSE seen since entry (not just the entry price), so a
    # sharp spike that reverses fast still gets SOME of its gain
    # protected even if it never triggers a pyramid add (pyramiding only
    # trails the stop up to each new unit's OWN stop level, in discrete
    # 0.5N-interval jumps -- a fast spike-and-reverse within one of those
    # jumps gets no protection at all from pyramiding alone). Runs
    # independently of pyramiding and uses the CURRENT day's N, same
    # "recompute at current volatility" convention the pyramid-add block
    # already uses. Only moves the stop UP, never down (see the trailing
    # update block below). Disabled unless a config explicitly opts in
    # via risk.trailing_stop.enabled.
    trailing_stop_cfg = cfg["risk"].get("trailing_stop") or {}
    trailing_stop_enabled = trailing_stop_cfg.get("enabled", False) and sizing_method == "atr_unit"
    trailing_stop_atr_multiple = trailing_stop_cfg.get("atr_multiple", cfg["risk"].get("stop_atr_multiple", 2.0))

    # Side pot -- periodically skims trading profit into a separate,
    # untraded holding, actually removed from `cash` (so it stops being
    # sized into future positions, same as moving it to a real separate
    # account). Two phases:
    #   PHASE 1 (side_pot_value < starting_cash): whenever portfolio_value
    #     exceeds the running benchmark (starts at starting_cash -- the
    #     "initial investment"), skim phase1_skim_pct of the NEW gain
    #     above the benchmark, then reset the benchmark to the
    #     (post-skim) portfolio_value so the same gain is never skimmed
    #     twice. Goal: get the side pot up to matching the initial
    #     investment -- the point past which you could lose the entire
    #     TRADING account and still have your original stake back.
    #   PHASE 2 (side_pot_value >= starting_cash): same mechanic, but the
    #     trigger becomes a full phase2_ratchet_pct move above the last
    #     benchmark (a real new plateau, not any new high) -- a classic
    #     high-water-mark ratchet, same shape hedge funds use for
    #     performance fees, just skimming into your own side pot instead.
    # Disabled unless a config explicitly opts in via side_pot.enabled.
    side_pot_cfg = cfg.get("side_pot") or {}
    side_pot_enabled = side_pot_cfg.get("enabled", False)
    side_pot_phase1_skim_pct = side_pot_cfg.get("phase1_skim_pct", 50.0) / 100
    side_pot_phase2_ratchet_pct = side_pot_cfg.get("phase2_ratchet_pct", 20.0) / 100
    side_pot_phase2_skim_pct = side_pot_cfg.get("phase2_skim_pct", 50.0) / 100

    # Correlation-based circuit breaker (see strategy/correlation.py) — a
    # portfolio-level check on top of per-position sizing. Disabled unless
    # a config explicitly opts in via risk.correlation_breaker.enabled.
    correlation_cfg = cfg["risk"].get("correlation_breaker") or {}
    correlation_enabled = correlation_cfg.get("enabled", False)
    corr_lookback = correlation_cfg.get("lookback_period", 60)
    corr_threshold = correlation_cfg.get("correlation_threshold", 0.7)
    corr_max_correlated = correlation_cfg.get("max_correlated_positions", 2)

    # Portfolio volatility targeting -- scales NEW buying (fresh entries,
    # pyramid adds) and the max_invested_pct ceiling by
    # min(1, target / realized vol of the portfolio's own daily returns
    # over the last `lookback_days`). Calm stretches trade at full size;
    # when the account's own swings run hotter than target, new exposure
    # shrinks proportionally (Moreira & Muir 2017, "Volatility-Managed
    # Portfolios"). Never levers UP past 1x, and never force-trims
    # positions already open -- it only throttles what gets added.
    # Disabled unless a config opts in via risk.vol_target.enabled.
    vol_target_cfg = cfg["risk"].get("vol_target") or {}
    vol_target_enabled = vol_target_cfg.get("enabled", False)
    vol_target_annual = vol_target_cfg.get("target_annual_pct", 15.0) / 100
    vol_target_lookback = vol_target_cfg.get("lookback_days", 20)

    def exposure_scalar():
        if not vol_target_enabled or len(equity_curve) <= vol_target_lookback:
            return 1.0
        recent = pd.Series([row["portfolio_value"] for row in equity_curve[-(vol_target_lookback + 1):]])
        realized = recent.pct_change().dropna().std() * np.sqrt(252)
        if not realized or pd.isna(realized) or realized <= 0:
            return 1.0
        return min(1.0, vol_target_annual / realized)

    # Inverse-volatility sizing (risk.sizing_method: "inverse_vol") -- each
    # new position gets target_position_vol_pct / (the ticker's own
    # realized annual vol over lookback_days) of equity, capped by
    # max_position_pct. A 40%-vol asset gets a quarter the weight of a
    # 10%-vol one, so every holding contributes similar risk -- the
    # standard sizing for diversified trend-following across asset
    # classes. No stop is implied (unlike atr_unit); exit.stop_loss_pct
    # still applies if set.
    inverse_vol_cfg = cfg["risk"].get("inverse_vol") or {}
    inverse_vol_target = inverse_vol_cfg.get("target_position_vol_pct", 10.0) / 100
    inverse_vol_lookback = inverse_vol_cfg.get("lookback_days", 60)
    realized_vol = {}
    if sizing_method == "inverse_vol":
        realized_vol = {
            t: df["Close"].pct_change().rolling(inverse_vol_lookback).std() * np.sqrt(252)
            for t, df in price_data.items()
        }

    # Stop-out cooldown -- blocks re-entry into a ticker for `days` after
    # it exits via stop_loss specifically (not trend_exit/take_profit).
    # Targets "immediately re-enter and get whipsawed again": a stock
    # that just stopped out is, by definition, one the fast entry signal
    # was just wrong about recently -- waiting a bit before trusting a
    # fresh signal on the SAME ticker again. Disabled unless a config
    # explicitly opts in via risk.stop_cooldown.enabled.
    cooldown_cfg = cfg["risk"].get("stop_cooldown") or {}
    cooldown_enabled = cooldown_cfg.get("enabled", False)
    cooldown_days = cooldown_cfg.get("days", 10)

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
    ps_method = ps_cfg.get("method", "correlation")

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
    blocked_signals = []  # BUY signals the circuit breaker (or cooldown) skipped
    rebalance_log = []    # portfolio selection's rebalance history
    last_stop_date = {}   # ticker -> date of its most recent stop_loss exit (cooldown)
    pyramid_log = []      # pyramid-add events (see the pyramid-add block below)
    peak_price = {}       # ticker -> highest Close seen since the stack's entry (trailing stop)
    last_price = {}       # ticker -> most recent known Close (mark-to-market gap fallback, see mark_price)
    side_pot_value = 0.0  # skimmed profit, actually removed from `cash` -- see side_pot block below
    side_pot_benchmark = starting_cash  # last equity level a skim was measured from
    side_pot_log = []     # skim events (date, amount, phase, portfolio_value after)
    active_tickers = set(price_data.keys()) if not ps_enabled else set()
    next_rebalance_date = all_dates[0] if (ps_enabled and all_dates) else None
    equity_curve = []
    # next_open mode only: orders decided on the previous trading day,
    # filled at today's open (see execute_pending_orders below).
    pending_exits = {}     # ticker -> (exit_reason, trend_reason)
    pending_pyramids = []  # dicts: ticker, allocation, risk_per_share, sizing_note, atr
    pending_entries = []   # dicts: ticker, allocation, risk_per_share, sizing_note, entry_reason

    def open_price(ticker, date):
        """Today's Open for `ticker`, or None if it has no usable row today."""
        df = price_data.get(ticker)
        if df is None or date not in df.index or "Open" not in df.columns:
            return None
        px = df.loc[date, "Open"]
        return px if pd.notna(px) and px > 0 else None

    def close_stack(ticker, date, price, exit_reason, trend_reason):
        """Sells every unit of `ticker`'s stack at `price`, adds the
        proceeds (net of commission) to cash, and records one closed trade
        per unit. Shared by both execution modes. Proceeds are added to
        cash one unit at a time, the order the original inline code used:
        summing first changes float rounding, and later "cost > cash"
        checks on positions sized to exactly the remaining cash are
        knife-edge enough for that to change which trades happen."""
        nonlocal cash
        stack = open_positions.pop(ticker)
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
        peak_price.pop(ticker, None)
        if exit_reason == "stop_loss" and cooldown_enabled:
            last_stop_date[ticker] = date

    def mark_price(ticker, date):
        """Price to mark an open position at for `date`. Falls back to the
        most recent KNOWN Close when `ticker` has no row for `date` (a data
        gap -- confirmed directly on FAS around 2026-07-21/22, missing 2
        trading days other tickers had) instead of silently excluding the
        position from invested_value, which used to value it at $0 for
        those days and then "recover" the instant data resumed -- a fake
        ~40% one-day portfolio drawdown with no real price move behind it.
        Returns None only if `ticker` has never had a valid price yet
        (shouldn't happen for a position that's already open)."""
        if ticker in price_data and date in price_data[ticker].index:
            price = price_data[ticker].loc[date, "Close"]
            if pd.notna(price):
                last_price[ticker] = price
                return price
        return last_price.get(ticker)

    for date in all_dates:
        # --- next_open mode: fill yesterday's queued orders at today's open ---
        # Same order live/run_live.py acts in: exits, then pyramid adds,
        # then fresh entries (so a same-run exit's proceeds can fund a
        # re-entry, and a stopped-out ticker whose BUY still holds is sold
        # and re-bought at the same open -- the backtest's long-standing
        # same-bar re-entry behavior, now at a tradeable price). A ticker
        # with no usable open today keeps a pending EXIT for tomorrow;
        # pending buys for it are dropped instead (the signal is stale).
        if next_open:
            for ticker in list(pending_exits):
                if ticker not in open_positions:
                    del pending_exits[ticker]
                    continue
                px = open_price(ticker, date)
                if px is None:
                    continue
                exit_reason, trend_reason = pending_exits.pop(ticker)
                close_stack(ticker, date, px, exit_reason, trend_reason)

            for order in pending_pyramids:
                ticker = order["ticker"]
                stack = open_positions.get(ticker)
                px = open_price(ticker, date)
                if not stack or px is None:
                    continue
                allocation = min(order["allocation"], cash / (1 + commission_pct))
                shares = allocation / px
                if shares <= 0:
                    continue
                new_unit_stop = px - order["risk_per_share"]
                synced_stop = max(stack[0].stop_price, new_unit_stop) if stack[0].stop_price is not None else new_unit_stop
                for p in stack:
                    p.stop_price = synced_stop
                unit_number = len(stack) + 1
                add_reason = journal.pyramid_add_reason_text(unit_number, pyramid_max_units, pyramid_unit_interval_n)
                add_log = journal.format_pyramid_add(ticker, unit_number, pyramid_max_units, px, sizing_note=order["sizing_note"])
                cash -= shares * px * (1 + commission_pct)
                stack.append(Position(
                    ticker, date, px, shares, add_reason, add_log,
                    synced_stop, order["risk_per_share"] * shares, sizing_method, unit_number=unit_number,
                ))
                pyramid_log.append({
                    "date": date, "ticker": ticker, "unit_number": unit_number,
                    "price": px, "shares": shares, "log": add_log,
                })

            for order in pending_entries:
                ticker = order["ticker"]
                px = open_price(ticker, date)
                if ticker in open_positions or px is None:
                    continue
                allocation = min(order["allocation"], cash / (1 + commission_pct))
                shares = allocation / px
                if shares <= 0:
                    continue
                risk_per_share = order["risk_per_share"]
                if risk_per_share is None and order["stop_loss_pct"]:
                    risk_per_share = px * (order["stop_loss_pct"] / 100)
                stop_price = (px - risk_per_share) if risk_per_share else None
                entry_log = journal.format_entry(ticker, px, order["entry_reason"], sizing_note=order["sizing_note"])
                cash -= shares * px * (1 + commission_pct)
                open_positions[ticker] = [Position(
                    ticker, date, px, shares, order["entry_reason"], entry_log,
                    stop_price, (risk_per_share * shares) if risk_per_share else None,
                    sizing_method, unit_number=1,
                )]
                peak_price[ticker] = px

            pending_pyramids = []
            pending_entries = []

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
                method=ps_method,
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
            pos.value(mark_price(t, date))
            for t, stack in open_positions.items()
            if mark_price(t, date) is not None
            for pos in stack
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
                if next_open:
                    pending_exits[ticker] = (exit_reason, trend_reason)
                else:
                    close_stack(ticker, date, price, exit_reason, trend_reason)

        # Recompute invested value after exits. In next_open mode a stack
        # queued to exit is still held tonight, but everything below
        # (pyramid adds, trailing stop, entry sizing) treats it as already
        # gone -- valued at today's close as a proxy for tomorrow's
        # proceeds -- the same view live/run_live.py takes right after it
        # submits a sell.
        invested_value = sum(
            pos.value(mark_price(t, date))
            for t, stack in open_positions.items()
            if t not in pending_exits and mark_price(t, date) is not None
            for pos in stack
        )
        # Cash available for today's buy decisions. Identical to `cash` in
        # signal_close mode; in next_open mode it also counts proceeds from
        # queued exits and nets out buys already queued today.
        budget_cash = cash + sum(
            pos.value(mark_price(t, date)) * (1 - commission_pct)
            for t in pending_exits if mark_price(t, date) is not None
            for pos in open_positions[t]
        )
        portfolio_value = budget_cash + invested_value
        scalar = exposure_scalar()  # 1.0 unless risk.vol_target is on
        invested_cap_pct = max_invested_pct * scalar

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
                if ticker in pending_exits:
                    continue
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

                if not next_open:
                    invested_value = sum(
                        pos.value(mark_price(t, date))
                        for t, s in open_positions.items()
                        if mark_price(t, date) is not None
                        for pos in s
                    )
                    portfolio_value = cash + invested_value
                max_position_value = portfolio_value * max_position_pct_for(ticker)
                stack_value = sum(p.value(price) for p in stack)
                room_in_position = max_position_value - stack_value
                room_left = (portfolio_value * invested_cap_pct) - invested_value

                stop_atr_multiple = cfg["risk"]["stop_atr_multiple"]
                risk_pct_per_unit = cfg["risk"]["risk_pct_per_unit"]
                risk_per_share = stop_atr_multiple * atr
                dollar_risk_budget = portfolio_value * (risk_pct_per_unit / 100)
                atr_allocation = (dollar_risk_budget / risk_per_share) * price * scalar
                allocation = min(atr_allocation, room_in_position, room_left, budget_cash)
                if allocation <= 0:
                    continue

                sizing_note = (
                    f"pyramid unit sized to risk {risk_pct_per_unit:.1f}% of equity "
                    f"(N=${atr:.2f}, stop {stop_atr_multiple:.1f}N away)"
                )
                if next_open:
                    pending_pyramids.append({
                        "ticker": ticker, "allocation": allocation,
                        "risk_per_share": risk_per_share, "sizing_note": sizing_note,
                    })
                    budget_cash -= allocation * (1 + commission_pct)
                    invested_value += allocation
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
                add_reason = journal.pyramid_add_reason_text(unit_number, pyramid_max_units, pyramid_unit_interval_n)
                add_log = journal.format_pyramid_add(ticker, unit_number, pyramid_max_units, price, sizing_note=sizing_note)

                cash -= cost
                budget_cash -= cost
                stack.append(Position(
                    ticker, date, price, shares, add_reason, add_log,
                    synced_stop, initial_risk_dollars, sizing_method, unit_number=unit_number,
                ))
                pyramid_log.append({
                    "date": date, "ticker": ticker, "unit_number": unit_number,
                    "price": price, "shares": shares, "log": add_log,
                })

            # Recompute invested value after pyramid adds (next_open mode
            # already tracked queued adds in invested_value/budget_cash)
            if not next_open:
                invested_value = sum(
                    pos.value(mark_price(t, date))
                    for t, stack in open_positions.items()
                    if mark_price(t, date) is not None
                    for pos in stack
                )
                budget_cash = cash
                portfolio_value = cash + invested_value

        # --- Update peak-based trailing stop (existing open stacks only) ---
        # Deliberately runs AFTER today's stop-loss/trend-exit check above
        # (which used yesterday's stop level) and updates the stop for
        # TOMORROW's check instead -- avoids a same-day lookahead paradox
        # where today's fresh high could retroactively stop itself out.
        # Reads stack[0].stop_price as its starting point, so it picks up
        # any pyramid-triggered trail from earlier in this same day's
        # loop, and only ever raises it further (never down), same
        # "shared across the stack" convention stop_price already uses.
        if trailing_stop_enabled:
            for ticker, stack in open_positions.items():
                if ticker in pending_exits:
                    continue
                df = price_data[ticker]
                if date not in df.index:
                    continue
                sig_df = signals.get(ticker)
                if sig_df is None or date not in sig_df.index:
                    continue
                atr = sig_df.loc[date, "atr"]
                if atr is None or pd.isna(atr) or atr <= 0:
                    continue
                price = df.loc[date, "Close"]
                if pd.isna(price):
                    continue

                peak = max(peak_price.get(ticker, stack[0].entry_price), price)
                peak_price[ticker] = peak
                candidate_stop = peak - trailing_stop_atr_multiple * atr
                current_stop = stack[0].stop_price
                new_stop = max(current_stop, candidate_stop) if current_stop is not None else candidate_stop
                for p in stack:
                    p.stop_price = new_stop

        # --- Check entries ---
        for ticker, sig_df in signals.items():
            # A stack queued to exit at tomorrow's open can be re-entered
            # (sold and re-bought at that same open), mirroring the
            # same-bar re-entry signal_close mode has always done.
            if ticker in open_positions and ticker not in pending_exits:
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
                held = [t for t in open_positions if t not in pending_exits]
                held += [o["ticker"] for o in pending_entries]
                corr_count = correlation.correlated_position_count(
                    ticker, held, price_data, date, corr_lookback, corr_threshold
                )
                if corr_count >= corr_max_correlated:
                    reason = correlation.breaker_reason(ticker, corr_count, corr_threshold, corr_max_correlated)
                    blocked_signals.append({
                        "ticker": ticker, "date": date, "reason": reason,
                        "log": journal.format_blocked(ticker, reason),
                    })
                    continue

            if cooldown_enabled and ticker in last_stop_date:
                days_since_stop = (date - last_stop_date[ticker]).days
                if days_since_stop < cooldown_days:
                    reason = (
                        f"stopped out {days_since_stop} day(s) ago, "
                        f"cooldown is {cooldown_days} day(s)"
                    )
                    blocked_signals.append({
                        "ticker": ticker, "date": date, "reason": reason,
                        "log": journal.format_blocked(ticker, reason),
                    })
                    continue

            max_position_value = portfolio_value * max_position_pct_for(ticker)
            room_left = (portfolio_value * invested_cap_pct) - invested_value
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
                atr_allocation = (dollar_risk_budget / risk_per_share) * price * scalar
                # max_position_pct/max_invested_pct still apply as a ceiling on top.
                allocation = min(atr_allocation, max_position_value, room_left, budget_cash)
                sizing_note = (
                    f"sized to risk {risk_pct_per_unit:.1f}% of equity "
                    f"(N=${atr:.2f}, stop {stop_atr_multiple:.1f}N away)"
                )
            elif sizing_method == "inverse_vol":
                vol = realized_vol[ticker].get(date) if ticker in realized_vol else None
                if vol is None or pd.isna(vol) or vol <= 0:
                    continue  # not enough history to size it yet
                weight = min(inverse_vol_target / vol, max_position_pct_for(ticker))
                allocation = min(portfolio_value * weight * scalar, room_left, budget_cash)
                sizing_note = f"sized to {inverse_vol_target * 100:.0f}% target vol (realized {vol * 100:.0f}%)"
            else:
                # Flat % sizing (v1-v4 behavior), or atr_unit requested but ATR
                # isn't available yet (not enough history) — falls back safely.
                allocation = min(max_position_value * scalar, room_left, budget_cash)

            if allocation <= 0:
                continue

            if next_open:
                # Flat-% stops are re-derived from the actual fill price;
                # N-based stops keep today's N (risk_per_share is dollars).
                pending_entries.append({
                    "ticker": ticker, "allocation": allocation,
                    "risk_per_share": risk_per_share,
                    "stop_loss_pct": cfg["exit"].get("stop_loss_pct"),
                    "sizing_note": sizing_note, "entry_reason": sig_df.loc[date, "reason"],
                })
                budget_cash -= allocation * (1 + commission_pct)
                invested_value += allocation
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
            budget_cash -= cost
            open_positions[ticker] = [Position(
                ticker, date, price, shares, entry_reason, entry_log,
                stop_price, initial_risk_dollars, sizing_method, unit_number=1,
            )]
            peak_price[ticker] = price
            invested_value += shares * price

        if next_open:
            # End-of-day equity is what's ACTUALLY held tonight: every open
            # stack (including ones queued to exit tomorrow) at today's
            # close, plus real cash -- queued buys haven't spent anything yet.
            invested_value = sum(
                pos.value(mark_price(t, date))
                for t, stack in open_positions.items()
                if mark_price(t, date) is not None
                for pos in stack
            )
        portfolio_value = cash + invested_value

        # --- Side pot skim check (see side_pot block above) --- runs once
        # per day, using the day's final trading equity (after all of
        # today's exits/pyramid-adds/entries), so a skim is never based
        # on a stale intraday snapshot.
        if side_pot_enabled:
            if side_pot_value < starting_cash:
                # Phase 1: any new gain above the benchmark triggers a skim.
                if portfolio_value > side_pot_benchmark:
                    gain = portfolio_value - side_pot_benchmark
                    skim = min(gain * side_pot_phase1_skim_pct, cash)
                    if skim > 0:
                        cash -= skim
                        side_pot_value += skim
                        portfolio_value = cash + invested_value
                        side_pot_benchmark = portfolio_value
                        side_pot_log.append({
                            "date": date, "phase": 1, "skim_amount": round(skim, 2),
                            "side_pot_value": round(side_pot_value, 2),
                            "portfolio_value": round(portfolio_value, 2),
                        })
            else:
                # Phase 2: only a full ratchet-pct move above the last
                # benchmark triggers a skim -- a real new plateau, not
                # any new high.
                ratchet_trigger = side_pot_benchmark * (1 + side_pot_phase2_ratchet_pct)
                if portfolio_value >= ratchet_trigger:
                    gain = portfolio_value - side_pot_benchmark
                    skim = min(gain * side_pot_phase2_skim_pct, cash)
                    if skim > 0:
                        cash -= skim
                        side_pot_value += skim
                        portfolio_value = cash + invested_value
                        side_pot_benchmark = portfolio_value
                        side_pot_log.append({
                            "date": date, "phase": 2, "skim_amount": round(skim, 2),
                            "side_pot_value": round(side_pot_value, 2),
                            "portfolio_value": round(portfolio_value, 2),
                        })

        equity_curve.append({
            "date": date, "portfolio_value": portfolio_value, "cash": cash,
            "side_pot_value": side_pot_value, "total_wealth": portfolio_value + side_pot_value,
        })

    equity_df = pd.DataFrame(equity_curve).set_index("date")
    metrics = compute_metrics(
        equity_df, closed_trades, starting_cash, blocked_signals, rebalance_log, pyramid_log,
        benchmark_returns=benchmark_returns,
    )
    if side_pot_enabled:
        metrics["side_pot_final_value"] = round(side_pot_value, 2)
        metrics["side_pot_skim_count"] = len(side_pot_log)
        metrics["side_pot_reached_parity"] = side_pot_value >= starting_cash

    return {
        "trades": closed_trades, "metrics": metrics, "equity_curve": equity_df,
        "blocked_signals": blocked_signals, "rebalance_log": rebalance_log, "pyramid_log": pyramid_log,
        "side_pot_log": side_pot_log,
    }


def compute_metrics(
    equity_df: pd.DataFrame, trades: list, starting_cash: float,
    blocked_signals: list = None, rebalance_log: list = None, pyramid_log: list = None,
    benchmark_returns: pd.Series = None,
) -> dict:
    if equity_df.empty:
        return {}

    final_value = equity_df["portfolio_value"].iloc[-1]
    total_return_pct = (final_value / starting_cash - 1) * 100

    # Max drawdown
    running_max = equity_df["portfolio_value"].cummax()
    drawdown = (equity_df["portfolio_value"] - running_max) / running_max
    max_drawdown_pct = drawdown.min() * 100

    # Ulcer Index: sqrt(mean(drawdown^2)) -- unlike max_drawdown_pct (which
    # only cares about the single worst instant), this penalizes BOTH depth
    # and DURATION of every drawdown along the way. A strategy that grinds
    # sideways-down for months scores worse here than one with the same
    # max drawdown that recovers quickly, even though max_drawdown_pct
    # alone can't tell them apart.
    ulcer_index = float(np.sqrt((drawdown ** 2).mean())) * 100

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

    # Calmar Ratio: annualized return / |max drawdown|. Answers "how much
    # return per unit of worst-case pain" -- directly comparable across
    # strategies (or against simple buy-and-hold) regardless of scale.
    calmar_ratio = (annualized_return_pct / abs(max_drawdown_pct)) if max_drawdown_pct != 0 else None

    # Sortino ratio: annualized return / annualized downside deviation of
    # period returns, MAR (minimum acceptable return) = 0. Unlike SQN
    # (trade R-multiples), this only penalizes downside dispersion, not
    # upside volatility -- and unlike a homemade downside-SQN variant, it
    # has a widely-used external interpretation scale (<0 bad, 0-1
    # sub-par, 1-2 good, 2-3 very good, >3 excellent), so a given number
    # means something without having to rebuild the whole distribution.
    # periods_per_year is derived from the equity curve's own bar count
    # and calendar span (not a hardcoded 252/365), so it self-adjusts to
    # whatever bar frequency this backtest actually used.
    period_returns = equity_df["portfolio_value"].pct_change().dropna()
    if len(period_returns) > 1 and years > 0:
        periods_per_year = len(period_returns) / years
        downside_returns = period_returns.clip(upper=0)
        downside_deviation = float(np.sqrt((downside_returns ** 2).mean()))
        annualized_downside_deviation = downside_deviation * np.sqrt(periods_per_year)
        sortino_ratio = (
            (annualized_return_pct / 100) / annualized_downside_deviation
            if annualized_downside_deviation > 0 else None
        )
    else:
        sortino_ratio = None

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

    # Profit Factor: gross profit / gross loss (both as positive dollar
    # sums). A different question than win rate or avg R-multiple --
    # "for every dollar lost, how many dollars were won." >1 is
    # profitable, >2 is generally considered strong. None (not infinity)
    # when there are no losing trades to divide by, or no trades at all.
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses if t["pnl"] < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    # Beta / Alpha vs an external benchmark (see run_backtest.py, which
    # fetches SPY's daily returns and passes them in as
    # benchmark_returns). Beta: how much this equity curve's daily moves
    # track the benchmark's (regression slope). Alpha: the annualized
    # excess return LEFT OVER after removing that benchmark exposure --
    # simplified CAPM, risk-free rate treated as 0 (same MAR=0 convention
    # Sortino already uses here). Directly answers "is this adding real
    # value beyond just being correlated with a rising market," not just
    # "did it beat the benchmark's raw number." None when no benchmark
    # was supplied, or too little overlapping data to regress on.
    beta = alpha_pct = None
    if benchmark_returns is not None:
        strat_returns = equity_df["portfolio_value"].pct_change().dropna()
        aligned = pd.DataFrame({"strategy": strat_returns, "benchmark": benchmark_returns}).dropna()
        if len(aligned) > 1:
            bench_var = aligned["benchmark"].var()
            if bench_var > 0:
                beta = float(aligned["strategy"].cov(aligned["benchmark"]) / bench_var)
                bench_days = (aligned.index[-1] - aligned.index[0]).days
                bench_years = bench_days / 365.25 if bench_days > 0 else 1
                bench_total_return = (1 + aligned["benchmark"]).prod() - 1
                bench_annualized = (1 + bench_total_return) ** (1 / bench_years) - 1 if bench_years > 0 else 0
                alpha_pct = (annualized_return_pct / 100 - beta * bench_annualized) * 100

    return {
        "starting_cash": starting_cash,
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return_pct, 2),
        "annualized_return_pct": round(annualized_return_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "ulcer_index": round(ulcer_index, 3),
        "calmar_ratio": round(calmar_ratio, 3) if calmar_ratio is not None else None,
        "sortino_ratio": round(sortino_ratio, 3) if sortino_ratio is not None else None,
        "n_trades": n_trades,
        "win_rate_pct": round(win_rate, 2),
        "avg_win_pct": round(np.mean([t["return_pct"] for t in wins]), 2) if wins else 0,
        "avg_loss_pct": round(np.mean([t["return_pct"] for t in losses]), 2) if losses else 0,
        "longest_losing_streak": max_streak,
        "trades_with_r_multiple": len(r_multiples),
        "avg_r_multiple": round(avg_r, 3) if avg_r is not None else None,
        "r_multiple_stdev": round(r_stdev, 3) if r_stdev is not None else None,
        "system_quality_number": round(sqn, 3) if sqn is not None else None,
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
        "beta": round(beta, 3) if beta is not None else None,
        "alpha_pct": round(alpha_pct, 3) if alpha_pct is not None else None,
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
