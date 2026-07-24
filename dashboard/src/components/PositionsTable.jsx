function fmtUsd(n) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
}

export default function PositionsTable({ openTrades }) {
  return (
    <Panel title="Open positions">
      {openTrades.length === 0 ? (
        <Empty text="No open positions right now." />
      ) : (
        <Table
          headers={["Ticker", "Entry date", "Entry price", "Shares"]}
          rows={openTrades.map((t) => [
            t.ticker,
            t.entry_date,
            fmtUsd(t.entry_price),
            t.shares.toFixed(3),
          ])}
        />
      )}
    </Panel>
  );
}

export function Panel({ title, children }) {
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
      <div style={{ fontSize: 11, letterSpacing: "0.06em", color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 12 }}>
        {title}
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
