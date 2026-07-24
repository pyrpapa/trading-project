"""
Simulates the strategy over historical data, day by day, applying:
- entry/exit signals from strategy/rules.py
- stop-loss / take-profit (config-driven, checked every day a position is open)
- position sizing and max-invested caps (config-driven)

Outputs a full trade log and summary performance metrics.
"""
import pandas as pd
import numpy as np


class Position:
    def __init__(self, ticker, entry_date, entry_price, shares):
        self.ticker = ticker
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.shares = shares

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
    stop_loss_pct = cfg["exit"]["stop_loss_pct"] / 100 if cfg["exit"]["stop_loss_pct"] else None
    take_profit_pct = cfg["exit"].get("take_profit_pct")
    take_profit_pct = take_profit_pct / 100 if take_profit_pct else None
    max_position_pct = cfg["risk"]["max_position_pct"] / 100
    max_invested_pct = cfg["risk"]["max_invested_pct"] / 100

    # Union of all trading dates across tickers
    all_dates = sorted(set.union(*[set(df.index) for df in price_data.values()]))

    cash = starting_cash
    open_positions = {}  # ticker -> Position
    closed_trades = []
    equity_curve = []

    for date in all_dates:
        # Mark-to-market portfolio value at start of day
        invested_value = sum(
            pos.value(price_data[t].loc[date, "Close"])
            for t, pos in open_positions.items()
            if date in price_data[t].index
        )
        portfolio_value = cash + invested_value

        # --- Check exits first (stop-loss, take-profit, trend-exit signal) ---
        for ticker in list(open_positions.keys()):
            df = price_data[ticker]
            if date not in df.index:
                continue
            pos = open_positions[ticker]
            price = df.loc[date, "Close"]
            change_pct = (price - pos.entry_price) / pos.entry_price

            exit_reason = None
            if stop_loss_pct and change_pct <= -stop_loss_pct:
                exit_reason = "stop_loss"
            elif take_profit_pct and change_pct >= take_profit_pct:
                exit_reason = "take_profit"
            elif ticker in signals and date in signals[ticker].index:
                if signals[ticker].loc[date, "signal"] == "SELL":
                    exit_reason = "trend_exit"

            if exit_reason:
                proceeds = pos.shares * price * (1 - commission_pct)
                cash += proceeds
                closed_trades.append({
                    "ticker": ticker,
                    "entry_date": pos.entry_date,
                    "entry_price": pos.entry_price,
                    "exit_date": date,
                    "exit_price": price,
                    "shares": pos.shares,
                    "pnl": proceeds - (pos.shares * pos.entry_price),
                    "return_pct": change_pct * 100,
                    "exit_reason": exit_reason,
                })
                del open_positions[ticker]

        # Recompute invested value after exits
        invested_value = sum(
            pos.value(price_data[t].loc[date, "Close"])
            for t, pos in open_positions.items()
            if date in price_data[t].index
        )
        portfolio_value = cash + invested_value

        # --- Check entries ---
        for ticker, sig_df in signals.items():
            if ticker in open_positions:
                continue
            if date not in sig_df.index:
                continue
            if sig_df.loc[date, "signal"] != "BUY":
                continue

            price = price_data[ticker].loc[date, "Close"]
            if pd.isna(price):
                continue

            # Risk checks: don't exceed max position size or max total invested
            max_position_value = portfolio_value * max_position_pct
            room_left = (portfolio_value * max_invested_pct) - invested_value
            allocation = min(max_position_value, room_left, cash)

            if allocation <= 0:
                continue

            shares = allocation / price
            cost = shares * price * (1 + commission_pct)
            if cost > cash:
                continue

            cash -= cost
            open_positions[ticker] = Position(ticker, date, price, shares)
            invested_value += shares * price

        portfolio_value = cash + invested_value
        equity_curve.append({"date": date, "portfolio_value": portfolio_value, "cash": cash})

    equity_df = pd.DataFrame(equity_curve).set_index("date")
    metrics = compute_metrics(equity_df, closed_trades, starting_cash)

    return {"trades": closed_trades, "metrics": metrics, "equity_curve": equity_df}


def compute_metrics(equity_df: pd.DataFrame, trades: list, starting_cash: float) -> dict:
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
    }
