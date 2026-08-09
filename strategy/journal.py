"""
Formats human-readable trade journal entries — in the spirit of the trade
diary examples in Curtis Faith's "Way of the Turtle", e.g.:

    "Entered long at $400.00 because it was a 60 day breakout according
    to the rules of System 2."

Used by both the backtester (backtest/engine.py) and the live/paper
runner (live/run_live.py) so backtest and live trade logs read the same
way and can be compared directly. Nothing here is strategy-specific —
the actual "why" text comes from strategy/rules.py (which reads config),
so this module just formats whatever reason it's given.
"""


def format_entry(ticker: str, price: float, reason: str, sizing_note: str = None) -> str:
    reason = reason or "no reason was recorded"
    base = f"Entered long {ticker} at ${price:,.2f}"
    if sizing_note:
        base += f", {sizing_note}"
    return f"{base} because {reason}."


def format_exit(ticker: str, price: float, return_pct: float, reason: str, r_multiple: float = None) -> str:
    reason = reason or "no reason was recorded"
    direction = "up" if return_pct >= 0 else "down"
    r_part = f", {r_multiple:+.1f}R" if r_multiple is not None else ""
    return (
        f"Exited {ticker} at ${price:,.2f} ({return_pct:+.2f}%, {direction}{r_part}) "
        f"because {reason}."
    )


def format_blocked(ticker: str, reason: str) -> str:
    return f"Skipped BUY {ticker} because {reason}."


def format_pyramid_add(ticker: str, unit_number: int, max_units: int, price: float, sizing_note: str = None) -> str:
    base = f"Added unit {unit_number}/{max_units} to {ticker} at ${price:,.2f}"
    if sizing_note:
        base += f", {sizing_note}"
    return f"{base} (pyramiding)."


def pyramid_add_reason_text(unit_number: int, max_units: int, unit_interval_n: float) -> str:
    """
    Human-readable description of WHY a pyramid unit fired -- a pure price
    threshold, not a fresh entry signal (see backtest/engine.py): price
    moved `unit_interval_n` * N further in the position's favor since the
    LAST unit's own entry price, and the stack hasn't hit max_units yet.
    """
    return (
        f"price moved {unit_interval_n:.1f}N further in its favor since the last unit's entry "
        f"(adding unit {unit_number} of {max_units})"
    )


def exit_reason_text(exit_reason_code: str, cfg: dict, trend_reason: str = None) -> str:
    """
    Turns the short exit_reason code the engine/live runner already
    computes ("stop_loss", "take_profit", "trend_exit") into a full
    human-readable explanation, pulling the actual numbers from config
    so the text stays correct if those numbers change — including which
    stop mechanism is actually in effect (flat % vs N-based).
    """
    exit_cfg = cfg.get("exit", {})
    risk_cfg = cfg.get("risk", {})
    sizing_method = risk_cfg.get("sizing_method", "pct")

    if exit_reason_code == "stop_loss":
        if sizing_method == "atr_unit":
            multiple = risk_cfg.get("stop_atr_multiple")
            return f"price dropped {multiple:.1f}N from entry (N = ATR-based volatility unit), triggering the stop-loss"
        pct = exit_cfg.get("stop_loss_pct")
        return f"price dropped {pct:.1f}% from entry, triggering the stop-loss"

    if exit_reason_code == "take_profit":
        pct = exit_cfg.get("take_profit_pct")
        return f"price gained {pct:.1f}% from entry, hitting the take-profit target"

    if exit_reason_code == "trend_exit":
        return trend_reason or "the trend-exit rule fired"

    return exit_reason_code or "no exit rule was recorded"
