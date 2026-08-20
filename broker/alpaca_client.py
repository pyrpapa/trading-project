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


def _is_crypto(ticker: str) -> bool:
    """Canonical (yfinance-style) crypto tickers always look like 'BTC-USD'."""
    return "-" in ticker


def _to_alpaca_symbol(ticker: str) -> str:
    """
    Alpaca and yfinance use different symbol formats for crypto: this
    project's configs/data layer use yfinance's 'BTC-USD' (hyphen)
    throughout, but Alpaca's own symbol is 'BTC/USD' (slash) -- confirmed
    directly via client.get_asset('BTC/USD').symbol. Equities/ETFs are
    unaffected (no hyphen, passed through unchanged).
    """
    return ticker.replace("-", "/") if _is_crypto(ticker) else ticker


def _from_alpaca_symbol(symbol: str, asset_class=None) -> str:
    """
    Inverse of _to_alpaca_symbol, for translating broker responses back to
    canonical (yfinance-style) format. Alpaca is NOT consistent about the
    separator for crypto: order/asset responses use 'LINK/USD' (slash),
    but the positions endpoint has been observed returning the same pair
    as 'LINKUSD' -- no separator at all. Confirmed directly: a live
    LINK-USD position came back from get_all_positions() as 'LINKUSD',
    didn't match anything in _from_alpaca_symbol's old slash-only check,
    and was silently flagged as an "orphaned" position -- disabling its
    stop-loss/exit checks entirely, exactly the failure mode the orphan
    warning exists to catch, except the position wasn't actually
    orphaned, the symbol translation was just wrong.

    `asset_class` (present on both Position and Order objects) is the
    authoritative crypto/equity signal here, not the symbol's shape --
    used to decide whether a missing separator needs to be reinserted at
    all, so an equity ticker that happens to end in "USD" is never
    mistaken for crypto.
    """
    if "/" in symbol:
        return symbol.replace("/", "-")

    from alpaca.trading.enums import AssetClass
    is_crypto = asset_class == AssetClass.CRYPTO
    if is_crypto and "-" not in symbol and symbol.endswith("USD"):
        return f"{symbol[:-3]}-USD"
    return symbol


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

        self.api_key = api_key
        self.secret_key = secret_key
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
        """Returns {ticker: {qty, avg_entry_price, market_value, unrealized_plpc}}, ticker in canonical (yfinance-style) format."""
        positions = self.client.get_all_positions()
        return {
            _from_alpaca_symbol(p.symbol, p.asset_class): {
                "qty": float(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "market_value": float(p.market_value),
                "unrealized_plpc": float(p.unrealized_plpc) * 100,  # as %
            }
            for p in positions
        }

    def submit_market_order(self, symbol: str, notional_usd: float = None, qty: float = None, side: str = "buy"):
        """
        Submit a market order. `symbol` is canonical (yfinance-style,
        e.g. 'BTC-USD' for crypto) -- translated to Alpaca's own format
        internally. Provide either notional_usd (dollar amount, supports
        fractional shares) or qty (number of shares).
        """
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        # Crypto trades 24/7 -- "day" has no clean meaning there (no
        # market close for an order to expire against), so use GTC for
        # crypto specifically. Equities keep DAY, unchanged.
        tif = TimeInForce.GTC if _is_crypto(symbol) else TimeInForce.DAY

        kwargs = dict(symbol=_to_alpaca_symbol(symbol), side=order_side, time_in_force=tif)
        if notional_usd is not None:
            kwargs["notional"] = round(notional_usd, 2)
        elif qty is not None:
            kwargs["qty"] = qty
        else:
            raise ValueError("Must provide either notional_usd or qty")

        order = self.client.submit_order(MarketOrderRequest(**kwargs))
        return {"id": str(order.id), "symbol": _from_alpaca_symbol(order.symbol, order.asset_class), "side": side, "status": str(order.status)}

    def is_market_open(self, symbol: str) -> bool:
        """
        Whether `symbol` can be traded RIGHT NOW. Crypto trades 24/7 so is
        always considered open. Equities/ETFs key off Alpaca's own market
        clock (accounts for weekends, holidays, half-days -- more reliable
        than computing NYSE hours by hand), since a DAY market order
        submitted while the equity market is closed doesn't reject, it just
        queues silently until the next open -- exposing the eventual fill
        to whatever the market does overnight (confirmed directly: a paper
        BUY submitted after the close filled the next morning 1-2.4% away
        from the price the entry was sized against). Callers use this to
        skip the entry instead of queuing it blind.
        """
        if _is_crypto(symbol):
            return True
        return self.client.get_clock().is_open

    def get_latest_price(self, symbol: str) -> float:
        """
        Live quote for `symbol` (canonical, yfinance-style) straight from
        Alpaca's own market data -- NOT data/fetcher.py's yfinance daily
        bars. Used for position sizing and stop-loss/exit checks, where
        yfinance's daily-bar data can lag "now" by more than the intended
        one day (crypto especially -- confirmed directly: a live BUY
        priced off a bar that was already 2 days stale despite running
        same-day). The trend SIGNAL itself (MA/volume/regime crossovers
        in strategy/rules.py) still comes from yfinance daily bars --
        trend-following is meant to key off completed daily bars, only
        the "what price is this actually happening at" check needed to
        be live.
        """
        from alpaca.data.requests import CryptoLatestTradeRequest, StockLatestTradeRequest

        alpaca_symbol = _to_alpaca_symbol(symbol)
        if _is_crypto(symbol):
            from alpaca.data.historical.crypto import CryptoHistoricalDataClient
            client = CryptoHistoricalDataClient(self.api_key, self.secret_key)
            req = CryptoLatestTradeRequest(symbol_or_symbols=alpaca_symbol)
            trade = client.get_crypto_latest_trade(req)[alpaca_symbol]
        else:
            from alpaca.data.historical.stock import StockHistoricalDataClient
            from alpaca.data.enums import DataFeed
            client = StockHistoricalDataClient(self.api_key, self.secret_key)
            # IEX feed -- SIP requires a paid subscription; IEX is free
            # and what a paper-trading account has access to by default.
            req = StockLatestTradeRequest(symbol_or_symbols=alpaca_symbol, feed=DataFeed.IEX)
            trade = client.get_stock_latest_trade(req)[alpaca_symbol]
        return float(trade.price)

    def close_position(self, symbol: str):
        """
        `symbol` is canonical (yfinance-style) -- translated internally.

        Submits an explicit market SELL order for the full held quantity,
        rather than using the SDK's own close_position() convenience
        endpoint. Confirmed directly (404 on a real LINK-USD close) that
        the SDK's close_position() puts the symbol straight into the URL
        PATH (DELETE /v2/positions/{symbol}) without encoding it --
        crypto symbols contain a literal "/" (e.g. LINK/USD), which
        splits into two path segments there instead of one symbol, so
        the request 404s. This would have silently broken any AUTOMATIC
        crypto stop-loss/trend-exit close too, not just a manual one --
        live/run_live.py calls this same method. Submitting an order
        instead sidesteps the bug entirely, since the symbol travels in
        the JSON request body there, not the URL path -- same code path
        submit_market_order() already uses successfully for entries.
        """
        positions = self.get_positions()
        if symbol not in positions:
            raise ValueError(f"No open position in {symbol!r} to close.")
        qty = positions[symbol]["qty"]
        order = self.submit_market_order(symbol, qty=qty, side="sell")
        return {"id": order["id"], "symbol": symbol, "status": order["status"]}
