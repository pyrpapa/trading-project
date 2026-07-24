import { Panel, Empty, Table } from "./PositionsTable.jsx";

function fmtUsd(n) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
}

export default function SignalsFeed({ signals }) {
  return (
    <Panel title="Recent signals">
      {signals.length === 0 ? (
        <Empty text="No signals logged yet." />
      ) : (
        <Table
          headers={["Date", "Ticker", "Type", "Price", "Reason"]}
          rows={signals.map((s) => [
            s.signal_date,
            s.ticker,
            <span style={{ color: s.signal_type === "BUY" ? "var(--positive)" : "var(--negative)" }}>
              {s.signal_type}
            </span>,
            fmtUsd(s.price),
            s.reason ?? "—",
          ])}
        />
      )}
    </Panel>
  );
}
