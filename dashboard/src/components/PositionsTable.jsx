import { useState } from "react";

// Shared by SignalsFeed.jsx too (see its import from this file, same
// pattern already used for Panel/Table/Empty below) -- realized P&L on a
// closed trade uses the exact same formatting/coloring as unrealized
// P&L here, no reason to duplicate it.
export function fmtUsd(n) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
}

export function fmtPct(n) {
  if (n === null || n === undefined) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

export function pnlColor(n) {
  if (n === null || n === undefined) return "var(--text-primary)";
  return n > 0 ? "var(--positive)" : n < 0 ? "var(--negative)" : "var(--text-primary)";
}

export default function PositionsTable({ openTrades, accessToken }) {
  // currentPrices: { TICKER: price } -- fetched on demand via the
  // "Refresh prices" button, not automatically on every load. Manual by
  // design (per request) rather than polling, so opening the dashboard
  // doesn't burn an Alpaca API call every time regardless of whether
  // anyone's actually looking at P&L right now.
  const [currentPrices, setCurrentPrices] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastFetched, setLastFetched] = useState(null);

  // Sell flow state. `confirming`/`selling`/`sellResult` are keyed by
  // ticker, not by row -- a pyramided stack closes as ONE whole-position
  // order (see live/close_position.py's own docstring: no partial-unit
  // close), so every row sharing a ticker moves through the same
  // confirm -> submit -> result states together, even though the table
  // shows them as separate rows (one per pyramid unit).
  const [confirming, setConfirming] = useState(null); // ticker currently showing the confirm prompt, or null
  const [selling, setSelling] = useState(null); // ticker currently being submitted, or null
  const [sellResults, setSellResults] = useState({}); // { TICKER: "submitted" | error string }

  async function refreshPrices() {
    const tickers = [...new Set(openTrades.map((t) => t.ticker))];
    if (tickers.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`/api/quotes?symbols=${encodeURIComponent(tickers.join(","))}`);
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);
      setCurrentPrices(body.prices || {});
      setLastFetched(new Date());
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function confirmSell(ticker) {
    setSelling(ticker);
    setConfirming(null);
    try {
      const resp = await fetch("/api/sell", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ ticker, dryRun: false }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);
      setSellResults((r) => ({ ...r, [ticker]: "submitted" }));
    } catch (e) {
      setSellResults((r) => ({ ...r, [ticker]: String(e.message || e) }));
    } finally {
      setSelling(null);
    }
  }

  // Total shares across every row for a ticker -- shown in the confirm
  // prompt so it's unambiguous a pyramided position sells as one whole
  // stack, regardless of which unit's row the Sell button was clicked on.
  function totalShares(ticker) {
    return openTrades.filter((t) => t.ticker === ticker).reduce((sum, t) => sum + t.shares, 0);
  }

  return (
    <Panel
      title="Open positions"
      action={
        openTrades.length > 0 && (
          <button onClick={refreshPrices} disabled={loading} style={refreshButtonStyle}>
            {loading ? "Refreshing…" : "Refresh prices"}
          </button>
        )
      }
    >
      {openTrades.length === 0 ? (
        <Empty text="No open positions right now." />
      ) : (
        <>
          <Table
            headers={["Ticker", "Entry date", "Entry price", "Shares", "Current price", "P&L", "P&L %", ""]}
            rows={openTrades.map((t) => {
              const current = currentPrices[t.ticker];
              const pnl = current != null ? (current - t.entry_price) * t.shares : null;
              const pnlPct = current != null ? ((current - t.entry_price) / t.entry_price) * 100 : null;
              const sellResult = sellResults[t.ticker];

              let action;
              if (confirming === t.ticker) {
                action = (
                  <span style={{ display: "flex", gap: 6, alignItems: "center", whiteSpace: "nowrap" }}>
                    <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
                      Sell all {totalShares(t.ticker).toFixed(3)} sh?
                    </span>
                    <button onClick={() => confirmSell(t.ticker)} style={confirmButtonStyle}>Confirm</button>
                    <button onClick={() => setConfirming(null)} style={cancelButtonStyle}>Cancel</button>
                  </span>
                );
              } else if (selling === t.ticker) {
                action = <span style={{ color: "var(--text-faint)", fontSize: 11 }}>Submitting…</span>;
              } else if (sellResult === "submitted") {
                action = (
                  <span style={{ color: "var(--positive)", fontSize: 11 }}>
                    Sell order submitted — check back shortly
                  </span>
                );
              } else if (sellResult) {
                action = <span style={{ color: "var(--negative)", fontSize: 11 }}>Failed: {sellResult}</span>;
              } else {
                action = (
                  <button onClick={() => setConfirming(t.ticker)} style={sellButtonStyle}>Sell</button>
                );
              }

              return [
                t.ticker,
                t.entry_date,
                fmtUsd(t.entry_price),
                t.shares.toFixed(3),
                current != null ? fmtUsd(current) : "—",
                <span style={{ color: pnlColor(pnl) }}>{pnl != null ? fmtUsd(pnl) : "—"}</span>,
                <span style={{ color: pnlColor(pnlPct) }}>{fmtPct(pnlPct)}</span>,
                action,
              ];
            })}
          />
          {error && (
            <div style={{ color: "var(--negative)", fontSize: 12, marginTop: 8 }}>
              Couldn't fetch live prices: {error}
            </div>
          )}
          {lastFetched && !error && (
            <div style={{ color: "var(--text-faint)", fontSize: 11, marginTop: 8 }}>
              Prices as of {lastFetched.toLocaleTimeString()} — not a live feed, click Refresh for current numbers.
            </div>
          )}
          <div style={{ color: "var(--text-faint)", fontSize: 11, marginTop: 4 }}>
            Selling a pyramided position closes ALL of its units at once — there's no partial close.
          </div>
        </>
      )}
    </Panel>
  );
}

const refreshButtonStyle = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  color: "var(--text-primary)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  padding: "4px 10px",
  cursor: "pointer",
};

const sellButtonStyle = {
  ...refreshButtonStyle,
  borderColor: "var(--negative)",
  color: "var(--negative)",
};

const confirmButtonStyle = {
  ...refreshButtonStyle,
  background: "var(--negative)",
  borderColor: "var(--negative)",
  color: "#fff",
};

const cancelButtonStyle = {
  ...refreshButtonStyle,
};

export function Panel({ title, children, action }) {
  return (
    <div
      style={{
        flex: 1,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        padding: "16px 18px",
        minWidth: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div style={{ fontSize: 11, letterSpacing: "0.06em", color: "var(--text-muted)", textTransform: "uppercase" }}>
          {title}
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

export function Empty({ text }) {
  return (
    <div style={{ color: "var(--text-faint)", fontSize: 13, padding: "24px 0", textAlign: "center" }}>{text}</div>
  );
}

export function Table({ headers, rows }) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)", fontSize: 13 }}>
      <thead>
        <tr>
          {headers.map((h) => (
            <th
              key={h}
              style={{
                textAlign: "left",
                fontWeight: 500,
                color: "var(--text-faint)",
                fontSize: 11,
                textTransform: "uppercase",
                letterSpacing: "0.04em",
                borderBottom: "1px solid var(--border)",
                padding: "0 8px 8px 0",
              }}
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i}>
            {row.map((cell, j) => (
              <td key={j} style={{ padding: "6px 8px 6px 0", borderBottom: "1px solid var(--border)", color: "var(--text-primary)" }}>
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
