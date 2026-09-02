"""
Vercel Python serverless function -- the Backtest page's "Run backtest"
button posts here directly instead of dispatching a GitHub Actions
workflow. Runs synchronously and returns metrics in the response, since
this project's backtests consistently finish in well under a minute
(confirmed against real usage before building this) -- comfortably
inside even Vercel Hobby's 300s default function timeout, no
async/poll-for-results dance needed.

This ONLY works because this Vercel project's Root Directory is the
REPO ROOT (not dashboard/, where the rest of the dashboard's API
functions used to assume) -- that's what lets this file import the
real strategy/backtest/data/storage modules directly, the exact same
code every other backtest in this project (CLI, GitHub Actions) already
uses. No reimplementation, so a dashboard-triggered run and a
command-line run of the identical config can never silently diverge.
See vercel.json at the repo root for the build config that makes the
dashboard/ frontend still build correctly under this root.

POST /api/run_backtest
Header: Authorization: Bearer <supabase access_token>
{
  "custom":  {"baseConfig": "...", "formFields": {...}, "advancedYaml": "...", "runLabel": "..."},
  "compare": {"baseConfig": "...", "formFields": {...}, "runLabel": "..."},   # omit to skip
  "exportOnly": false   # true: return configYaml for each, run nothing
}
->
{
  "ok": true,
  "custom":  {"run_label": "...", "metrics": {...}, "report_url": "..." | null},
  "compare": {"run_label": "...", "metrics": {...}, "report_url": "..." | null},
}
(exportOnly response shape: {"ok": true, "custom": {"configYaml": "..."}, "compare": {...}})
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root

import yaml

from run_backtest import run_backtest_for_config, NoDataError
from data import fetcher

# Vercel's deployed source tree is read-only at runtime -- only /tmp is
# writable. data/fetcher.py's on-disk cache and run_backtest_for_config's
# chart-report output both default to relative paths under the (read-
# only) repo tree, so both get redirected into /tmp here. This is an
# override from the CALLER, not a change to fetcher.py/run_backtest.py
# themselves -- those stay environment-agnostic; every other caller
# (CLI, GitHub Actions) still gets their normal on-repo paths.
fetcher.CACHE_DIR = "/tmp/data-cache"
REPORT_DIR = "/tmp/results"

# Mirrors BacktestPage.jsx's FIELD_GROUPS `path` values exactly -- keep
# the two in sync if a field is added/renamed there. The frontend only
# ever sends keys it actually wants set (a blank-but-required field is
# simply omitted, not sent as null -- see BacktestPage.jsx's
# coerceField), so every key present here gets applied unconditionally,
# no "skip if empty" logic needed on this side.
FIELD_PATHS = {
    "watchlist": "watchlist",
    "start_date": "backtest.start_date",
    "end_date": "backtest.end_date",
    "starting_cash": "backtest.starting_cash",
    "entry_type": "entry.type",
    "ma_period": "entry.ma_period",
    "breakout_period": "entry.breakout_period",
    "volume_confirmation": "entry.volume_confirmation",
    "volume_ma_period": "entry.volume_ma_period",
    "regime_filter_period": "entry.regime_filter_period",
    "choppiness_filter_period": "entry.choppiness_filter_period",
    "choppiness_threshold": "entry.choppiness_threshold",
    "exit_type": "exit.type",
    "ma_exit": "exit.ma_exit",
    "exit_breakout_period": "exit.exit_breakout_period",
    "stop_loss_pct": "exit.stop_loss_pct",
    "take_profit_pct": "exit.take_profit_pct",
    "sizing_method": "risk.sizing_method",
    "atr_period": "risk.atr_period",
    "risk_pct_per_unit": "risk.risk_pct_per_unit",
    "stop_atr_multiple": "risk.stop_atr_multiple",
    "max_position_pct": "risk.max_position_pct",
    "max_invested_pct": "risk.max_invested_pct",
    "pyramiding_enabled": "risk.pyramiding.enabled",
    "pyramiding_unit_interval_n": "risk.pyramiding.unit_interval_n",
    "pyramiding_max_units": "risk.pyramiding.max_units",
    "trailing_stop_enabled": "risk.trailing_stop.enabled",
    "trailing_stop_atr_multiple": "risk.trailing_stop.atr_multiple",
}


def set_path(obj, dotted_path, value):
    parts = dotted_path.split(".")
    node = obj
    for p in parts[:-1]:
        if not isinstance(node.get(p), dict):
            node[p] = {}
        node = node[p]
    node[parts[-1]] = value


def deep_merge(base, override):
    """Same shape as BacktestPage.jsx's old JS deepMerge: a mapping merges
    key-by-key (recursively); anything else replaces wholesale."""
    if not isinstance(override, dict):
        return override
    result = dict(base)
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def build_config(base_config_path, form_fields, advanced_yaml):
    base_config_path = os.path.normpath(base_config_path)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_path = os.path.join(repo_root, base_config_path)
    # Guards against a path that escapes the repo (e.g. "../../etc/passwd")
    # -- this endpoint reads whatever file it's given, so it must stay
    # confined to the repo tree.
    if not os.path.abspath(full_path).startswith(repo_root) or not os.path.isfile(full_path):
        raise ValueError(f"Config not found: {base_config_path}")

    with open(full_path) as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError(f"{base_config_path} didn't parse into a config object -- is the path right?")

    for field, value in (form_fields or {}).items():
        path = FIELD_PATHS.get(field)
        if not path:
            continue
        set_path(cfg, path, value)

    if advanced_yaml and advanced_yaml.strip():
        override = yaml.safe_load(advanced_yaml)
        if not isinstance(override, dict):
            raise ValueError("Advanced YAML must be a mapping (e.g. `risk:\n  stop_atr_multiple: 2.0`), not a bare value or list")
        cfg = deep_merge(cfg, override)

    return cfg


def verify_session(token):
    """Raises on an invalid/expired session. Uses the anon key + the
    caller's own access token (never the service key) purely to validate
    who's asking -- same pattern the old api/sell.js used."""
    from supabase import create_client
    url = os.environ.get("VITE_SUPABASE_URL")
    anon_key = os.environ.get("VITE_SUPABASE_ANON_KEY")
    if not url or not anon_key:
        raise RuntimeError("VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY not configured on the server")
    client = create_client(url, anon_key)
    resp = client.auth.get_user(token)
    if not resp or not getattr(resp, "user", None):
        raise PermissionError("Invalid or expired session -- log in again and retry")


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length)) if length else {}
        except Exception as e:
            return self._send_json(400, {"error": f"Invalid JSON body: {e}"})

        auth_header = self.headers.get("Authorization", "")
        token = auth_header[7:] if auth_header.lower().startswith("bearer ") else ""
        if not token:
            return self._send_json(401, {"error": "Missing Authorization header -- not logged in?"})
        try:
            verify_session(token)
        except PermissionError as e:
            return self._send_json(401, {"error": str(e)})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

        export_only = bool(payload.get("exportOnly"))

        def run_one(spec):
            cfg = build_config(spec.get("baseConfig"), spec.get("formFields") or {}, spec.get("advancedYaml") or "")
            if export_only:
                return {"configYaml": yaml.dump(cfg)}
            run_label = spec.get("runLabel") or None
            result = run_backtest_for_config(
                cfg,
                run_label=run_label,
                save_to_supabase=True,
                make_chart=True,
                label_hint=run_label or "custom",
                verbose=False,
                report_dir=REPORT_DIR,
            )
            return {
                "run_label": run_label,
                "watchlist": cfg.get("watchlist"),
                "start_date": cfg["backtest"]["start_date"],
                "end_date": cfg["backtest"]["end_date"],
                "metrics": result["metrics"],
                "report_url": result.get("report_url"),
            }

        response = {"ok": True}
        try:
            if "custom" in payload:
                response["custom"] = run_one(payload["custom"])
            if "compare" in payload:
                response["compare"] = run_one(payload["compare"])
        except NoDataError as e:
            return self._send_json(400, {"error": str(e)})
        except (ValueError, FileNotFoundError) as e:
            return self._send_json(400, {"error": str(e)})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

        self._send_json(200, response)
