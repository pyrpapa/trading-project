"""
Thin wrapper around the Supabase client for this project's tables.

Credentials come from environment variables — never hardcode them:
    SUPABASE_URL
    SUPABASE_SERVICE_KEY   (service role key — server-side only, never
                             ship this to a browser/frontend)

Usage:
    from storage.supabase_client import SupabaseStore
    store = SupabaseStore()
    store.save_backtest_run(cfg, metrics, run_label="ma20-stop8")
"""
import os
import json


class SupabaseStore:
    def __init__(self, url: str = None, key: str = None):
        url = url or os.environ.get("SUPABASE_URL")
        key = key or os.environ.get("SUPABASE_SERVICE_KEY")

        if not url or not key:
            raise RuntimeError(
                "Missing Supabase credentials. Set SUPABASE_URL and "
                "SUPABASE_SERVICE_KEY as environment variables (see .env.example)."
            )

        try:
            from supabase import create_client
        except ImportError:
            raise RuntimeError("Run: pip install supabase")

        self.client = create_client(url, key)

    def save_backtest_run(self, cfg: dict, metrics: dict, run_label: str = None) -> dict:
        row = {
            "run_label": run_label,
            "config": cfg,
            "watchlist": cfg["watchlist"],
            "start_date": cfg["backtest"]["start_date"],
            "end_date": cfg["backtest"]["end_date"],
            "metrics": metrics,
        }
        result = self.client.table("backtest_runs").insert(row).execute()
        return result.data[0] if result.data else None

    def save_trades(self, trades: list, source: str = "backtest", backtest_run_id: int = None) -> None:
        if not trades:
            return
        rows = []
        for t in trades:
            rows.append({
                "ticker": t["ticker"],
                "source": source,
                "entry_date": str(t["entry_date"].date()) if hasattr(t["entry_date"], "date") else str(t["entry_date"]),
                "entry_price": float(t["entry_price"]),
                "exit_date": str(t["exit_date"].date()) if hasattr(t["exit_date"], "date") else str(t["exit_date"]),
                "exit_price": float(t["exit_price"]),
                "shares": float(t["shares"]),
                "pnl": float(t["pnl"]),
                "return_pct": float(t["return_pct"]),
                "exit_reason": t["exit_reason"],
                "entry_reason": t.get("entry_reason"),
                "entry_log": t.get("entry_log"),
                "exit_reason_detail": t.get("exit_reason_detail"),
                "exit_log": t.get("exit_log"),
                "sizing_method": t.get("sizing_method"),
                "initial_risk_dollars": float(t["initial_risk_dollars"]) if t.get("initial_risk_dollars") is not None else None,
                "r_multiple": float(t["r_multiple"]) if t.get("r_multiple") is not None else None,
                "backtest_run_id": backtest_run_id,
            })
        # Batch insert in chunks to avoid oversized requests
        for i in range(0, len(rows), 500):
            self.client.table("trades").insert(rows[i:i + 500]).execute()

    def save_signal(self, ticker: str, signal_date, signal_type: str, price: float, reason: str = None) -> dict:
        row = {
            "ticker": ticker,
            "signal_date": str(signal_date.date()) if hasattr(signal_date, "date") else str(signal_date),
            "signal_type": signal_type,
            "price": float(price),
            "reason": reason,
        }
        result = self.client.table("signals").insert(row).execute()
        return result.data[0] if result.data else None

    def save_config_snapshot(self, cfg: dict, note: str = None) -> dict:
        row = {"config": cfg, "note": note}
        result = self.client.table("config_history").insert(row).execute()
        return result.data[0] if result.data else None

    def open_trade(
        self, ticker: str, entry_date, entry_price: float, shares: float, source: str = "paper",
        entry_reason: str = None, entry_log: str = None,
        sizing_method: str = None, initial_risk_dollars: float = None, unit_number: int = 1,
    ) -> dict:
        row = {
            "ticker": ticker,
            "source": source,
            "entry_date": str(entry_date.date()) if hasattr(entry_date, "date") else str(entry_date),
            "entry_price": float(entry_price),
            "shares": float(shares),
            "entry_reason": entry_reason,
            "entry_log": entry_log,
            "sizing_method": sizing_method,
            "initial_risk_dollars": float(initial_risk_dollars) if initial_risk_dollars is not None else None,
            "unit_number": unit_number,
        }
        result = self.client.table("trades").insert(row).execute()
        return result.data[0] if result.data else None

    def close_trade(
        self, trade_id: int, exit_date, exit_price: float, pnl: float, return_pct: float, exit_reason: str,
        exit_reason_detail: str = None, exit_log: str = None, r_multiple: float = None,
    ) -> dict:
        row = {
            "exit_date": str(exit_date.date()) if hasattr(exit_date, "date") else str(exit_date),
            "exit_price": float(exit_price),
            "pnl": float(pnl),
            "return_pct": float(return_pct),
            "exit_reason": exit_reason,
            "exit_reason_detail": exit_reason_detail,
            "exit_log": exit_log,
            "r_multiple": float(r_multiple) if r_multiple is not None else None,
        }
        result = self.client.table("trades").update(row).eq("id", trade_id).execute()
        return result.data[0] if result.data else None

    def find_open_trade(self, ticker: str, source: str = "paper"):
        result = (
            self.client.table("trades")
            .select("*")
            .eq("ticker", ticker)
            .eq("source", source)
            .is_("exit_date", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def find_last_closed_trade(self, ticker: str, source: str = "paper", exit_reason: str = None):
        """
        The most recent CLOSED trade for a ticker, optionally filtered to
        a specific exit_reason (e.g. "stop_loss" -- see the stop-out
        cooldown in live/run_live.py). Returns None if no closed trade
        matches, which callers should treat as "no cooldown in effect",
        same fail-open convention as everything else that reconstructs
        state from Supabase.
        """
        query = (
            self.client.table("trades")
            .select("*")
            .eq("ticker", ticker)
            .eq("source", source)
            .not_.is_("exit_date", "null")
        )
        if exit_reason:
            query = query.eq("exit_reason", exit_reason)
        result = query.order("exit_date", desc=True).limit(1).execute()
        return result.data[0] if result.data else None

    def find_open_trades(self, ticker: str, source: str = "paper") -> list:
        """
        All currently-open trade rows for a ticker, ordered oldest-first
        (unit_number ascending) -- reconstructs a pyramided position's
        full "stack" (see live/run_live.py), not just its most recent
        unit. Returns [] if none found (e.g. Supabase has no record of a
        position the broker shows as open -- caller should treat that as
        "can't safely reconstruct" the same way a missing find_open_trade
        result already does for stop-loss checks).
        """
        result = (
            self.client.table("trades")
            .select("*")
            .eq("ticker", ticker)
            .eq("source", source)
            .is_("exit_date", "null")
            .order("unit_number", desc=False)
            .execute()
        )
        return result.data or []

    def save_account_snapshot(self, equity: float, cash: float, portfolio_value: float, buying_power: float, mode: str = "paper") -> dict:
        row = {
            "equity": float(equity),
            "cash": float(cash),
            "portfolio_value": float(portfolio_value),
            "buying_power": float(buying_power),
            "mode": mode,
        }
        result = self.client.table("account_snapshots").insert(row).execute()
        return result.data[0] if result.data else None

    def get_recent_runs(self, limit: int = 10) -> list:
        result = (
            self.client.table("backtest_runs")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data

    def get_run_by_label(self, label: str) -> dict:
        result = (
            self.client.table("backtest_runs")
            .select("*")
            .eq("run_label", label)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_trades_for_run(self, backtest_run_id: int) -> list:
        result = (
            self.client.table("trades")
            .select("*")
            .eq("backtest_run_id", backtest_run_id)
            .order("entry_date", desc=False)
            .execute()
        )
        return result.data
