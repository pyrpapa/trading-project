import { useState, useEffect, useCallback } from "react";
import { load as yamlLoad } from "js-yaml";
import { supabase } from "../lib/supabaseClient.js";
import { Panel, Table, Empty, fmtPct, pnlColor } from "./PositionsTable.jsx";
import TickerPicker from "./TickerPicker.jsx";

const REPO = "pyrpapa/trading-project";

const BASE_CONFIGS = [
  { value: "config/strategy_master.yaml", label: "strategy_master.yaml (live default)" },
  { value: "config/strategy_master_crypto_v36.yaml", label: "strategy_master_crypto_v36.yaml (preserved crypto track)" },
  { value: "__custom__", label: "Other (enter a path)…" },
];

// Curated fields, grouped to match config/strategy_master.yaml's own
// section layout. Each field carries its own `help` text inline now
// (shown right under the input, not in a separate section) and a
// dotted `path` used both to pre-fill the field from the chosen base
// config and to write it back into the merged config server-side.
//
// This same key->path mapping is duplicated in api/backtest.js's
// FIELD_PATHS -- keep the two in sync if you add/rename a field here.
const FIELD_GROUPS = [
  {
    title: "General",
    fields: [
      { key: "start_date", label: "Start date", path: "backtest.start_date", type: "date", help: "First day of the simulated period." },
      { key: "end_date", label: "End date", path: "backtest.end_date", type: "date", help: "Last day of the simulated period." },
      { key: "starting_cash", label: "Starting cash ($)", path: "backtest.starting_cash", type: "number", help: "Simulated account balance on day one." },
    ],
  },
  {
    title: "Entry",
    fields: [
      { key: "entry_type", label: "Entry rule", path: "entry.type", type: "select", options: ["ma_crossover", "donchian_breakout", "always"], help: "ma_crossover buys the first day price closes above its MA; donchian_breakout buys any day price closes above its N-day high; always buys back in immediately after any exit (isolates whether entry timing itself adds value)." },
      { key: "ma_period", label: "MA period (days)", path: "entry.ma_period", type: "number", help: "Moving-average length for the ma_crossover entry rule (and the ma_crossover trend-exit rule, if selected)." },
      { key: "breakout_period", label: "Donchian breakout period (days)", path: "entry.breakout_period", type: "number", help: "Lookback window for the donchian_breakout entry rule's N-day high." },
      { key: "volume_confirmation", label: "Require volume confirmation", path: "entry.volume_confirmation", type: "boolselect", help: "If enabled, an entry also requires that day's volume to be above its own moving average." },
      { key: "volume_ma_period", label: "Volume MA period (days)", path: "entry.volume_ma_period", type: "number", help: "Moving-average length for the volume-confirmation check above." },
      { key: "regime_filter_period", label: "Regime filter period (days, 0 = off)", path: "entry.regime_filter_period", type: "number", help: "A much slower MA the fast entry signal must also be above (a macro trend filter). 0 disables it." },
      { key: "choppiness_filter_period", label: "Choppiness filter period (days)", path: "entry.choppiness_filter_period", type: "number", help: "Lookback window for the choppiness index (how efficiently price is trending vs. chopping sideways)." },
      { key: "choppiness_threshold", label: "Choppiness threshold (blank = off)", path: "entry.choppiness_threshold", type: "number", step: "1", help: "Blocks entries when the choppiness index is above this value (market judged to be ranging, not trending). Blank disables the filter." },
    ],
  },
  {
    title: "Exit",
    fields: [
      { key: "exit_type", label: "Trend-exit rule", path: "exit.type", type: "select", options: ["ma_crossover", "donchian_low"], help: "ma_crossover exits the first day price closes back below its MA; donchian_low exits the first day price closes below its N-day low (more tolerant of pullbacks)." },
      { key: "ma_exit", label: "Trend-exit enabled", path: "exit.ma_exit", type: "boolselect", help: "Master on/off switch for the trend-exit rule above — disabled means only the stop-loss/take-profit can close a position." },
      { key: "exit_breakout_period", label: "Donchian exit period (days)", path: "exit.exit_breakout_period", type: "number", help: "Lookback window for the donchian_low trend-exit rule's N-day low." },
      { key: "stop_loss_pct", label: "Stop-loss (%)", path: "exit.stop_loss_pct", type: "number", step: "0.5", help: "Flat-percent stop-loss below entry price. Ignored if sizing method is atr_unit (that mode uses stop distance × ATR instead)." },
      { key: "take_profit_pct", label: "Take-profit (%, blank = disabled)", path: "exit.take_profit_pct", type: "number", step: "0.5", help: "Flat-percent take-profit above entry price. Blank means only stops and the trend-exit rule can close a winner." },
    ],
  },
  {
    title: "Risk & sizing",
    fields: [
      { key: "sizing_method", label: "Sizing method", path: "risk.sizing_method", type: "select", options: ["pct", "atr_unit"], help: "pct sizes every position the same % of equity. atr_unit (Turtle-style) sizes by volatility — calmer tickers get bigger positions for the same dollar risk — and is required for pyramiding." },
      { key: "atr_period", label: "ATR period (days)", path: "risk.atr_period", type: "number", help: "Lookback window for ATR (\"N\"), the volatility measure atr_unit sizing and ATR-based stops are built on." },
      { key: "risk_pct_per_unit", label: "Risk per unit (% of equity)", path: "risk.risk_pct_per_unit", type: "number", step: "0.1", help: "% of equity risked on one unit, atr_unit sizing only — position size = (this % of equity) ÷ (stop distance in $)." },
      { key: "stop_atr_multiple", label: "Stop distance (× ATR/N)", path: "risk.stop_atr_multiple", type: "number", step: "0.1", help: "Stop-loss distance from entry, in multiples of ATR/N, atr_unit sizing only." },
      { key: "max_position_pct", label: "Max position size (% of equity)", path: "risk.max_position_pct", type: "number", step: "1", help: "Hard cap on any single ticker's position size, regardless of what the sizing formula would otherwise produce." },
      { key: "max_invested_pct", label: "Max total invested (% of equity)", path: "risk.max_invested_pct", type: "number", step: "1", help: "Hard cap on total capital deployed across all open positions at once." },
    ],
  },
  {
    title: "Pyramiding",
    fields: [
      { key: "pyramiding_enabled", label: "Pyramiding enabled", path: "risk.pyramiding.enabled", type: "boolselect", help: "Allows adding more units to an already-open, winning position as price moves further in its favor. Requires atr_unit sizing." },
      { key: "pyramiding_unit_interval_n", label: "Add unit every N moved further (× ATR)", path: "risk.pyramiding.unit_interval_n", type: "number", step: "0.1", help: "Price must move this many multiples of ATR/N further in the position's favor (since the LAST unit's own entry) before another unit is added." },
      { key: "pyramiding_max_units", label: "Max units per position", path: "risk.pyramiding.max_units", type: "number", help: "Ceiling on how many units one position can stack up to." },
    ],
  },
  {
    title: "Trailing stop",
    fields: [
      { key: "trailing_stop_enabled", label: "Trailing stop enabled", path: "risk.trailing_stop.enabled", type: "boolselect", help: "Adds a second stop that trails up behind the position's peak price (never down), on top of the regular stop-loss — whichever stop is tighter wins." },
      { key: "trailing_stop_atr_multiple", label: "Trailing distance (× ATR/N)", path: "risk.trailing_stop.atr_multiple", type: "number", step: "0.1", help: "How far behind the peak price the trailing stop sits, in multiples of ATR/N." },
    ],
  },
];
const ALL_FIELDS = FIELD_GROUPS.flatMap((g) => g.fields);

const METRIC_COLS = ["total_return_pct", "max_drawdown_pct", "calmar_ratio", "sortino_ratio", "alpha_pct", "n_trades"];
const METRIC_LABELS = {
  total_return_pct: "Return", max_drawdown_pct: "Max DD", calmar_ratio: "Calmar",
  sortino_ratio: "Sortino", alpha_pct: "Alpha", n_trades: "Trades",
};

function getPath(obj, dottedPath) {
  return dottedPath.split(".").reduce((node, key) => (node == null ? undefined : node[key]), obj);
}

// Parsed-YAML value -> the string an <input>/<select> wants. null/undefined
// become "" (an empty field), which is exactly right for the nullable
// fields (take_profit_pct, choppiness_threshold) and harmless for the rest.
function toFieldString(value) {
  if (value === null || value === undefined) return "";
  return String(value);
}

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
  const [loadingBase, setLoadingBase] = useState(false);
  const [baseError, setBaseError] = useState(null);

  const activeBasePath = baseConfig === "__custom__" ? customPath : baseConfig;

  // Pre-fills the whole form from whatever base config is currently
  // selected -- fetched fresh (client-side, GitHub's raw content API
  // allows cross-origin reads on public repos) rather than bundling a
  // copy, same reasoning as api/backtest.js's own fetch.
  const loadBaseConfig = useCallback(async (path) => {
    if (!path) return;
    setLoadingBase(true);
    setBaseError(null);
    try {
      const resp = await fetch(`https://raw.githubusercontent.com/${REPO}/main/${path}`);
      if (!resp.ok) throw new Error(`couldn't fetch ${path} (${resp.status})`);
      const cfg = yamlLoad(await resp.text());
      if (typeof cfg !== "object" || cfg === null) throw new Error(`${path} didn't parse into a config`);

      const newFields = {};
      for (const f of ALL_FIELDS) newFields[f.key] = toFieldString(getPath(cfg, f.path));
      setFields(newFields);

      const watchlist = Array.isArray(cfg.watchlist) ? cfg.watchlist : [];
      const known = new Set(watchlist.filter((t) => KNOWN_TICKERS.has(t)));
      setSelectedTickers([...known]);
      setCustomTickerText(watchlist.filter((t) => !known.has(t)).join(", "));
    } catch (e) {
      setBaseError(String(e.message || e));
    } finally {
      setLoadingBase(false);
    }
  }, []);

  useEffect(() => {
    if (baseConfig !== "__custom__") loadBaseConfig(baseConfig);
  }, [baseConfig, loadBaseConfig]);

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
    if (raw === undefined || raw === "") return null; // blank means null in the config (take_profit_pct, choppiness_threshold)
    if (f.type === "number") return Number(raw);
    if (f.type === "boolselect") return raw === "true";
    return raw; // text, date, select
  }

  function buildFormFields() {
    const formFields = { watchlist: watchlistValue() };
    for (const f of ALL_FIELDS) formFields[f.key] = coerceField(f, fields[f.key]);
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
        baseConfig: activeBasePath,
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
      <Panel
        title="Run a custom backtest"
        action={
          <button type="button" onClick={() => loadBaseConfig(activeBasePath)} disabled={loadingBase} style={refreshButtonStyle}>
            {loadingBase ? "Loading…" : "Reload from base config"}
          </button>
        }
      >
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
              onBlur={() => loadBaseConfig(customPath)}
              placeholder="config/strategy_v40_tight_stops.yaml — press Tab/click away to load"
              style={{ ...inputStyle, marginTop: 8 }}
            />
          )}
          {baseError && <div style={{ color: "var(--negative)", fontSize: 12, marginTop: 6 }}>{baseError}</div>}
          <div style={{ color: "var(--text-faint)", fontSize: 11, marginTop: 6 }}>
            Every field below is pre-filled from this config — edit whatever you want to change, leave the rest as-is.
          </div>

          <div style={{ marginTop: 20 }}>
            <div style={groupTitleStyle}>General</div>
            <div style={{ marginBottom: 12 }}>
              <label style={labelStyle}>Watchlist</label>
              <TickerPicker
                selected={selectedTickers}
                onChange={setSelectedTickers}
                customText={customTickerText}
                onCustomTextChange={setCustomTickerText}
              />
              <div style={helpStyle}>Tickers the backtest considers.</div>
            </div>
            <FieldGrid fields={FIELD_GROUPS[0].fields} values={fields} onChange={updateField} />
          </div>

          {FIELD_GROUPS.slice(1).map((group) => (
            <div key={group.title} style={{ marginTop: 20 }}>
              <div style={groupTitleStyle}>{group.title}</div>
              <FieldGrid fields={group.fields} values={fields} onChange={updateField} />
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
            Strategy name — labels this run below, and names the file if you export
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
              date range. Click "Check for results" below once it's had time to finish.
            </div>
          )}
          {result && result !== "submitted" && (
            <div style={{ color: "var(--negative)", fontSize: 13, marginTop: 12 }}>Failed: {result}</div>
          )}
        </form>
      </Panel>

      <div style={{ marginTop: 12 }}>
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
    </div>
  );
}

function FieldGrid({ fields, values, onChange }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "14px 16px" }}>
      {fields.map((f) => (
        <div key={f.key}>
          <label style={labelStyle}>{f.label}</label>
          {f.type === "select" || f.type === "boolselect" ? (
            <select value={values[f.key] ?? ""} onChange={(e) => onChange(f.key, e.target.value)} style={inputStyle}>
              {f.type === "boolselect"
                ? [<option key="true" value="true">Enabled</option>, <option key="false" value="false">Disabled</option>]
                : f.options.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : (
            <input
              type={f.type}
              step={f.step}
              value={values[f.key] ?? ""}
              onChange={(e) => onChange(f.key, e.target.value)}
              style={inputStyle}
            />
          )}
          <div style={helpStyle}>{f.help}</div>
        </div>
      ))}
    </div>
  );
}

// Mirrors TickerPicker.jsx's own list -- used to split a loaded config's
// watchlist between "matches a picker chip" (highlighted) and "not in
// the curated list" (falls into the free-text custom field instead).
const KNOWN_TICKERS = new Set([
  "SPXL", "TQQQ", "SOXL", "FAS", "TNA", "TECL", "ERX", "TMF", "YINN", "DRN", "CURE",
  "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLU", "XLY", "XLP", "XLB", "XLRE",
  "TLT", "AGG", "GLD", "SLV", "DBC", "VNQ", "VEA",
  "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "NFLX", "JPM", "V", "WMT", "DIS", "BA", "XOM", "UNH", "HD", "PG", "MA", "COST",
  "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "LINK-USD", "AVAX-USD", "LTC-USD", "ADA-USD", "DOT-USD", "UNI-USD", "BCH-USD", "FIL-USD", "RENDER-USD", "AAVE-USD", "CRV-USD", "LDO-USD",
]);

const labelStyle = {
  display: "block",
  fontSize: 12,
  color: "var(--text-muted)",
  marginBottom: 6,
};

const helpStyle = {
  fontSize: 11,
  color: "var(--text-faint)",
  marginTop: 4,
  lineHeight: 1.4,
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
