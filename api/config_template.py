"""
Vercel Python serverless function -- returns a strategy config's real,
current YAML text with a short, plain-English comment injected above
each tunable field explaining what it controls and what shifting it
conceptually means. Powers the Backtest page's single config editor:
load this once, edit values directly in the text, run it.

Explanations are adapted from the same field descriptions this project
already wrote for the (now-retired) 26-field form UI -- proven,
already-accurate prose, not reinvented here. Deliberately a SHORTER,
different comment layer than the real config file's own comments
(which are promotion-history narrative, valuable but long) -- this
endpoint's injected comments never touch or duplicate those; both are
visible in the returned text, the real ones because they're already in
the file, these because they're inserted fresh on top.

GET /api/config_template?path=config/strategy_master.yaml   (path optional, defaults to the live config)
-> {"configYaml": "...annotated text..."}

No auth -- same reasoning as api/report.js/quotes.js: this only reads
already-public config text out of the repo, nothing sensitive passes
through.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re
from urllib.parse import urlparse, parse_qs

DEFAULT_CONFIG_PATH = "config/strategy_master.yaml"

# dotted.path -> one-line explanation. Kept in sync BY HAND with
# dashboard/src/components/BacktestPage.jsx's old FIELD_GROUPS `help`
# text where this was lifted from (shortened to fit one line) -- same
# "duplicated, keep in sync" convention api/run_backtest.py's
# FIELD_PATHS already uses relative to that same file.
ANNOTATIONS = {
    "watchlist": "Tickers the strategy is allowed to trade.",
    "backtest.start_date": "First day of the simulated period.",
    "backtest.end_date": "Last day of the simulated period.",
    "backtest.starting_cash": "Simulated account balance on day one.",
    "backtest.commission_pct": "Flat % cost deducted on both entry and exit -- 0 means frictionless trading, unrealistic at high trade frequency.",
    "entry.ma_period": "Moving-average length for the entry signal -- shorter reacts faster but whipsaws more; longer is slower but steadier.",
    "entry.breakout_period": "Lookback window (days) for a Donchian-breakout entry's N-day high.",
    "entry.volume_confirmation": "If true, an entry also requires that day's volume above its own moving average.",
    "entry.volume_ma_period": "Moving-average length for the volume-confirmation check above.",
    "entry.regime_filter_period": "A much slower MA the fast entry signal must also be above (a macro trend filter). Tested and found to HURT this strategy's own live track -- present for reference, not recommended to enable.",
    "entry.choppiness_threshold": "Blocks entries when the choppiness index reads above this (market judged to be ranging, not trending). Unset = filter off.",
    "entry.choppiness_filter_period": "Lookback window for the choppiness index above.",
    "exit.ma_exit": "Master on/off switch for the trend-exit rule below -- false means only the stop-loss/take-profit can ever close a position.",
    "exit.type": "ma_crossover exits the first day price closes back below its MA; donchian_low exits the first day price closes below its N-day low (more tolerant of pullbacks).",
    "exit.exit_breakout_period": "Lookback window (days) for the donchian_low trend-exit rule's N-day low -- shorter exits faster (locks in gains sooner, also stops out sooner); longer rides trends longer.",
    "exit.stop_loss_pct": "Flat-percent stop-loss below entry. Only used when risk.sizing_method is 'pct' -- atr_unit mode uses stop_atr_multiple x ATR instead.",
    "exit.take_profit_pct": "Flat-percent take-profit above entry. Unset means only stops and the trend-exit rule can ever close a winner -- no profit gets locked in early.",
    "risk.sizing_method": "'pct' sizes every position the same % of equity. 'atr_unit' (Turtle-style) sizes by volatility -- calmer tickers get bigger positions for the same dollar risk -- and is required for pyramiding.",
    "risk.atr_period": "Lookback window (days) for ATR ('N'), the volatility measure atr_unit sizing and the trailing stop are built on.",
    "risk.risk_pct_per_unit": "% of equity risked on one unit (atr_unit sizing only) -- position size = (this % of equity) / (stop distance in $). Higher = bigger positions, more risk per trade.",
    "risk.stop_atr_multiple": "Stop-loss distance from entry, in multiples of ATR/N (atr_unit sizing only). Tighter = smaller losses per trade but more whipsaw stop-outs; wider = fewer whipsaws but bigger losses when wrong.",
    "risk.max_position_pct": "Hard cap on any single ticker's position size, regardless of what the sizing formula would otherwise produce.",
    "risk.max_invested_pct": "Hard cap on total capital deployed across all open positions at once -- the rest stays cash.",
    "risk.pyramiding.enabled": "Allows adding more units to an already-open, winning position as price moves further in its favor. Requires atr_unit sizing.",
    "risk.pyramiding.unit_interval_n": "Price must move this many multiples of ATR/N further in the position's favor (since the LAST unit's own entry) before another unit is added.",
    "risk.pyramiding.max_units": "Ceiling on how many units one position can stack up to.",
    "risk.trailing_stop.enabled": "Adds a second stop that trails up behind the position's peak price (never down), on top of the regular stop -- whichever is tighter wins.",
    "risk.trailing_stop.atr_multiple": "How far behind the peak price the trailing stop sits, in multiples of ATR/N. Tighter locks in more profit but exits winners sooner; wider rides trends further but gives back more of the peak.",
    "risk.correlation_breaker.enabled": "Blocks a NEW entry if it would push the count of already-open, mutually-correlated positions past max_correlated_positions. Never force-closes an existing position.",
    "risk.correlation_breaker.lookback_period": "Trading days of returns used to measure correlation between two tickers.",
    "risk.correlation_breaker.correlation_threshold": "Pearson correlation at/above this counts two positions as 'correlated' for the breaker above.",
    "risk.correlation_breaker.max_correlated_positions": "How many already-open correlated positions are allowed before a new one in that same group gets blocked.",
}


def _annotate(raw_text: str) -> str:
    """
    Walks the raw YAML text line by line, tracking dotted key paths via
    indentation, and inserts a `# ...` comment line (matching that
    line's own indentation) immediately above any `key: value` line
    whose full dotted path is in ANNOTATIONS.

    The real config's OWN comments (promotion-history narrative, e.g.
    strategy_master.yaml's multi-hundred-line header) are deliberately
    dropped here, not preserved alongside the new ones -- that history
    is real and stays fully intact in the actual git-tracked file, but
    showing all of it in an editor meant to be simple would defeat the
    point. Only real key/value and list-item lines pass through
    unchanged; every original `#`-comment line is filtered out first.
    Values themselves are never touched -- this only adds/removes
    comment lines, nothing about the config's real data changes.
    """
    key_line = re.compile(r"^(\s*)([A-Za-z0-9_]+):(\s.*|)$")
    stack = []  # list of (indent, key)
    out_lines = []

    for line in raw_text.splitlines():
        if line.strip().startswith("#"):
            continue  # drop the file's own existing comments

        match = key_line.match(line)
        if match:
            indent = len(match.group(1))
            key = match.group(2)
            stack = [(i, k) for i, k in stack if i < indent]
            dotted = ".".join([k for _, k in stack] + [key])
            note = ANNOTATIONS.get(dotted)
            if note:
                out_lines.append(f"{match.group(1)}# {note}")
            stack.append((indent, key))
        out_lines.append(line)

    # Collapse runs of 2+ blank lines (left behind where a whole
    # multi-line comment block was dropped) down to a single blank line.
    text = "\n".join(out_lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        raw_path = (query.get("path") or [DEFAULT_CONFIG_PATH])[0]
        config_path = os.path.normpath(raw_path)

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_path = os.path.join(repo_root, config_path)
        # Same repo-confinement guard as api/run_backtest.py's build_config.
        if not os.path.abspath(full_path).startswith(repo_root) or not os.path.isfile(full_path):
            return self._send_json(400, {"error": f"Config not found: {config_path}"})

        with open(full_path) as f:
            raw_text = f.read()

        try:
            self._send_json(200, {"configYaml": _annotate(raw_text), "path": config_path})
        except Exception as e:
            self._send_json(500, {"error": str(e)})
