import { useState, useEffect, useCallback } from "react";
import { load as yamlLoad } from "js-yaml";
import { supabase } from "../lib/supabaseClient.js";
import { Panel, Table, Empty, fmtPct, pnlColor } from "./PositionsTable.jsx";

const METRIC_COLS = ["total_return_pct", "max_drawdown_pct", "calmar_ratio", "sortino_ratio", "alpha_pct", "n_trades"];
const METRIC_LABELS = {
  total_return_pct: "Return", max_drawdown_pct: "Max DD", calmar_ratio: "Calmar",
  sortino_ratio: "Sortino", alpha_pct: "Alpha", n_trades: "Trades",
};

// Shared by both the live "Results" table and the "Saved backtests"
// table below it -- same row shape either way (watchlist, window, the
// metric columns, a report link/status), just the Run-label and
// Save-button cells differ per caller.
function metricRowCells(r) {
  return [
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
      // Through api/report.js, not r.report_url (Supabase's own public
      // URL) directly -- linking straight to Storage rendered the report
      // as raw HTML source text instead of a page, because the object
      // wasn't reliably served with a text/html content-type. The proxy
      // re-serves the same content with that header set explicitly.
      <a href={`/api/report?label=${encodeURIComponent(r.run_label)}`} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>View</a>
    ) : r.report_error ? (
      <span style={{ color: "var(--negative)", cursor: "help" }} title={r.report_error}>failed *</span>
    ) : (
      <span style={{ color: "var(--text-faint)" }}>—</span>
    ),
  ];
}

// Explicit save, not auto-persisted history: every run already lands in
// Supabase's backtest_runs table regardless (save_to_supabase=True in
// api/run_backtest.py) -- that's the real, durable storage. What's
// local here is just the small LIST of run_labels you've chosen to
// keep around, in this browser's localStorage. Clicking "Save" adds a
// label to this list and the row gets re-fetched from Supabase (by
// run_label, never a broad history query) on every future page load,
// however many runs happen in between. Wrapped in try/catch
// throughout: private browsing/disabled site data degrades to "saving
// doesn't persist," never breaks the page.
const SAVED_LABELS_KEY = "backtestPage.savedLabels";

function loadSavedLabels() {
  try {
    const raw = localStorage.getItem(SAVED_LABELS_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function persistSavedLabels(labels) {
  try {
    localStorage.setItem(SAVED_LABELS_KEY, JSON.stringify(labels));
  } catch {
    // Nothing to do -- storage just isn't available this session.
  }
}

export default function BacktestPage() {
  // The whole editor: the live strategy's real YAML, with a concise
  // plain-English comment injected above each tunable field (see
  // api/config_template.py) -- this replaces the old 26-field form,
  // ticker chip-picker, and separate base/compare-config dropdowns
  // entirely. Whatever's in here is exactly what gets run.
  const [configText, setConfigText] = useState("");
  const [loadingTemplate, setLoadingTemplate] = useState(true);
  const [templateError, setTemplateError] = useState(null);

  // Names both the Supabase run_label AND the exported file -- one
  // field doing double duty rather than two names to keep in sync.
  const [strategyName, setStrategyName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  // api/run_backtest.py runs synchronously and returns metrics directly
  // -- no dispatch-and-poll dance, so this is just the last response,
  // not a running history. { custom: {run_label, metrics, report_url},
  // compare: {...} } | null. Overwritten (not appended to) on every new
  // submit, and NOT persisted across a reload -- this is deliberately
  // ephemeral ("what I just ran"); explicitly clicking Save on a row is
  // what makes something stick around (see savedLabels/savedRuns below).
  const [results, setResults] = useState(null);
  // The small local list of run_labels you've marked to keep, and the
  // actual rows fetched from Supabase for them (by label, not a broad
  // history query -- see the SAVED_LABELS_KEY comment above).
  const [savedLabels, setSavedLabels] = useState(loadSavedLabels);
  const [savedRuns, setSavedRuns] = useState([]);
  const [loadingSaved, setLoadingSaved] = useState(false);

  // Fetches the annotated live-config text from api/config_template.py
  // -- a plain GET, no auth (same reasoning as api/report.js/quotes.js:
  // this only reads already-public config text, nothing sensitive).
  const loadTemplate = useCallback(async () => {
    setLoadingTemplate(true);
    setTemplateError(null);
    try {
      const resp = await fetch("/api/config_template");
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);
      setConfigText(body.configYaml);
    } catch (e) {
      setTemplateError(String(e.message || e));
    } finally {
      setLoadingTemplate(false);
    }
  }, []);

  useEffect(() => {
    loadTemplate();
  }, [loadTemplate]);

  // Re-fetches every time savedLabels changes (on mount, and after every
  // save/unsave) -- targeted at exactly those labels, never a broad
  // "recent runs" query, so this stays cheap and small regardless of how
  // many total backtests have ever been run.
  useEffect(() => {
    if (savedLabels.length === 0) {
      setSavedRuns([]);
      return;
    }
    let cancelled = false;
    setLoadingSaved(true);
    supabase
      .from("backtest_runs")
      .select("*")
      .in("run_label", savedLabels)
      .order("created_at", { ascending: false })
      .then(({ data }) => {
        if (!cancelled) setSavedRuns(data ?? []);
      })
      .finally(() => {
        if (!cancelled) setLoadingSaved(false);
      });
    return () => { cancelled = true; };
  }, [savedLabels]);

  function toggleSave(runLabel) {
    if (!runLabel) return;
    setSavedLabels((prev) => {
      const next = prev.includes(runLabel) ? prev.filter((l) => l !== runLabel) : [...prev, runLabel];
      persistSavedLabels(next);
      return next;
    });
  }

  // Permanently deletes the run from Supabase (backtest_runs + its
  // trades, cascaded -- see migration 005) -- distinct from toggleSave's
  // "unsave," which only removes it from this browser's local list
  // without touching the underlying data. Confirmed with a plain native
  // confirm() rather than the app's usual inline-confirm pattern (used
  // for the Sell button): this is backtest metadata, not a real trade,
  // materially lower stakes.
  async function handleDelete(runLabel) {
    if (!runLabel) return;
    if (!window.confirm(`Permanently delete "${runLabel}" from Supabase? This can't be undone.`)) return;
    const { error: deleteError } = await supabase.from("backtest_runs").delete().eq("run_label", runLabel);
    if (deleteError) {
      setError(`Couldn't delete "${runLabel}": ${deleteError.message}`);
      return;
    }
    setSavedRuns((prev) => prev.filter((r) => r.run_label !== runLabel));
    setSavedLabels((prev) => {
      const next = prev.filter((l) => l !== runLabel);
      persistSavedLabels(next);
      return next;
    });
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

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);

    // Client-side parse check first -- a clear inline error beats a
    // cryptic 500 from the server for something as easy to catch here
    // as broken YAML syntax.
    try {
      const parsed = yamlLoad(configText);
      if (typeof parsed !== "object" || parsed === null) {
        throw new Error("Must be a YAML mapping (e.g. `watchlist:\n  - SPXL`), not a bare value or list.");
      }
    } catch (e) {
      setError(`Config isn't valid YAML: ${e.message || e}`);
      return;
    }

    setSubmitting(true);
    setResults(null);
    try {
      const label = strategyName || `custom-${Date.now()}`;
      const { data: { session } } = await supabase.auth.getSession();
      const resp = await fetch("/api/run_backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${session?.access_token}` },
        body: JSON.stringify({ rawConfigYaml: configText, runLabel: label }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);
      setResults({ custom: body.custom, compare: body.compare });
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setSubmitting(false);
    }
  }

  function handleExport() {
    const label = strategyName || "custom-strategy";
    downloadYaml(configText, `${label.replace(/[^a-z0-9_-]+/gi, "-")}.yaml`);
  }

  return (
    <div style={{ padding: "20px 24px 24px 24px" }}>
      <Panel
        title="Strategy editor"
        action={
          <button type="button" onClick={loadTemplate} disabled={loadingTemplate} style={refreshButtonStyle}>
            {loadingTemplate ? "Loading…" : "Reset to current live strategy"}
          </button>
        }
      >
        <div style={{ color: "var(--text-faint)", fontSize: 11, marginBottom: 10 }}>
          This is the actual live strategy — every value below is real, and every commented line above a value
          explains what it controls and what raising or lowering it would conceptually mean. Edit whatever you
          want to try, then run it. Every run is automatically compared against the unmodified live strategy over
          the same window, so you always see whether your change actually helped.
        </div>

        <form onSubmit={handleSubmit}>
          {templateError && (
            <div style={{ color: "var(--negative)", fontSize: 13, marginBottom: 10 }}>
              Couldn't load the live strategy: {templateError}
            </div>
          )}
          <textarea
            value={configText}
            onChange={(e) => setConfigText(e.target.value)}
            spellCheck={false}
            rows={32}
            style={{ ...inputStyle, fontFamily: "var(--font-mono)", fontSize: 12, resize: "vertical", whiteSpace: "pre" }}
          />

          <label style={{ ...labelStyle, marginTop: 16 }}>
            Strategy name — labels this run below and names the file if you export
          </label>
          <input
            type="text"
            value={strategyName}
            onChange={(e) => setStrategyName(e.target.value)}
            placeholder="e.g. tighter-stop-test"
            style={inputStyle}
          />

          <div style={{ display: "flex", gap: 10 }}>
            <button type="submit" disabled={submitting || loadingTemplate} style={{ ...submitButtonStyle, width: "auto", flex: 1 }}>
              {submitting ? "Running…" : "Run backtest"}
            </button>
            <button
              type="button"
              onClick={handleExport}
              style={{ ...submitButtonStyle, width: "auto", flex: 1, background: "var(--surface-raised)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
            >
              Export config (.yaml)
            </button>
          </div>

          {submitting && (
            <div style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 12 }}>
              Running your version and the live strategy now — usually done within a few tens of seconds.
            </div>
          )}
          {error && (
            <div style={{ color: "var(--negative)", fontSize: 13, marginTop: 12 }}>Failed: {error}</div>
          )}
        </form>
      </Panel>

      <div style={{ marginTop: 12 }}>
        <Panel
          title={results ? "Results vs. live strategy" : "Results"}
          action={results && <button onClick={() => setResults(null)} style={refreshButtonStyle}>Clear</button>}
        >
          {!results ? (
            <Empty text="Run a backtest above to compare it against the current live strategy over the same window. Nothing here survives a reload unless you Save it below." />
          ) : (
            <Table
              headers={["Run", "Watchlist", "Window", ...METRIC_COLS.map((c) => METRIC_LABELS[c]), "Report", "Save"]}
              rows={[
                { ...results.custom, displayLabel: results.custom.run_label },
                { ...results.compare, displayLabel: `${results.compare.run_label} (live)` },
              ].map((r) => [
                r.displayLabel,
                ...metricRowCells(r),
                <button onClick={() => toggleSave(r.run_label)} style={refreshButtonStyle}>
                  {savedLabels.includes(r.run_label) ? "★ Saved" : "☆ Save"}
                </button>,
              ])}
            />
          )}
        </Panel>
      </div>

      <div style={{ marginTop: 12 }}>
        <Panel
          title="Saved backtests"
          action={loadingSaved && <span style={{ color: "var(--text-faint)", fontSize: 11 }}>Loading…</span>}
        >
          {savedRuns.length === 0 ? (
            <Empty text='Click "☆ Save" on a result above to keep it here — survives reloads, stays a short list you curate yourself, not a running history of every run.' />
          ) : (
            <Table
              headers={["Run", "Watchlist", "Window", ...METRIC_COLS.map((c) => METRIC_LABELS[c]), "Report", ""]}
              rows={savedRuns.map((r) => [
                r.run_label || `#${r.id}`,
                ...metricRowCells(r),
                <span style={{ display: "flex", gap: 6 }}>
                  <button onClick={() => toggleSave(r.run_label)} style={refreshButtonStyle}>Unsave</button>
                  <button onClick={() => handleDelete(r.run_label)} style={{ ...refreshButtonStyle, borderColor: "var(--negative)", color: "var(--negative)" }}>Delete</button>
                </span>,
              ])}
            />
          )}
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
