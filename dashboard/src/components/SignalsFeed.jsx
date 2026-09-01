import { Panel, Empty, Table, fmtUsd, fmtPct, pnlColor } from "./PositionsTable.jsx";

// Groups closed trades by (ticker, exit_date) and sums pnl/cost-basis --
// a pyramided stack exits as several `trades` rows sharing one exit_date
// (one per unit, each with its own entry_price/shares/pnl -- see
// live/run_live.py), so a SELL signal's realized P&L is the SUM across
// however many units closed that day, not a single row.
function summarizeExits(closedTrades) {
  const byKey = new Map();
  for (const t of closedTrades) {
    if (t.exit_date == null || t.pnl == null) continue;
    const key = `${t.ticker}|${t.exit_date}`;
    const prev = byKey.get(key) ?? { pnl: 0, costBasis: 0 };
    prev.pnl += t.pnl;
    prev.costBasis += t.entry_price * t.shares;
    byKey.set(key, prev);
  }
  return byKey;
}

export default function SignalsFeed({ signals, closedTrades = [] }) {
  const exitsByKey = summarizeExits(closedTrades);

  return (
    <Panel title="Recent signals">
      {signals.length === 0 ? (
        <Empty text="No signals logged yet." />
      ) : (
        <Table
          headers={["Date", "Ticker", "Type", "Price", "P&L", "Reason"]}
          rows={signals.map((s) => {
            const exit = s.signal_type === "SELL" ? exitsByKey.get(`${s.ticker}|${s.signal_date}`) : null;
            const pnlPct = exit && exit.costBasis > 0 ? (exit.pnl / exit.costBasis) * 100 : null;
            return [
              s.signal_date,
              s.ticker,
              <span style={{ color: s.signal_type === "BUY" ? "var(--positive)" : "var(--negative)" }}>
                {s.signal_type}
              </span>,
              fmtUsd(s.price),
              exit ? (
                <span style={{ color: pnlColor(exit.pnl) }}>
                  {fmtUsd(exit.pnl)} ({fmtPct(pnlPct)})
                </span>
              ) : (
                "—"
              ),
              s.reason ?? "—",
            ];
          })}
        />
      )}
    </Panel>
  );
}
