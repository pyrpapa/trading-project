// Vercel serverless function -- merges a base strategy config with the
// dashboard Backtest page's curated form fields and an optional
// advanced-YAML snippet, then dispatches run-backtest.yml (GitHub
// Actions) to actually run it. Same "keep the credential server-side,
// gate behind a real session" shape as api/sell.js -- a backtest is
// read-only against the market (never touches Alpaca), but it does
// spend real GitHub Actions time and writes to Supabase, so it's still
// gated behind login rather than left open.
//
// Fetches the base config from GitHub's raw content API at request time
// rather than bundling a copy in this repo's dashboard/ subtree --
// avoids a second copy of config/*.yaml silently drifting from the real
// one. Public repo, no auth needed for that read.
//
// Needs the SAME two credential sets as api/sell.js (VITE_SUPABASE_URL/
// ANON_KEY for session verification, GITHUB_DISPATCH_TOKEN for the
// workflow_dispatch call) -- already configured on Vercel if the Sell
// button is working; nothing new to add there.
//
// POST /api/backtest
// {
//   baseConfig: "config/strategy_master.yaml",
//   formFields: { watchlist: ["SPXL","ERX"], start_date: "2019-01-01", ... },
//   advancedYaml: "risk:\n  pyramiding:\n    enabled: false\n",  // optional
//   runLabel: "my-test-run"
// }

import { createClient } from "@supabase/supabase-js";
import { load as yamlLoad, dump as yamlDump } from "js-yaml";

const REPO = "pyrpapa/trading-project";

// Curated form field -> dotted YAML path. Mirrors BacktestPage.jsx's
// FIELD_GROUPS `path` values exactly -- keep the two in sync. Anything
// not in this list can still be set via the advancedYaml override.
const FIELD_PATHS = {
  watchlist: "watchlist",
  start_date: "backtest.start_date",
  end_date: "backtest.end_date",
  starting_cash: "backtest.starting_cash",
  entry_type: "entry.type",
  ma_period: "entry.ma_period",
  breakout_period: "entry.breakout_period",
  volume_confirmation: "entry.volume_confirmation",
  volume_ma_period: "entry.volume_ma_period",
  regime_filter_period: "entry.regime_filter_period",
  choppiness_filter_period: "entry.choppiness_filter_period",
  choppiness_threshold: "entry.choppiness_threshold",
  exit_type: "exit.type",
  ma_exit: "exit.ma_exit",
  exit_breakout_period: "exit.exit_breakout_period",
  stop_loss_pct: "exit.stop_loss_pct",
  take_profit_pct: "exit.take_profit_pct",
  sizing_method: "risk.sizing_method",
  atr_period: "risk.atr_period",
  risk_pct_per_unit: "risk.risk_pct_per_unit",
  stop_atr_multiple: "risk.stop_atr_multiple",
  max_position_pct: "risk.max_position_pct",
  max_invested_pct: "risk.max_invested_pct",
  pyramiding_enabled: "risk.pyramiding.enabled",
  pyramiding_unit_interval_n: "risk.pyramiding.unit_interval_n",
  pyramiding_max_units: "risk.pyramiding.max_units",
  trailing_stop_enabled: "risk.trailing_stop.enabled",
  trailing_stop_atr_multiple: "risk.trailing_stop.atr_multiple",
};

function setPath(obj, dottedPath, value) {
  const parts = dottedPath.split(".");
  let node = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    if (typeof node[parts[i]] !== "object" || node[parts[i]] === null) node[parts[i]] = {};
    node = node[parts[i]];
  }
  node[parts[parts.length - 1]] = value;
}

// Plain-object recursive merge (arrays and scalars are replaced
// wholesale, not concatenated) -- lets a short advancedYaml snippet like
// `risk:\n  pyramiding:\n    enabled: false` override just that one key
// without needing to repeat the rest of risk.*.
function deepMerge(base, override) {
  if (typeof override !== "object" || override === null || Array.isArray(override)) return override;
  const result = { ...base };
  for (const [key, value] of Object.entries(override)) {
    result[key] = typeof base?.[key] === "object" && base[key] !== null && !Array.isArray(base[key])
      ? deepMerge(base[key], value)
      : value;
  }
  return result;
}

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "POST only" });
  }

  const { baseConfig, formFields, advancedYaml, runLabel, exportOnly } = req.body || {};
  if (!baseConfig) {
    return res.status(400).json({ error: "baseConfig required, e.g. config/strategy_master.yaml" });
  }

  const authHeader = req.headers.authorization || "";
  const accessToken = authHeader.replace(/^Bearer\s+/i, "");
  if (!accessToken) {
    return res.status(401).json({ error: "Missing Authorization header -- not logged in?" });
  }

  const supabaseUrl = process.env.VITE_SUPABASE_URL;
  const supabaseAnonKey = process.env.VITE_SUPABASE_ANON_KEY;
  if (!supabaseUrl || !supabaseAnonKey) {
    return res.status(500).json({ error: "Supabase env vars not configured on the server" });
  }
  const supabase = createClient(supabaseUrl, supabaseAnonKey);
  const { data: userData, error: userError } = await supabase.auth.getUser(accessToken);
  if (userError || !userData?.user) {
    return res.status(401).json({ error: "Invalid or expired session -- log in again and retry" });
  }

  // exportOnly skips this -- it never dispatches anything, just returns
  // the merged YAML, so it doesn't need a GitHub token at all.
  const dispatchToken = process.env.GITHUB_DISPATCH_TOKEN;
  if (!exportOnly && !dispatchToken) {
    return res.status(500).json({ error: "GITHUB_DISPATCH_TOKEN not configured on the server" });
  }

  let cfg;
  try {
    const rawResp = await fetch(`https://raw.githubusercontent.com/${REPO}/main/${baseConfig}`);
    if (!rawResp.ok) throw new Error(`couldn't fetch ${baseConfig} (${rawResp.status}) -- check the path`);
    cfg = yamlLoad(await rawResp.text());
    if (typeof cfg !== "object" || cfg === null || Array.isArray(cfg)) {
      throw new Error(`${baseConfig} didn't parse into a config object -- is the path right?`);
    }
  } catch (e) {
    return res.status(400).json({ error: String(e.message || e) });
  }

  for (const [field, value] of Object.entries(formFields || {})) {
    // The dashboard form pre-fills from this same base config and always
    // sends every field, so `null` here is a deliberate value (a
    // nullable field like take_profit_pct left blank), NOT "untouched" --
    // only a genuinely absent key (not in formFields at all) means that.
    if (value === undefined) continue;
    if (!(field in FIELD_PATHS)) continue; // ignore anything not in the curated set
    setPath(cfg, FIELD_PATHS[field], value);
  }

  if (advancedYaml && advancedYaml.trim()) {
    let override;
    try {
      override = yamlLoad(advancedYaml);
    } catch (e) {
      return res.status(400).json({ error: `Advanced YAML didn't parse: ${e.message || e}` });
    }
    // Must itself be a mapping (e.g. `risk:\n  ...`) -- a scalar or list
    // here would otherwise replace the ENTIRE merged config (see
    // deepMerge's non-object branch), silently discarding everything
    // the base config + form fields already built.
    if (typeof override !== "object" || override === null || Array.isArray(override)) {
      return res.status(400).json({ error: "Advanced YAML must be a mapping (e.g. `risk:\n  stop_atr_multiple: 2.0`), not a bare value or list" });
    }
    cfg = deepMerge(cfg, override);
  }

  const configYaml = yamlDump(cfg);

  if (exportOnly) {
    return res.status(200).json({ ok: true, configYaml });
  }

  try {
    const resp = await fetch(
      `https://api.github.com/repos/${REPO}/actions/workflows/run-backtest.yml/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${dispatchToken}`,
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ref: "main",
          inputs: { config_yaml: configYaml, run_label: runLabel || "" },
        }),
      }
    );

    if (resp.status !== 204) {
      const text = await resp.text();
      return res.status(resp.status).json({ error: `GitHub API error (${resp.status}): ${text}` });
    }

    return res.status(200).json({ ok: true, configYaml });
  } catch (e) {
    return res.status(500).json({ error: String(e) });
  }
}
