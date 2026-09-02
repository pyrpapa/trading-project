import { useState } from "react";
import { supabase } from "../lib/supabaseClient.js";
import { Panel, Table, Empty, fmtPct, pnlColor } from "./PositionsTable.jsx";

const BASE_CONFIGS = [
  { value: "config/strategy_master.yaml", label: "strategy_master.yaml (live default)" },
  { value: "config/strategy_master_crypto_v36.yaml", label: "strategy_master_crypto_v36.yaml (preserved crypto track)" },
  { value: "__custom__", label: "Other (enter a path)…" },
];

// Curated knobs -- matches api/backtest.js's FIELD_PATHS exactly. Kept
// as a subset of what parameter_sweep.py already treats as the
// commonly-tuned parameters, not every key in a strategy config;
// anything else goes in the advanced YAML box below.
const FIELDS = [
  { key: "watchlist", label: "Watchlist (comma-separated tickers)", type: "text", placeholder: "leave blank to use the base config's" },
  { key: "start_date", label: "Start date", type: "date" },
  { key: "end_date", label: "End date", type: "date" },
  { key: "starting_cash", label: "Starting cash ($)", type: "number" },
  { key: "ma_period", label: "Entry MA period (days)", type: "number" },
  { key: "stop_loss_pct", label: "Stop-loss (%)", type: "number", step: "0.5" },
  { key: "take_profit_pct", label: "Take-profit (%, blank = disabled)", type: "number", step: "0.5" },
  { key: "risk_pct_per_unit", label: "Risk per unit (% of equity)", type: "number", step: "0.1" },
  { key: "stop_atr_multiple", label: "Stop distance (× ATR/N)", type: "number", step: "0.1" },
  { key: "max_position_pct", label: "Max position size (% of equity)", type: "number", step: "1" },
  { key: "max_invested_pct", label: "Max total invested (% of equity)", type: "number", step: "1" },
];

const METRIC_COLS = ["total_return_pct", "max_drawdown_pct", "calmar_ratio", "sortino_ratio", "alpha_pct", "n_trades"];
const METRIC_LABELS = {
  total_return_pct: "Return", max_drawdown_pct: "Max DD", calmar_ratio: "Calmar",
  sortino_ratio: "Sortino", alpha_pct: "Alpha", n_trades: "Trades",
};

export default function BacktestPage() {
  const [baseConfig, setBaseConfig] = useState(BASE_CONFIGS[0].value);
  const [customPath, setCustomPath] = useState("");
  const [fields, setFields] = useState({});
  const [advancedYaml, setAdvancedYaml] = useState("");
  const [runLabel, setRunLabel] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null); // "submitted" | error string | null
  const [recentRuns, setRecentRuns] = useState([]);
  const [loadingRuns, setLoadingRuns] = useState(false);

  async function loadRecentRuns() {
    setLoadingRuns(true);
    const { data } = await supabase.from("backtest_runs").select("*").order("created_at", { ascending: false }).limit(10);
    setRecentRuns(data ?? []);
    setLoadingRuns(false);
  }

  function updateField(key, value) {
    setFields((f) => ({ ...f, [key]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setResult(null);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      const formFields = {};
      for (const f of FIELDS) {
        const raw = fields[f.key];
        if (raw === undefined || raw === "") continue;
        formFields[f.key] = f.key === "watchlist"
          ? raw.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean)
          : f.type === "number" ? Number(raw) : raw;
      }
      const resp = await fetch("/api/backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${session?.access_token}` },
        body: JSON.stringify({
          baseConfig: baseConfig === "__custom__" ? customPath : baseConfig,
          formFields,
          advancedYaml,
          runLabel,
        }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);
      setResult("submitted");
    } catch (err) {
      setResult(String(err.message || err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ padding: "20px 24px 24px 24px", display: "flex", gap: 12, flexWrap: "wrap" }}>
      <Panel title="Run a custom backtest">
        <form onSubmit={handleSubmit}>
          <label style={labelStyle}>Base config</label>
          <select value={baseConfig} onChange={(e) => setBaseConfig(e.target.value)} style={inputStyle}>
            {BASE_CONFIGS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          {baseConfig === "__custom__" && (
            <input
              type="text"
              value={customPath}
              onChange={(e) => setCustomPath(e.target.value)}
              placeholder="config/strategy_v40_tight_stops.yaml"
              style={{ ...inputStyle, marginTop: 8 }}
            />
          )}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px 16px", marginTop: 16 }}>
            {FIELDS.map((f) => (
              <div key={f.key}>
                <label style={labelStyle}>{f.label}</label>
                <input
                  type={f.type}
                  step={f.step}
                  placeholder={f.placeholder}
                  value={fields[f.key] ?? ""}
                  onChange={(e) => updateField(f.key, e.target.value)}
                  style={inputStyle}
                />
              </div>
            ))}
          </div>

          <label style={{ ...labelStyle, marginTop: 16 }}>
            Advanced — extra YAML, merged on top of everything above (e.g. <code>risk:{"\n"}{"  "}pyramiding:{"\n"}{"    "}enabled: false</code>)
          </label>
          <textarea
            value={advancedYaml}
            onChange={(e) => setAdvancedYaml(e.target.value)}
            rows={6}
            style={{ ...inputStyle, fontFamily: "var(--font-mono)", fontSize: 12, resize: "vertical" }}
          />

          <label style={{ ...labelStyle, marginTop: 16 }}>Run label</label>
          <input
            type="text"
            value={runLabel}
            onChange={(e) => setRunLabel(e.target.value)}
            placeholder="e.g. tighter-stop-test"
            style={inputStyle}
          />

          <button type="submit" disabled={submitting} style={submitButtonStyle}>
            {submitting ? "Submitting…" : "Run backtest"}
          </button>

          {result === "submitted" && (
            <div style={{ color: "var(--positive)", fontSize: 13, marginTop: 12 }}>
              Submitted — this runs in GitHub Actions and can take a minute or more depending on the
              date range. Click "Check for results" below once it's had time to finish.
            </div>
          )}
          {result && result !== "submitted" && (
            <div style={{ color: "var(--negative)", fontSize: 13, marginTop: 12 }}>Failed: {result}</div>
          )}
        </form>
      </Panel>

      <Panel
        title="Recent backtest runs"
        action={<button onClick={loadRecentRuns} disabled={loadingRuns} style={refreshButtonStyle}>{loadingRuns ? "Loading…" : "Check for results"}</button>}
      >
        {recentRuns.length === 0 ? (
          <Empty text='No runs loaded yet — click "Check for results" above.' />
        ) : (
          <Table
            headers={["Run", "Watchlist", "Window", ...METRIC_COLS.map((c) => METRIC_LABELS[c])]}
            rows={recentRuns.map((r) => [
              r.run_label || `#${r.id}`,
              (r.watchlist || []).join(", "),
              `${r.start_date} → ${r.end_date}`,
              ...METRIC_COLS.map((c) => {
                const v = r.metrics?.[c];
                if (v == null) return "—";
                return c.includes("pct") // covers total_return_pct, max_drawdown_pct, alpha_pct
                  ? <span style={{ color: pnlColor(v) }}>{fmtPct(v)}</span>
                  : typeof v === "number" ? v.toFixed(2) : v;
              }),
            ])}
          />
        )}
      </Panel>
    </div>
  );
}

const labelStyle = {
  display: "block",
  fontSize: 12,
  color: "var(--text-muted)",
  marginBottom: 6,
};

const inputStyle = {
  width: "100%",
  padding: "8px 10px",
  background: "var(--surface-raised)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  color: "var(--text-primary)",
  fontSize: 13,
  fontFamily: "var(--font-body)",
};

const submitButtonStyle = {
  width: "100%",
  marginTop: 20,
  padding: "10px 0",
  background: "var(--accent)",
  color: "var(--bg)",
  border: "none",
  borderRadius: "var(--radius)",
  fontWeight: 600,
  fontSize: 14,
};

const refreshButtonStyle = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  color: "var(--text-primary)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  padding: "4px 10px",
  cursor: "pointer",
};
