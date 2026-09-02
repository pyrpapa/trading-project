import { useState, useEffect, useCallback } from "react";
import { load as yamlLoad } from "js-yaml";
import { supabase } from "../lib/supabaseClient.js";
import { Panel, Table, Empty, fmtPct, pnlColor } from "./PositionsTable.jsx";
import TickerPicker from "./TickerPicker.jsx";

// Only used for pre-filling the form client-side (raw.githubusercontent.com
// has permissive CORS for public repos) -- the actual backtest run goes
// through api/run_backtest.py, a Vercel Python function with direct
// filesystem access to config/*.yaml, so it doesn't need this fetch at all.
const REPO = "pyrpapa/trading-project";

const BASE_CONFIGS = [
  { value: "config/strategy_master.yaml", label: "strategy_master.yaml (live default)", shortName: "master" },
  { value: "config/strategy_master_crypto_v36.yaml", label: "strategy_master_crypto_v36.yaml (preserved crypto track)", shortName: "crypto-v36" },
  { value: "__custom__", label: "Other (enter a path)…" },
];

// Curated fields, grouped to match config/strategy_master.yaml's own
// section layout. Each field carries its own `help` text inline (shown
// right under the input) and a dotted `path` used both to pre-fill the
// field from the chosen base config and to write it back into the
// merged config server-side.
//
// `nullable: true` marks the only two fields where a blank value is
// itself meaningful (sets that key to null in the config) -- every
// other field is required whenever it's shown (marked with * in the
// UI) and blank there just means "leave the base config's value alone."
//
// `showIf(v)` hides a field when it wouldn't do anything given the
// current values of OTHER fields (`v` is the live `fields` state, keyed
// the same way) -- e.g. the Donchian breakout lookback only matters
// when the entry rule is actually donchian_breakout. Fields with no
// showIf are always shown. Mirrors the actual gating logic in
// strategy/rules.py / backtest/engine.py -- see each field's own `help`
// for the plain-English version of why.
//
// This same key->path mapping is duplicated in api/run_backtest.py's
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
      { key: "ma_period", label: "MA period (days)", path: "entry.ma_period", type: "number", showIf: (v) => v.entry_type === "ma_crossover" || (v.ma_exit !== "false" && v.exit_type === "ma_crossover"), help: "Moving-average length for the ma_crossover entry rule (and the ma_crossover trend-exit rule, if selected)." },
      { key: "breakout_period", label: "Donchian breakout period (days)", path: "entry.breakout_period", type: "number", showIf: (v) => v.entry_type === "donchian_breakout", help: "Lookback window for the donchian_breakout entry rule's N-day high." },
      { key: "volume_confirmation", label: "Require volume confirmation", path: "entry.volume_confirmation", type: "boolselect", showIf: (v) => v.entry_type !== "always", help: "If enabled, an entry also requires that day's volume to be above its own moving average." },
      { key: "volume_ma_period", label: "Volume MA period (days)", path: "entry.volume_ma_period", type: "number", showIf: (v) => v.entry_type !== "always", help: "Moving-average length for the volume-confirmation check above." },
      { key: "regime_filter_period", label: "Regime filter period (days, 0 = off)", path: "entry.regime_filter_period", type: "number", help: "A much slower MA the fast entry signal must also be above (a macro trend filter). 0 disables it." },
      { key: "choppiness_threshold", label: "Choppiness threshold (blank = off)", path: "entry.choppiness_threshold", type: "number", step: "1", nullable: true, help: "Blocks entries when the choppiness index is above this value (market judged to be ranging, not trending). Blank disables the filter." },
      { key: "choppiness_filter_period", label: "Choppiness filter period (days)", path: "entry.choppiness_filter_period", type: "number", showIf: (v) => v.choppiness_threshold !== "", help: "Lookback window for the choppiness index used by the threshold above. Only matters when a threshold is set." },
    ],
  },
  {
    title: "Exit",
    fields: [
      { key: "ma_exit", label: "Trend-exit enabled", path: "exit.ma_exit", type: "boolselect", help: "Master on/off switch for the trend-exit rule below — disabled means only the stop-loss/take-profit can close a position." },
      { key: "exit_type", label: "Trend-exit rule", path: "exit.type", type: "select", options: ["ma_crossover", "donchian_low"], showIf: (v) => v.ma_exit !== "false", help: "ma_crossover exits the first day price closes back below its MA; donchian_low exits the first day price closes below its N-day low (more tolerant of pullbacks)." },
      { key: "exit_breakout_period", label: "Donchian exit period (days)", path: "exit.exit_breakout_period", type: "number", showIf: (v) => v.ma_exit !== "false" && v.exit_type === "donchian_low", help: "Lookback window for the donchian_low trend-exit rule's N-day low." },
      { key: "stop_loss_pct", label: "Stop-loss (%)", path: "exit.stop_loss_pct", type: "number", step: "0.5", showIf: (v) => v.sizing_method !== "atr_unit", help: "Flat-percent stop-loss below entry price. Only used when sizing method is pct — atr_unit mode uses stop distance × ATR instead (Risk & sizing section)." },
      { key: "take_profit_pct", label: "Take-profit (%, blank = disabled)", path: "exit.take_profit_pct", type: "number", step: "0.5", nullable: true, help: "Flat-percent take-profit above entry price. Blank means only stops and the trend-exit rule can close a winner." },
    ],
  },
  {
    title: "Risk & sizing",
    fields: [
      { key: "sizing_method", label: "Sizing method", path: "risk.sizing_method", type: "select", options: ["pct", "atr_unit"], help: "pct sizes every position the same % of equity. atr_unit (Turtle-style) sizes by volatility — calmer tickers get bigger positions for the same dollar risk — and is required for pyramiding." },
      { key: "atr_period", label: "ATR period (days)", path: "risk.atr_period", type: "number", showIf: (v) => v.sizing_method === "atr_unit" || v.trailing_stop_enabled === "true", help: "Lookback window for ATR (\"N\"), the volatility measure atr_unit sizing and the trailing stop are built on." },
      { key: "risk_pct_per_unit", label: "Risk per unit (% of equity)", path: "risk.risk_pct_per_unit", type: "number", step: "0.1", showIf: (v) => v.sizing_method === "atr_unit", help: "% of equity risked on one unit, atr_unit sizing only — position size = (this % of equity) ÷ (stop distance in $)." },
      { key: "stop_atr_multiple", label: "Stop distance (× ATR/N)", path: "risk.stop_atr_multiple", type: "number", step: "0.1", showIf: (v) => v.sizing_method === "atr_unit", help: "Stop-loss distance from entry, in multiples of ATR/N, atr_unit sizing only." },
      { key: "max_position_pct", label: "Max position size (% of equity)", path: "risk.max_position_pct", type: "number", step: "1", help: "Hard cap on any single ticker's position size, regardless of what the sizing formula would otherwise produce." },
      { key: "max_invested_pct", label: "Max total invested (% of equity)", path: "risk.max_invested_pct", type: "number", step: "1", help: "Hard cap on total capital deployed across all open positions at once." },
    ],
  },
  {
    title: "Pyramiding",
    fields: [
      { key: "pyramiding_enabled", label: "Pyramiding enabled", path: "risk.pyramiding.enabled", type: "boolselect", showIf: (v) => v.sizing_method === "atr_unit", help: "Allows adding more units to an already-open, winning position as price moves further in its favor. Requires atr_unit sizing (Risk & sizing section)." },
      { key: "pyramiding_unit_interval_n", label: "Add unit every N moved further (× ATR)", path: "risk.pyramiding.unit_interval_n", type: "number", step: "0.1", showIf: (v) => v.sizing_method === "atr_unit" && v.pyramiding_enabled === "true", help: "Price must move this many multiples of ATR/N further in the position's favor (since the LAST unit's own entry) before another unit is added." },
      { key: "pyramiding_max_units", label: "Max units per position", path: "risk.pyramiding.max_units", type: "number", showIf: (v) => v.sizing_method === "atr_unit" && v.pyramiding_enabled === "true", help: "Ceiling on how many units one position can stack up to." },
    ],
  },
  {
    title: "Trailing stop",
    fields: [
      { key: "trailing_stop_enabled", label: "Trailing stop enabled", path: "risk.trailing_stop.enabled", type: "boolselect", help: "Adds a second stop that trails up behind the position's peak price (never down), on top of the regular stop-loss — whichever stop is tighter wins." },
      { key: "trailing_stop_atr_multiple", label: "Trailing distance (× ATR/N)", path: "risk.trailing_stop.atr_multiple", type: "number", step: "0.1", showIf: (v) => v.trailing_stop_enabled === "true", help: "How far behind the peak price the trailing stop sits, in multiples of ATR/N." },
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
  // What the custom run gets compared against -- defaults to master
  // (BASE_CONFIGS[0]) but can point at any other config, same picker
  // shape as "Base config" above (including its own "Other" path entry).
  const [compareConfig, setCompareConfig] = useState(BASE_CONFIGS[0].value);
  const [compareCustomPath, setCompareCustomPath] = useState("");
  const [selectedTickers, setSelectedTickers] = useState([]);
  const [customTickerText, setCustomTickerText] = useState("");
  const [fields, setFields] = useState({});
  const [advancedYaml, setAdvancedYaml] = useState("");
  // Names both the Supabase run_label AND the exported file -- one
  // field doing double duty rather than two names to keep in sync.
  const [strategyName, setStrategyName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState(null);
  // api/run_backtest.py runs synchronously and returns metrics directly
  // -- no dispatch-and-poll dance, so this is just the last response,
  // not a running history. { custom: {run_label, metrics, report_url},
  // compare: {...} } | null. Cleared on every new submit so a stale
  // pair's results don't linger next to a fresh one.
  const [results, setResults] = useState(null);
  const [loadingBase, setLoadingBase] = useState(false);
  const [baseError, setBaseError] = useState(null);

  const activeBasePath = baseConfig === "__custom__" ? customPath : baseConfig;
  const activeComparePath = compareConfig === "__custom__" ? compareCustomPath : compareConfig;
  const compareLabelSuffix = BASE_CONFIGS.find((c) => c.value === compareConfig)?.shortName
    ?? (activeComparePath.split("/").pop()?.replace(/\.ya?ml$/, "") || "compare");

  // Pre-fills the whole form from whatever base config is currently
  // selected -- fetched fresh, client-side, from GitHub's raw content
  // API (permissive CORS on public repos). Purely a form-prefill
  // convenience; the actual run reads config/*.yaml directly off disk
  // in api/run_backtest.py, no fetch involved there.
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

  function updateField(key, value) {
    setFields((f) => ({ ...f, [key]: value }));
  }

  function coerceField(f, raw) {
    if (raw === undefined || raw === "") {
      // Only the two fields explicitly marked nullable (take_profit_pct,
      // choppiness_threshold) treat blank as a real "set this to null"
      // value -- everything else (ma_period, stop_loss_pct, etc.) is a
      // required number in the config, and run_backtest.py crashes on
      // None there (its lookback_days = max(...) call has no None
      // handling). Every other field is always pre-filled with a real
      // value anyway, so blank on one of those means "skip -- leave
      // whatever the base config already had," not "null it out."
      return f.nullable ? null : undefined;
    }
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

  // api/run_backtest.py runs synchronously (a Vercel Python function with
  // direct repo access, not a GitHub Actions dispatch) and returns
  // metrics directly -- one request does both the custom run and its
  // comparison baseline, no separate dispatch-then-poll steps anymore.
  async function callRunBacktestApi(body) {
    const { data: { session } } = await supabase.auth.getSession();
    const resp = await fetch("/api/run_backtest", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${session?.access_token}` },
      body: JSON.stringify(body),
    });
    const responseBody = await resp.json();
    if (!resp.ok) throw new Error(responseBody.error || `HTTP ${resp.status}`);
    return responseBody;
  }

  function customSpec(runLabel) {
    return { baseConfig: activeBasePath, formFields: buildFormFields(), advancedYaml, runLabel };
  }

  function compareSpec(runLabel) {
    // Same start/end/starting-cash as the custom run (an apples-to-apples
    // window and account size), but otherwise the comparison config
    // completely unmodified -- none of the custom form's other fields
    // carry over here, on purpose.
    return {
      baseConfig: activeComparePath,
      runLabel,
      formFields: {
        start_date: fields.start_date || undefined,
        end_date: fields.end_date || undefined,
        starting_cash: fields.starting_cash ? Number(fields.starting_cash) : undefined,
      },
    };
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!activeComparePath) {
      setError("Pick a comparison config, or enter a path for it, before running.");
      return;
    }
    setSubmitting(true);
    setError(null);
    setResults(null);
    try {
      const label = strategyName || `custom-${Date.now()}`;
      const baselineLabel = `${label}-vs-${compareLabelSuffix}`;
      const body = await callRunBacktestApi({ custom: customSpec(label), compare: compareSpec(baselineLabel) });
      // compareLabelSuffix is snapshotted here, not read live in the
      // render -- the dropdown could change before this response lands,
      // and the results panel should describe what actually ran.
      setResults({ custom: body.custom, compare: body.compare, compareName: compareLabelSuffix });
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleExport() {
    setExporting(true);
    setError(null);
    try {
      const label = strategyName || "custom-strategy";
      const body = await callRunBacktestApi({ custom: customSpec(label), exportOnly: true });
      const filename = `${label.replace(/[^a-z0-9_-]+/gi, "-")}.yaml`;
      downloadYaml(body.custom.configYaml, filename);
    } catch (err) {
      setError(String(err.message || err));
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
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px 16px" }}>
            <div>
              <label style={labelStyle}>Base config <span style={{ color: "var(--negative)" }}>*</span></label>
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
              <div style={helpStyle}>What every field below pre-fills from — this is the config you're customizing.</div>
            </div>
            <div>
              <label style={labelStyle}>Compare against <span style={{ color: "var(--negative)" }}>*</span></label>
              <select value={compareConfig} onChange={(e) => setCompareConfig(e.target.value)} style={inputStyle}>
                {BASE_CONFIGS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
              {compareConfig === "__custom__" && (
                <input
                  type="text"
                  value={compareCustomPath}
                  onChange={(e) => setCompareCustomPath(e.target.value)}
                  placeholder="config/strategy_v40_tight_stops.yaml"
                  style={{ ...inputStyle, marginTop: 8 }}
                />
              )}
              <div style={helpStyle}>Runs alongside yours, same window and starting cash, otherwise unmodified. Defaults to master — pick a different config to compare against something else instead.</div>
            </div>
          </div>
          <div style={{ color: "var(--text-faint)", fontSize: 11, marginTop: 10 }}>
            Every field below is pre-filled from the base config — edit whatever you want to change, leave the rest as-is.
            Fields marked <span style={{ color: "var(--negative)" }}>*</span> are required whenever shown; unmarked fields can be left blank.
            Fields that only matter for a particular choice elsewhere (e.g. the entry rule, or sizing method) only appear once that choice is selected.
          </div>

          <div style={{ marginTop: 20 }}>
            <div style={groupTitleStyle}>General</div>
            <div style={{ marginBottom: 12 }}>
              <label style={labelStyle}>Watchlist <span style={{ color: "var(--negative)" }}>*</span></label>
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
            visibleFields(group.fields, fields).length > 0 && (
              <div key={group.title} style={{ marginTop: 20 }}>
                <div style={groupTitleStyle}>{group.title}</div>
                <FieldGrid fields={group.fields} values={fields} onChange={updateField} />
              </div>
            )
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
            Strategy name — labels this run below and names the file if you export. Running also
            launches a same-window, same-starting-cash baseline against whatever's picked in
            "Compare against" above, so you always get a like-for-like comparison.
          </label>
          <input
            type="text"
            value={strategyName}
            onChange={(e) => setStrategyName(e.target.value)}
            placeholder="e.g. tighter-stop-test"
            style={inputStyle}
          />

          <div style={{ display: "flex", gap: 10 }}>
            {/* Also disabled while the base config is still loading -- submitting
                before that async pre-fill resolves would send blank fields for
                everything, which used to mean "null out ma_period etc." and
                crash run_backtest.py; fixed at the source (coerceField above),
                but this closes the race that could trigger it in the first place. */}
            <button type="submit" disabled={submitting || loadingBase} style={{ ...submitButtonStyle, width: "auto", flex: 1 }}>
              {submitting ? "Submitting…" : loadingBase ? "Loading base config…" : "Run backtest"}
            </button>
            <button
              type="button"
              onClick={handleExport}
              disabled={exporting || loadingBase}
              style={{ ...submitButtonStyle, width: "auto", flex: 1, background: "var(--surface-raised)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
            >
              {exporting ? "Exporting…" : "Export config (.yaml)"}
            </button>
          </div>

          {submitting && (
            <div style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 12 }}>
              Running both backtests now — usually done within a few tens of seconds.
            </div>
          )}
          {error && (
            <div style={{ color: "var(--negative)", fontSize: 13, marginTop: 12 }}>Failed: {error}</div>
          )}
        </form>
      </Panel>

      <div style={{ marginTop: 12 }}>
        <Panel title={results ? `Results vs. ${results.compareName}` : "Results"}>
          {!results ? (
            <Empty text='Run a backtest above to compare it against another config over the same window (defaults to master, changeable in "Compare against").' />
          ) : (
            <Table
              headers={["Run", "Watchlist", "Window", ...METRIC_COLS.map((c) => METRIC_LABELS[c]), "Report"]}
              rows={[
                { ...results.custom, displayLabel: results.custom.run_label },
                { ...results.compare, displayLabel: `${results.compare.run_label} (${results.compareName})` },
              ].map((r) => [
                r.displayLabel,
                (r.watchlist || []).join(", "),
                `${r.start_date} → ${r.end_date}`,
                ...METRIC_COLS.map((c) => {
                  const v = r.metrics?.[c];
                  if (v == null) return "—";
                  return c.includes("pct") // covers total_return_pct, max_drawdown_pct, alpha_pct
                    ? <span style={{ color: pnlColor(v) }}>{fmtPct(v)}</span>
                    : typeof v === "number" ? v.toFixed(2) : v;
                }),
                r.report_url ? (
                  <a href={r.report_url} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>View</a>
                ) : (
                  <span style={{ color: "var(--text-faint)" }}>—</span>
                ),
              ])}
            />
          )}
        </Panel>
      </div>
    </div>
  );
}

function visibleFields(fields, values) {
  return fields.filter((f) => !f.showIf || f.showIf(values));
}

function FieldGrid({ fields, values, onChange }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "14px 16px" }}>
      {visibleFields(fields, values).map((f) => (
        <div key={f.key}>
          <label style={labelStyle}>
            {f.label}
            {!f.nullable && <span style={{ color: "var(--negative)" }}> *</span>}
          </label>
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
