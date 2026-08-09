"""
Export a saved backtest run (by label) to a CSV of trades and a
markdown summary you can keep, share, or drop into a spreadsheet.

Usage:
    python export_run.py --label "v4-bigger-positions"
    python export_run.py --label "v4-bigger-positions" --out results/
"""
import sys
import os
import csv
import json

sys.path.insert(0, os.path.dirname(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from storage.supabase_client import SupabaseStore


def main():
    if "--label" not in sys.argv:
        print("Usage: python export_run.py --label \"run-label\" [--out results/]")
        return
    label = sys.argv[sys.argv.index("--label") + 1]

    out_dir = "."
    if "--out" in sys.argv:
        out_dir = sys.argv[sys.argv.index("--out") + 1]
        os.makedirs(out_dir, exist_ok=True)

    store = SupabaseStore()
    run = store.get_run_by_label(label)
    if not run:
        print(f"No backtest run found with label '{label}'")
        return

    trades = store.get_trades_for_run(run["id"])

    safe_label = label.replace(" ", "_")

    # --- CSV of trades ---
    csv_path = os.path.join(out_dir, f"{safe_label}_trades.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "ticker", "entry_date", "entry_price", "exit_date", "exit_price", "shares",
            "pnl", "return_pct", "exit_reason", "sizing_method", "initial_risk_dollars",
            "r_multiple", "entry_log", "exit_log",
        ])
        for t in trades:
            writer.writerow([
                t["ticker"], t["entry_date"], t["entry_price"], t["exit_date"],
                t["exit_price"], t["shares"], t["pnl"], t["return_pct"], t["exit_reason"],
                t.get("sizing_method"), t.get("initial_risk_dollars"), t.get("r_multiple"),
                t.get("entry_log"), t.get("exit_log"),
            ])
    print(f"Wrote {len(trades)} trades to {csv_path}")

    # --- Markdown summary ---
    md_path = os.path.join(out_dir, f"{safe_label}_summary.md")
    metrics = run["metrics"]
    with open(md_path, "w") as f:
        f.write(f"# Backtest run: {label}\n\n")
        f.write(f"Run at: {run['created_at']}\n\n")
        f.write(f"Watchlist: {', '.join(run['watchlist'])}\n\n")
        f.write(f"Period: {run['start_date']} to {run['end_date']}\n\n")
        f.write("## Metrics\n\n")
        f.write("| Metric | Value |\n|---|---|\n")
        for k, v in metrics.items():
            f.write(f"| {k} | {v} |\n")
        f.write("\n## Config used\n\n```yaml\n")
        f.write(json.dumps(run["config"], indent=2))
        f.write("\n```\n")
    print(f"Wrote summary to {md_path}")


if __name__ == "__main__":
    main()
