import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

export default function EquityChart({ snapshots }) {
  const data = snapshots.map((s) => ({
    date: new Date(s.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    equity: s.equity,
  }));

  return (
    <div
      style={{
        margin: "20px 24px 0 24px",
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        padding: "16px 18px",
      }}
    >
      <div style={{ fontSize: 11, letterSpacing: "0.06em", color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 12 }}>
        Equity curve
      </div>
      {data.length === 0 ? (
        <div style={{ color: "var(--text-faint)", fontSize: 13, padding: "40px 0", textAlign: "center" }}>
          No account snapshots yet — the live runner logs one each time it runs.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="date" stroke="var(--text-faint)" fontSize={11} tickLine={false} axisLine={{ stroke: "var(--border)" }} />
            <YAxis
              stroke="var(--text-faint)"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              domain={["auto", "auto"]}
              tickFormatter={(v) => `$${(v / 1000).toFixed(1)}k`}
            />
            <Tooltip
              contentStyle={{ background: "var(--surface-raised)", border: "1px solid var(--border)", borderRadius: 6, fontFamily: "var(--font-mono)", fontSize: 12 }}
              formatter={(v) => [`$${v.toLocaleString()}`, "Equity"]}
            />
            <Line type="monotone" dataKey="equity" stroke="var(--accent)" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
