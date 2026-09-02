import { useState } from "react";
import { supabase } from "../lib/supabaseClient.js";
import { Panel, Table, Empty, fmtPct, pnlColor } from "./PositionsTable.jsx";
import TickerPicker from "./TickerPicker.jsx";

const BASE_CONFIGS = [
  { value: "config/strategy_master.yaml", label: "strategy_master.yaml (live default)" },
  { value: "config/strategy_master_crypto_v36.yaml", label: "strategy_master_crypto_v36.yaml (preserved crypto track)" },
  { value: "__custom__", label: "Other (enter a path)…" },
];

// Curated fields, grouped to match config/strategy_master.yaml's own
// section layout (watchlist/backtest, entry, exit, risk, pyramiding,
// trailing_stop) -- this is meant to cover everything someone would
// normally want to tune without touching YAML at all. "select" fields
// get a blank "(use base config's)" first option so leaving a field
// alone always means "inherit," same as every other field type here.
// "boolselect" is the same idea for on/off knobs -- a real HTML
// checkbox has no natural "unset" state, so booleans get a 3-way
// select instead (blank / Enabled / Disabled) to keep that same
// "blank = inherit" rule everywhere in this form.
//
// Each `key` maps 1:1 to an entry in api/backtest.js's FIELD_PATHS --
// keep the two in sync if you add/rename a field here.
const FIELD_GROUPS = [
  {
    title: "General",
    // watchlist is deliberately NOT here -- it gets the dedicated
    // TickerPicker UI instead of a generic field, but keeps its
    // FIELD_HELP entry below and its own row in the reference key.
    fields: [
      { key: "start_date", label: "Start date", type: "date" },
      { key: "end_date", label: "End date", type: "date" },
      { key: "starting_cash", label: "Starting cash ($)", type: "number" },
    ],
  },
  {
    title: "Entry",
    fields: [
      { key: "entry_type", label: "Entry rule", type: "select", options: ["ma_crossover", "donchian_breakout", "always"] },
      { key: "ma_period", label: "MA period (days)", type: "number" },
      { key: "breakout_period", label: "Donchian breakout period (days)", type: "number" },
      { key: "volume_confirmation", label: "Require volume confirmation", type: "boolselect" },
      { key: "volume_ma_period", label: "Volume MA period (days)", type: "number" },
      { key: "regime_filter_period", label: "Regime filter period (days, 0 = off)", type: "number" },
      { key: "choppiness_filter_period", label: "Choppiness filter period (days)", type: "number" },
      { key: "choppiness_threshold", label: "Choppiness threshold (blank = off)", type: "number", step: "1" },
    ],
  },
  {
    title: "Exit",
    fields: [
      { key: "exit_type", label: "Trend-exit rule", type: "select", options: ["ma_crossover", "donchian_low"] },
      { key: "ma_exit", label: "Trend-exit enabled", type: "boolselect" },
      { key: "exit_breakout_period", label: "Donchian exit period (days)", type: "number" },
      { key: "stop_loss_pct", label: "Stop-loss (%)", type: "number", step: "0.5" },
      { key: "take_profit_pct", label: "Take-profit (%, blank = disabled)", type: "number", step: "0.5" },
    ],
  },
  {
    title: "Risk & sizing",
    fields: [
      { key: "sizing_method", label: "Sizing method", type: "select", options: ["pct", "atr_unit"] },
      { key: "atr_period", label: "ATR period (days)", type: "number" },
      { key: "risk_pct_per_unit", label: "Risk per unit (% of equity)", type: "number", step: "0.1" },
      { key: "stop_atr_multiple", label: "Stop distance (× ATR/N)", type: "number", step: "0.1" },
      { key: "max_position_pct", label: "Max position size (% of equity)", type: "number", step: "1" },
      { key: "max_invested_pct", label: "Max total invested (% of equity)", type: "number", step: "1" },
    ],
  },
  {
    title: "Pyramiding",
    fields: [
      { key: "pyramiding_enabled", label: "Pyramiding enabled", type: "boolselect" },
      { key: "pyramiding_unit_interval_n", label: "Add unit every N moved further (× ATR)", type: "number", step: "0.1" },
      { key: "pyramiding_max_units", label: "Max units per position", type: "number" },
    ],
  },
  {
    title: "Trailing stop",
    fields: [
      { key: "trailing_stop_enabled", label: "Trailing stop enabled", type: "boolselect" },
      { key: "trailing_stop_atr_multiple", label: "Trailing distance (× ATR/N)", type: "number", step: "0.1" },
    ],
  },
];

// Plain-language definitions for the reference key at the bottom.
// Written to match this project's own explanations in strategy/rules.py
// and config/strategy_master.yaml's comments, not reworded from
// scratch, so they stay accurate to what the code actually does.
const FIELD_HELP = {
  watchlist: "Tickers the backtest considers. Comma-separated, e.g. \"SPXL, TQQQ, SOXL\".",
  start_date: "First day of the simulated period.",
  end_date: "Last day of the simulated period.",
  starting_cash: "Simulated account balance on day one.",
  entry_type: "\"ma_crossover\" buys the first day price closes above its MA; \"donchian_breakout\" buys any day price closes above its N-day high; \"always\" buys back in immediately after any exit (isolates whether the entry timing itself adds value).",
  ma_period: "Moving-average length used by the ma_crossover entry rule (and the ma_crossover trend-exit rule, if selected).",
  breakout_period: "Lookback window for the donchian_breakout entry rule's N-day high.",
  volume_confirmation: "If enabled, an entry also requires that day's volume to be above its own moving average.",
  volume_ma_period: "Moving-average length for the volume-confirmation check above.",
  regime_filter_period: "A much slower MA the fast entry signal must also be above (a macro trend filter). 0 disables it.",
  choppiness_filter_period: "Lookback window for the choppiness index (how efficiently price is trending vs. chopping sideways).",
  choppiness_threshold: "Blocks entries when the choppiness index is above this value (market judged to be ranging, not trending). Blank disables the filter.",
  exit_type: "\"ma_crossover\" exits the first day price closes back below its MA; \"donchian_low\" exits the first day price closes below its N-day low (more tolerant of pullbacks).",
  ma_exit: "Master on/off switch for the trend-exit rule above -- disabled means only the stop-loss/take-profit can close a position.",
  exit_breakout_period: "Lookback window for the donchian_low trend-exit rule's N-day low.",
  stop_loss_pct: "Flat-percent stop-loss below entry price. Ignored if sizing_method is atr_unit (that mode uses stop_atr_multiple instead).",
  take_profit_pct: "Flat-percent take-profit above entry price. Blank/disabled means only stops and the trend-exit rule can close a winner.",
  sizing_method: "\"pct\" sizes every position the same % of equity. \"atr_unit\" (Turtle-style) sizes by volatility -- calmer tickers get bigger positions for the same dollar risk -- and is required for pyramiding.",
  atr_period: "Lookback window for ATR (\"N\"), the volatility measure atr_unit sizing and ATR-based stops are built on.",
  risk_pct_per_unit: "% of equity risked on one unit, atr_unit sizing only -- position size = (this % of equity) ÷ (stop distance in $).",
  stop_atr_multiple: "Stop-loss distance from entry, in multiples of ATR/N, atr_unit sizing only.",
  max_position_pct: "Hard cap on any single ticker's position size, as a % of equity, regardless of what the sizing formula would otherwise produce.",
  max_invested_pct: "Hard cap on total capital deployed across all open positions at once, as a % of equity.",
  pyramiding_enabled: "Allows adding more units to an already-open, winning position as price moves further in its favor. Requires atr_unit sizing.",
  pyramiding_unit_interval_n: "Price must move this many multiples of ATR/N further in the position's favor (since the LAST unit's own entry) before another unit is added.",
  pyramiding_max_units: "Ceiling on how many units one position can stack up to.",
  trailing_stop_enabled: "Adds a second stop that trails up behind the position's peak price (never down), on top of the regular stop-loss -- whichever stop is tighter wins.",
  trailing_stop_atr_multiple: "How far behind the peak price the trailing stop sits, in multiples of ATR/N.",
};

const METRIC_COLS = ["total_return_pct", "max_drawdown_pct", "calmar_ratio", "sortino_ratio", "alpha_pct", "n_trades"];
const METRIC_LABELS = {
  total_return_pct: "Return", max_drawdown_pct: "Max DD", calmar_ratio: "Calmar",
  sortino_ratio: "Sortino", alpha_pct: "Alpha", n_trades: "Trades",
};

export default function BacktestPage() {
  const [baseConfig, setBaseConfig] = useState(BASE_CONFIGS[0].value);
  const [customPath, setCustomPath] = useState("");
  const [selectedTickers, setSelectedTickers] = useState([]);
  const [customTickerText, setCustomTickerText] = useState("");
  const [fields, setFields] = useState({});
  const [advancedYaml, setAdvancedYaml] = useState("");
  // Names both the Supabase run_label AND the exported file -- one
  // field doing double duty rather than two names to keep in sync.
  const [strategyName, setStrategyName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [result, setResult] = useState(null); // "submitted" | error string | null
  const [recentRuns, setRecentRuns] = useState([]);
  const [loadingRuns, setLoadingRuns] = useState(false);

  function watchlistValue() {
    const custom = customTickerText.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
    return [...new Set([...selectedTickers, ...custom])];
  }

  async function loadRecentRuns() {
    setLoadingRuns(true);
    const { data } = await supabase.from("backtest_runs").select("*").order("created_at", { ascending: false }).limit(10);
    setRecentRuns(data ?? []);
    setLoadingRuns(false);
  }

  function updateField(key, value) {
    setFields((f) => ({ ...f, [key]: value }));
  }

  function coerceField(f, raw) {
    if (raw === undefined || raw === "") return undefined; // untouched -- inherit from base config
    if (f.type === "number") return Number(raw);
    if (f.type === "boolselect") return raw === "true" ? true : raw === "false" ? false : undefined;
    return raw; // text, date, select
  }

  function buildFormFields() {
    const formFields = {};
    const watchlist = watchlistValue();
    if (watchlist.length > 0) formFields.watchlist = watchlist;
    for (const group of FIELD_GROUPS) {
      for (const f of group.fields) {
        const value = coerceField(f, fields[f.key]);
        if (value !== undefined) formFields[f.key] = value;
      }
    }
    return formFields;
  }

  function downloadYaml(text, filename) {
    const blob = new Blob([text], { type: "application/x-yaml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function callBacktestApi(extra) {
    const { data: { session } } = await supabase.auth.getSession();
    const resp = await fetch("/api/backtest", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${session?.access_token}` },
      body: JSON.stringify({
        baseConfig: baseConfig === "__custom__" ? customPath : baseConfig,
        formFields: buildFormFields(),
        advancedYaml,
        runLabel: strategyName,
        ...extra,
      }),
    });
    const body = await resp.json();
    if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);
    return body;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setResult(null);
    try {
      await callBacktestApi({});
      setResult("submitted");
    } catch (err) {
      setResult(String(err.message || err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleExport() {
    setExporting(true);
    setResult(null);
    try {
      const body = await callBacktestApi({ exportOnly: true });
      const filename = `${(strategyName || "custom-strategy").replace(/[^a-z0-9_-]+/gi, "-")}.yaml`;
      downloadYaml(body.configYaml, filename);
    } catch (err) {
      setResult(String(err.message || err));
    } finally {
      setExporting(false);
    }
  }

  return (
    <div style={{ padding: "20px 24px 24px 24px" }}>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
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

            {FIELD_GROUPS.map((group) => (
              <div key={group.title} style={{ marginTop: 20 }}>
                <div style={groupTitleStyle}>{group.title}</div>
                {group.title === "General" && (
                  <div style={{ marginBottom: 12 }}>
                    <label style={labelStyle}>Watchlist</label>
                    <TickerPicker
                      selected={selectedTickers}
                      onChange={setSelectedTickers}
                      customText={customTickerText}
                      onCustomTextChange={setCustomTickerText}
                    />
                  </div>
                )}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px 16px" }}>
                  {group.fields.map((f) => (
                    <div key={f.key}>
                      <label style={labelStyle}>{f.label}</label>
                      {f.type === "select" || f.type === "boolselect" ? (
                        <select
                          value={fields[f.key] ?? ""}
                          onChange={(e) => updateField(f.key, e.target.value)}
                          style={inputStyle}
                        >
                          <option value="">(use base config's)</option>
                          {f.type === "boolselect"
                            ? [<option key="true" value="true">Enabled</option>, <option key="false" value="false">Disabled</option>]
                            : f.options.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      ) : (
                        <input
                          type={f.type}
                          step={f.step}
                          placeholder={f.placeholder}
                          value={fields[f.key] ?? ""}
                          onChange={(e) => updateField(f.key, e.target.value)}
                          style={inputStyle}
                        />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}

            <label style={{ ...labelStyle, marginTop: 20 }}>
              Advanced — anything not covered above, as YAML merged on top of everything else
            </label>
            <textarea
              value={advancedYaml}
              onChange={(e) => setAdvancedYaml(e.target.value)}
              rows={4}
              placeholder={"e.g.\nrisk:\n  correlation_breaker:\n    enabled: true"}
              style={{ ...inputStyle, fontFamily: "var(--font-mono)", fontSize: 12, resize: "vertical" }}
            />

            <label style={{ ...labelStyle, marginTop: 16 }}>
              Strategy name — labels this run in the results below, and names the file if you export
            </label>
            <input
              type="text"
              value={strategyName}
              onChange={(e) => setStrategyName(e.target.value)}
              placeholder="e.g. tighter-stop-test"
              style={inputStyle}
            />

            <div style={{ display: "flex", gap: 10 }}>
              <button type="submit" disabled={submitting} style={{ ...submitButtonStyle, width: "auto", flex: 1 }}>
                {submitting ? "Submitting…" : "Run backtest"}
              </button>
              <button
                type="button"
                onClick={handleExport}
                disabled={exporting}
                style={{ ...submitButtonStyle, width: "auto", flex: 1, background: "var(--surface-raised)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              >
                {exporting ? "Exporting…" : "Export config (.yaml)"}
              </button>
            </div>

            {result === "submitted" && (
              <div style={{ color: "var(--positive)", fontSize: 13, marginTop: 12 }}>
                Submitted — this runs in GitHub Actions and can take a minute or more depending on the
                date range. Click "Check for results" once it's had time to finish.
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

      <div style={{ marginTop: 12 }}>
        <Panel title="Field reference">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "10px 24px" }}>
            {[{ key: "watchlist", label: "Watchlist" }, ...FIELD_GROUPS.flatMap((g) => g.fields)].map((f) => (
              <div key={f.key} style={{ fontSize: 12 }}>
                <span style={{ color: "var(--accent)", fontFamily: "var(--font-mono)" }}>{f.label}</span>
                <div style={{ color: "var(--text-muted)", marginTop: 2, lineHeight: 1.4 }}>{FIELD_HELP[f.key]}</div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

const labelStyle = {
  display: "block",
  fontSize: 12,
  color: "var(--text-muted)",
  marginBottom: 6,
};

const groupTitleStyle = {
  fontSize: 11,
  letterSpacing: "0.06em",
  color: "var(--accent)",
  textTransform: "uppercase",
  marginBottom: 8,
  borderBottom: "1px solid var(--border)",
  paddingBottom: 4,
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
