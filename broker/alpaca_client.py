"""
Thin wrapper around Alpaca's trading API.

Credentials come from environment variables — never hardcode them:
    ALPACA_API_KEY
    ALPACA_SECRET_KEY
    ALPACA_PAPER          "true" (default) or "false" — which endpoint to use

Alpaca gives you a free paper trading account automatically when you
sign up — no separate application needed. Get keys from:
https://app.alpaca.markets/paper/dashboard/overview

Uses the alpaca-py SDK (the current official one; the older
alpaca-trade-api package is deprecated).
"""
import os


class AlpacaBroker:
    def __init__(self, api_key: str = None, secret_key: str = None, paper: bool = None):
        api_key = api_key or os.environ.get("ALPACA_API_KEY")
        secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY")
        if paper is None:
            paper = os.environ.get("ALPACA_PAPER", "true").lower() != "false"

        if not api_key or not secret_key:
            raise RuntimeError(
                "Missing Alpaca credentials. Set ALPACA_API_KEY and "
                "ALPACA_SECRET_KEY as environment variables (see .env.example)."
            )

        try:
            from alpaca.trading.client import TradingClient
        except ImportError:
            raise RuntimeError("Run: pip install alpaca-py")

        self.paper = paper
        self.client = TradingClient(api_key, secret_key, paper=paper)

        if not paper:
            # Hard guard: this project is built for paper trading first.
            # Remove this check yourself only once you've deliberately
            # decided you're ready to trade with real money.
            raise RuntimeError(
                "ALPACA_PAPER=false was set, meaning this would place REAL "
                "trades with real money. This safeguard is here on purpose — "
                "remove it only when you've validated paper results and are "
                "intentionally ready to go live."
            )

    def get_account(self) -> dict:
        acct = self.client.get_account()
        return {
            "equity": float(acct.equity),
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
            "portfolio_value": float(acct.portfolio_value),
        }

    def get_positions(self) -> dict:
        """Returns {ticker: {qty, avg_entry_price, market_value, unrealized_plpc}}"""
        positions = self.client.get_all_positions()
        return {
            p.symbol: {
                "qty": float(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "market_value": float(p.market_value),
                "unrealized_plpc": float(p.unrealized_plpc) * 100,  # as %
            }
            for p in positions
        }

    def submit_market_order(self, symbol: str, notional_usd: float = None, qty: float = None, side: str = "buy"):
        """
        Submit a market order. Provide either notional_usd (dollar amount,
        supports fractional shares) or qty (number of shares).
        """
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

        kwargs = dict(symbol=symbol, side=order_side, time_in_force=TimeInForce.DAY)
        if notional_usd is not None:
            kwargs["notional"] = round(notional_usd, 2)
        elif qty is not None:
            kwargs["qty"] = qty
        else:
            raise ValueError("Must provide either notional_usd or qty")

        order = self.client.submit_order(MarketOrderRequest(**kwargs))
        return {"id": str(order.id), "symbol": order.symbol, "side": side, "status": str(order.status)}

    def close_position(self, symbol: str):
        order = self.client.close_position(symbol)
        return {"id": str(order.id), "symbol": symbol, "status": str(order.status)}
