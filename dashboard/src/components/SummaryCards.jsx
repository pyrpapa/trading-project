function fmtUsd(n) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
}

function fmtPct(n) {
  if (n === null || n === undefined) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function Card({ label, value, sub, subColor }) {
  return (
    <div
      style={{
        flex: 1,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        padding: "16px 18px",
      }}
    >
      <div
        style={{
          fontSize: 11,
          letterSpacing: "0.06em",
          color: "var(--text-muted)",
          textTransform: "uppercase",
          marginBottom: 8,
        }}
      >
        {label}
      </div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 24, fontWeight: 500 }}>{value}</div>
      {sub && (
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, marginTop: 4, color: subColor || "var(--text-muted)" }}>
          {sub}
        </div>
      )}
    </div>
  );
}

export default function SummaryCards({ latestSnapshot, previousSnapshot, openPositionsCount }) {
  const equity = latestSnapshot?.equity ?? null;
  const cash = latestSnapshot?.cash ?? null;

  let changePct = null;
  if (latestSnapshot && previousSnapshot) {
    changePct = ((latestSnapshot.equity - previousSnapshot.equity) / previousSnapshot.equity) * 100;
  }

  return (
    <div style={{ display: "flex", gap: 12, padding: "20px 24px 0 24px" }}>
      <Card label="Equity" value={fmtUsd(equity)} sub={changePct !== null ? `${fmtPct(changePct)} since last check` : null}
        subColor={changePct > 0 ? "var(--positive)" : changePct < 0 ? "var(--negative)" : "var(--text-muted)"} />
      <Card label="Cash" value={fmtUsd(cash)} />
      <Card label="Open positions" value={openPositionsCount ?? "—"} />
    </div>
  );
}
