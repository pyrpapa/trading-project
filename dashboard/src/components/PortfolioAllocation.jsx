import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell, LabelList } from "recharts";

// Fixed-order categorical palette, dark-surface steps -- validated (CVD
// separation, contrast, chroma/lightness bands) against this dashboard's
// own panel surface (#171d24) via the dataviz skill's validator before
// use here. Never cycled/reassigned -- if the watchlist ever grows past
// 7 tickers, fold the smallest into "Other" rather than adding a
// generated 8th hue (an unvalidated hue breaks the CVD guarantee).
const CATEGORICAL = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9"];

function fmtUsd(n) {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export default function PortfolioAllocation({ openTrades }) {
  // One bar per TICKER, not per row -- a pyramided position (several
  // rows in the Open Positions table, one per unit) is one holding for
  // allocation purposes, so its units' cost bases are summed together.
  const byTicker = new Map();
  for (const t of openTrades) {
    byTicker.set(t.ticker, (byTicker.get(t.ticker) ?? 0) + t.entry_price * t.shares);
  }
  const data = [...byTicker.entries()]
    .map(([ticker, value]) => ({ ticker, value }))
    .sort((a, b) => b.value - a.value);

  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        padding: "16px 18px",
      }}
    >
      <div style={{ fontSize: 11, letterSpacing: "0.06em", color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 12 }}>
        Invested by ticker
      </div>
      {data.length === 0 ? (
        <div style={{ color: "var(--text-faint)", fontSize: 13, padding: "40px 0", textAlign: "center" }}>
          No open positions right now.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={Math.max(120, data.length * 40)}>
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 48 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" horizontal={false} />
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="ticker"
              stroke="var(--text-faint)"
              fontSize={12}
              tickLine={false}
              axisLine={false}
              width={56}
            />
            <Tooltip
              cursor={{ fill: "var(--surface-raised)" }}
              contentStyle={{ background: "var(--surface-raised)", border: "1px solid var(--border)", borderRadius: 6, fontFamily: "var(--font-mono)", fontSize: 12 }}
              formatter={(v) => [fmtUsd(v), "Invested"]}
            />
            <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={28}>
              {data.map((d, i) => (
                <Cell key={d.ticker} fill={CATEGORICAL[i % CATEGORICAL.length]} />
              ))}
              <LabelList
                dataKey="value"
                position="right"
                formatter={fmtUsd}
                style={{ fill: "var(--text-primary)", fontFamily: "var(--font-mono)", fontSize: 12 }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
