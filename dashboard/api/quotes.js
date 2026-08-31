// Vercel serverless function -- the ONLY place in the dashboard that ever
// touches Alpaca credentials. Deliberately kept server-side: this repo's
// backend (live/run_live.py) already treats ALPACA_API_KEY/SECRET_KEY as
// secrets never meant to reach a browser, and the dashboard itself is a
// static site with no other backend of its own, so this is the one spot
// that can safely hold them. Set ALPACA_API_KEY / ALPACA_SECRET_KEY as
// Vercel project environment variables (Project -> Settings ->
// Environment Variables) -- WITHOUT a VITE_ prefix, unlike the Supabase
// ones, specifically so Vite never bundles them into client-side code.
//
// Read-only market data (GET /v2/stocks/.../trades/latest) -- same
// Alpaca endpoint class broker/alpaca_client.py's get_latest_price()
// uses, just called directly over HTTP here instead of through the
// alpaca-py SDK, to avoid needing a Python runtime for one small
// function. Returns each requested ticker's latest trade price, nothing
// account-specific, so this endpoint is intentionally left unauthenticated
// (no funds or account data ever pass through it) -- worth revisiting if
// Alpaca API usage ever needs tighter gating.
//
// GET /api/quotes?symbols=SPXL,TECL,ERX
// -> { prices: { SPXL: 289.91, TECL: 201.47, ERX: 106.18 } }

export default async function handler(req, res) {
  const raw = req.query.symbols;
  const symbols = (Array.isArray(raw) ? raw.join(",") : raw || "")
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);

  if (symbols.length === 0) {
    return res.status(400).json({ error: "symbols query param required, e.g. ?symbols=SPXL,ERX" });
  }

  const apiKey = process.env.ALPACA_API_KEY;
  const secretKey = process.env.ALPACA_SECRET_KEY;
  if (!apiKey || !secretKey) {
    return res.status(500).json({ error: "ALPACA_API_KEY / ALPACA_SECRET_KEY not configured on the server" });
  }

  try {
    const url = `https://data.alpaca.markets/v2/stocks/trades/latest?symbols=${encodeURIComponent(symbols.join(","))}`;
    const alpacaResp = await fetch(url, {
      headers: {
        "APCA-API-KEY-ID": apiKey,
        "APCA-API-SECRET-KEY": secretKey,
      },
    });

    if (!alpacaResp.ok) {
      const text = await alpacaResp.text();
      return res.status(alpacaResp.status).json({ error: `Alpaca API error (${alpacaResp.status}): ${text}` });
    }

    const body = await alpacaResp.json();
    const prices = {};
    for (const [symbol, trade] of Object.entries(body.trades || {})) {
      prices[symbol] = trade.p;
    }
    return res.status(200).json({ prices });
  } catch (e) {
    return res.status(500).json({ error: String(e) });
  }
}
