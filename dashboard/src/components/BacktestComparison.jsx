import { Panel, Empty, Table } from "./PositionsTable.jsx";

export default function BacktestComparison({ runs }) {
  return (
    <Panel title="Backtest runs">
      {runs.length === 0 ? (
        <Empty text="No backtest runs saved yet — run with --save --label from the CLI." />
      ) : (
        <Table
          headers={["Label", "Date", "Return", "Max drawdown", "Win rate", "Trades"]}
          rows={runs.map((r) => {
            const m = r.metrics || {};
            const ret = m.total_return_pct;
            return [
              r.run_label ?? "(unlabeled)",
              new Date(r.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
              <span style={{ color: ret > 0 ? "var(--positive)" : ret < 0 ? "var(--negative)" : "var(--text-primary)" }}>
                {ret !== undefined ? `${ret > 0 ? "+" : ""}${ret}%` : "—"}
              </span>,
              m.max_drawdown_pct !== undefined ? `${m.max_drawdown_pct}%` : "—",
              m.win_rate_pct !== undefined ? `${m.win_rate_pct}%` : "—",
              m.n_trades ?? "—",
            ];
          })}
        />
      )}
    </Panel>
  );
}
