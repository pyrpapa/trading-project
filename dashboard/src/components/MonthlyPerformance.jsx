import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell, LabelList, ReferenceLine } from "recharts";

// Diverging (positive/negative), not categorical -- monthly return has a
// sign, not an identity, so it reuses the same status-style tokens the
// rest of the dashboard already uses for P&L (SummaryCards, the two
// tables), not a new palette.
function barColor(pct) {
  return pct >= 0 ? "var(--positive)" : "var(--negative)";
}

function monthLabel(monthKey) {
  const [year, month] = monthKey.split("-");
  return new Date(Number(year), Number(month) - 1, 1).toLocaleDateString("en-US", { month: "short", year: "2-digit" });
}

// account_snapshots is already fetched for the equity curve (App.jsx) --
// reused here rather than a new query. Buckets by calendar month, using
// each month's LAST snapshot as that month's closing equity, and
// computes % change vs the PRIOR month's closing equity. The first
// month in the data has no prior month to compare against, so it falls
// back to its own first-vs-last snapshot -- a partial-month figure,
// flagged in the chart's caption rather than silently presented as a
// full month's return.
function computeMonthlyReturns(snapshots) {
  const byMonth = new Map();
  for (const s of snapshots) {
    const d = new Date(s.created_at);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    if (!byMonth.has(key)) byMonth.set(key, { first: s.equity, last: s.equity });
    else byMonth.get(key).last = s.equity;
  }
  const months = [...byMonth.keys()].sort();
  const rows = [];
  months.forEach((key, i) => {
    const { first, last } = byMonth.get(key);
    const baseline = i === 0 ? first : byMonth.get(months[i - 1]).last;
    const pct = baseline ? ((last - baseline) / baseline) * 100 : null;
    rows.push({ month: monthLabel(key), pct, partial: i === 0 });
  });
  return rows;
}

export default function MonthlyPerformance({ snapshots }) {
  const data = computeMonthlyReturns(snapshots).filter((r) => r.pct !== null);
  const hasPartialFirst = data.length > 0 && data[0].partial;

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
        Monthly performance
      </div>
      {data.length === 0 ? (
        <div style={{ color: "var(--text-faint)", fontSize: 13, padding: "40px 0", textAlign: "center" }}>
          Not enough account history yet.
        </div>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data} margin={{ top: 16 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="month" stroke="var(--text-faint)" fontSize={11} tickLine={false} axisLine={{ stroke: "var(--border)" }} />
              <YAxis stroke="var(--text-faint)" fontSize={11} tickLine={false} axisLine={false} tickFormatter={(v) => `${v}%`} />
              <ReferenceLine y={0} stroke="var(--border-bright)" />
              <Tooltip
                cursor={{ fill: "var(--surface-raised)" }}
                contentStyle={{ background: "var(--surface-raised)", border: "1px solid var(--border)", borderRadius: 6, fontFamily: "var(--font-mono)", fontSize: 12 }}
                formatter={(v) => [`${v >= 0 ? "+" : ""}${v.toFixed(2)}%`, "Return"]}
              />
              <Bar dataKey="pct" radius={[4, 4, 4, 4]} maxBarSize={40}>
                {data.map((d) => (
                  <Cell key={d.month} fill={barColor(d.pct)} />
                ))}
                <LabelList
                  dataKey="pct"
                  position="top"
                  formatter={(v) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`}
                  style={{ fill: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          {hasPartialFirst && (
            <div style={{ color: "var(--text-faint)", fontSize: 11, marginTop: 4 }}>
              First bar covers a partial month — account history starts mid-month.
            </div>
          )}
        </>
      )}
    </div>
  );
}
