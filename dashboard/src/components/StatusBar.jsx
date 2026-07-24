function timeAgo(dateStr) {
  if (!dateStr) return "never";
  const diffMs = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function StatusBar({ mode, strategyLabel, lastCheck, onSignOut }) {
  const isStale = !lastCheck || Date.now() - new Date(lastCheck).getTime() > 1000 * 60 * 60 * 30; // >30h

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "12px 24px",
        borderBottom: "1px solid var(--border)",
        fontFamily: "var(--font-mono)",
        fontSize: 13,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: isStale ? "var(--negative)" : "var(--positive)",
              display: "inline-block",
            }}
          />
          <span style={{ color: "var(--text-muted)" }}>{mode.toUpperCase()}</span>
        </span>
        <span style={{ color: "var(--border-bright)" }}>·</span>
        <span style={{ color: "var(--accent)" }}>{strategyLabel}</span>
        <span style={{ color: "var(--border-bright)" }}>·</span>
        <span style={{ color: "var(--text-muted)" }}>
          last check: {timeAgo(lastCheck)}
        </span>
      </div>
      <button
        onClick={onSignOut}
        style={{
          background: "none",
          border: "1px solid var(--border)",
          color: "var(--text-muted)",
          borderRadius: "var(--radius)",
          padding: "4px 10px",
          fontSize: 12,
          fontFamily: "var(--font-mono)",
        }}
      >
        sign out
      </button>
    </div>
  );
}
