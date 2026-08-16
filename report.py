"""
Builds a self-contained HTML backtest report: stat tiles, equity curve +
drawdown, monthly returns (Donchian-trend-style win/loss bars, like
Way of the Turtle's own performance charts), an R-multiple distribution,
and per-ticker price charts with buy/sell markers pulled straight from
the trade journal.

Not wired into run_backtest.py's Supabase save path — this works
entirely from the in-memory backtest result, so it's fast to regenerate
while you're experimenting with a config. Usage:

    python run_backtest.py --chart
    python run_backtest.py --config config/strategy_v5_n_sizing.yaml --chart --label "v5-n-sizing"

Colors and mark specs follow the project's dataviz palette (see the
`dataviz` skill's references/palette.md if you're editing this file) —
categorical slot 1 (blue) for gains/entries, slot 8 (red) for
losses/exits, so the same color means the same thing in every chart.
"""
import base64
import io
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np

from strategy.portfolio_selection import universe_tickers

# --- Palette (see dataviz skill references/palette.md) ---
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
BLUE = "#2a78d6"    # gains, entries, "up"
RED = "#e34948"     # losses, exits, "down"
GRAY_MIDPOINT = "#f0efec"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial", "sans-serif"],
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": BASELINE,
    "axes.labelcolor": INK_SECONDARY,
    "text.color": INK_PRIMARY,
    "xtick.color": INK_MUTED,
    "ytick.color": INK_MUTED,
    "grid.color": GRIDLINE,
    "axes.grid": True,
    "grid.linewidth": 0.8,
    "axes.linewidth": 0.8,
    "font.size": 10,
})


def _fig_to_data_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _monthly_returns(equity_df: pd.DataFrame) -> pd.Series:
    monthly = equity_df["portfolio_value"].resample("ME").last()
    return (monthly.pct_change().dropna() * 100)


def _equity_drawdown_chart(equity_df: pd.DataFrame):
    running_max = equity_df["portfolio_value"].cummax()
    drawdown = (equity_df["portfolio_value"] - running_max) / running_max * 100

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 5.5), sharex=True,
                                    gridspec_kw={"height_ratios": [2.2, 1], "hspace": 0.12})
    ax1.plot(equity_df.index, equity_df["portfolio_value"], color=BLUE, linewidth=1.8)
    ax1.set_ylabel("Portfolio value ($)")
    ax1.set_title("Equity curve", loc="left", color=INK_PRIMARY, fontsize=12, fontweight="bold")
    ax1.grid(True, axis="y")
    ax1.spines[["top", "right"]].set_visible(False)

    ax2.fill_between(equity_df.index, drawdown, 0, color=RED, alpha=0.85, linewidth=0)
    ax2.set_ylabel("Drawdown (%)")
    ax2.grid(True, axis="y")
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax2.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax2.xaxis.get_major_locator()))

    return fig


def _monthly_returns_chart(equity_df: pd.DataFrame):
    returns = _monthly_returns(equity_df)
    if returns.empty:
        return None

    colors = [BLUE if r >= 0 else RED for r in returns.values]
    fig, ax = plt.subplots(figsize=(11, 3.6))
    ax.bar(returns.index, returns.values, width=20, color=colors, linewidth=0)
    ax.axhline(0, color=BASELINE, linewidth=0.8)
    ax.set_ylabel("Monthly return (%)")
    ax.set_title("Monthly returns", loc="left", color=INK_PRIMARY, fontsize=12, fontweight="bold")
    ax.grid(True, axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))

    # Legend (two categories, always present per dataviz guidance)
    from matplotlib.patches import Patch
    ax.legend(
        handles=[Patch(facecolor=BLUE, label="Winning months"), Patch(facecolor=RED, label="Losing months")],
        loc="upper left", frameon=False, fontsize=9,
    )
    return fig


def _r_multiple_histogram(trades: list):
    r_values = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    if not r_values:
        return None

    fig, ax = plt.subplots(figsize=(11, 3.6))
    bins = np.arange(min(-1, np.floor(min(r_values))), max(2, np.ceil(max(r_values))) + 0.5, 0.5)
    counts, edges, patches = ax.hist(r_values, bins=bins, linewidth=0)
    for patch, left_edge in zip(patches, edges[:-1]):
        patch.set_facecolor(BLUE if left_edge >= 0 else RED)
    ax.axvline(0, color=BASELINE, linewidth=0.8)
    ax.set_xlabel("R-multiple (trade P&L ÷ initial risk)")
    ax.set_ylabel("Number of trades")
    ax.set_title("R-multiple distribution", loc="left", color=INK_PRIMARY, fontsize=12, fontweight="bold")
    ax.grid(True, axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    return fig


def _price_marker_charts(price_data: dict, trades: list):
    tickers = list(price_data.keys())
    if not tickers:
        return None

    fig, axes = plt.subplots(len(tickers), 1, figsize=(11, 3.2 * len(tickers)), squeeze=False)
    axes = axes[:, 0]

    for i, (ax, ticker) in enumerate(zip(axes, tickers)):
        df = price_data[ticker]
        ax.plot(df.index, df["Close"], color=INK_MUTED, linewidth=1.1, zorder=1)

        ticker_trades = [t for t in trades if t["ticker"] == ticker]
        entry_dates = [t["entry_date"] for t in ticker_trades]
        entry_prices = [t["entry_price"] for t in ticker_trades]
        exit_dates = [t["exit_date"] for t in ticker_trades]
        exit_prices = [t["exit_price"] for t in ticker_trades]

        # A trend-following whipsaw-prone system can produce a LOT of trades
        # (this one does — see project findings on win rate/whipsaws), which
        # packs markers densely. Smaller + semi-transparent keeps individual
        # entries/exits legible instead of solidifying into a blob.
        if entry_dates:
            ax.scatter(entry_dates, entry_prices, marker="^", color=BLUE, s=26, alpha=0.6,
                       linewidths=0, zorder=3, label="Buy")
        if exit_dates:
            ax.scatter(exit_dates, exit_prices, marker="v", color=RED, s=26, alpha=0.6,
                       linewidths=0, zorder=3, label="Sell")

        ax.set_title(f"{ticker}  ({len(ticker_trades)} trades)", loc="left", color=INK_PRIMARY,
                     fontsize=11, fontweight="bold")
        ax.set_ylabel("Price ($)")
        ax.grid(True, axis="y")
        ax.spines[["top", "right"]].set_visible(False)

    axes[-1].xaxis.set_major_locator(mdates.AutoDateLocator())
    axes[-1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(axes[-1].xaxis.get_major_locator()))
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    # One legend for the whole figure (all subplots use the same Buy/Sell
    # encoding), placed above everything so it never overlaps price data
    # or per-subplot titles.
    from matplotlib.lines import Line2D
    legend_handles = [
        Line2D([0], [0], marker="^", color="none", markerfacecolor=BLUE, markersize=8, label="Buy"),
        Line2D([0], [0], marker="v", color="none", markerfacecolor=RED, markersize=8, label="Sell"),
    ]
    fig.legend(handles=legend_handles, loc="upper center", ncol=2, frameon=False,
               fontsize=9, bbox_to_anchor=(0.5, 1.0))
    return fig


def _stat_tiles_html(metrics: dict) -> str:
    def fmt(key, suffix="", digits=2, na="—"):
        v = metrics.get(key)
        return na if v is None else f"{v:,.{digits}f}{suffix}"

    def fmt_usd(key, na="—"):
        v = metrics.get(key)
        return na if v is None else f"${v:,.2f}"

    tiles = [
        ("Starting equity", fmt_usd("starting_cash")),
        ("Ending equity", fmt_usd("final_value")),
        ("Total return", fmt("total_return_pct", "%")),
        ("CAGR", fmt("annualized_return_pct", "%")),
        ("Max drawdown", fmt("max_drawdown_pct", "%")),
        ("Ulcer Index", fmt("ulcer_index", "", 3)),
        ("Win rate", fmt("win_rate_pct", "%")),
        ("Trades", fmt("n_trades", "", 0)),
        ("Avg R-multiple", fmt("avg_r_multiple", "R")),
        ("Profit Factor", fmt("profit_factor", "", 3)),
        ("System Quality (SQN)", fmt("system_quality_number", "", 2)),
        ("Sortino ratio", fmt("sortino_ratio", "", 3)),
        ("Calmar ratio", fmt("calmar_ratio", "", 3)),
        ("Beta / Alpha (vs SPY)", f"{fmt('beta', '', 3)} / {fmt('alpha_pct', '%')}"),
        ("Best / Worst R", f"{fmt('best_r_multiple', 'R')} / {fmt('worst_r_multiple', 'R')}"),
        ("Blocked by breaker", fmt("correlation_blocked_count", "", 0)),
        ("Rebalances", fmt("portfolio_rebalances", "", 0)),
        ("Avg portfolio size", fmt("avg_active_portfolio_size", "", 2)),
        ("Pyramid adds", fmt("pyramid_adds", "", 0)),
        ("Positions pyramided", fmt("positions_pyramided", "", 0)),
    ]
    cells = "".join(
        f'<div class="tile"><div class="tile-label">{label}</div>'
        f'<div class="tile-value">{value}</div></div>'
        for label, value in tiles
    )
    return f'<div class="tiles">{cells}</div>'


def _rebalance_history_html(rebalance_log: list) -> str:
    if not rebalance_log:
        return ""
    lines = []
    for r in rebalance_log:
        added = f"  +{r['added']}" if r["added"] else ""
        dropped = f"  -{r['dropped']}" if r["dropped"] else ""
        lines.append(f"{r['date'].date()}:  {r['selected']}{added}{dropped}")
    body = "\n".join(lines)
    return (
        '<div class="chart" style="padding: 16px 20px;">'
        '<div style="font-weight: 600; margin-bottom: 8px;">Portfolio selection history</div>'
        f'<div class="config">{body}</div></div>'
    )


def _universe_subtitle(cfg: dict) -> str:
    ps_cfg = cfg.get("portfolio_selection") or {}
    if ps_cfg.get("enabled"):
        candidates = universe_tickers(cfg)
        return f"{len(candidates)} candidates (target {ps_cfg.get('target_size')}): {', '.join(candidates)}"
    return ', '.join(cfg.get('watchlist', []))


def _entry_rule_subtitle(cfg: dict) -> str:
    entry_cfg = cfg.get("entry", {})
    entry_type = entry_cfg.get("type", "ma_crossover")
    if entry_type == "donchian_breakout":
        return f"donchian_breakout ({entry_cfg.get('breakout_period', 20)}-day)"
    return f"ma_crossover ({entry_cfg.get('ma_period', 20)}-day)"


def _exit_rule_subtitle(cfg: dict) -> str:
    """Returns "" (omitted entirely) for the default ma_crossover exit,
    same "only mention what's non-default" pattern as pyramiding's
    subtitle below — every pre-v11 report stays visually unchanged."""
    exit_cfg = cfg.get("exit", {})
    exit_type = exit_cfg.get("type", "ma_crossover")
    if exit_type == "donchian_low":
        return f" &middot; exit: donchian_low ({exit_cfg.get('exit_breakout_period', 10)}-day)"
    return ""


def _pyramiding_subtitle(cfg: dict) -> str:
    """Returns "" (omitted entirely) when pyramiding isn't enabled, same
    pattern as the rest of this file — the subtitle only grows to mention
    features a config actually opted into."""
    pyramid_cfg = (cfg.get("risk") or {}).get("pyramiding") or {}
    if not pyramid_cfg.get("enabled"):
        return ""
    interval = pyramid_cfg.get("unit_interval_n", 0.5)
    max_units = pyramid_cfg.get("max_units", 4)
    return f" &middot; pyramiding: +1 unit/{interval}N (max {max_units})"


def generate_html_report(result: dict, cfg: dict, price_data: dict, run_label: str, out_path: str) -> str:
    """
    result:     the dict returned by backtest.engine.run_backtest()
                ({"trades", "metrics", "equity_curve"})
    cfg:        the parsed strategy config used for this run
    price_data: {ticker: DataFrame} used for the price+marker charts
    run_label:  display label for the report header
    out_path:   where to write the HTML file
    """
    trades = result["trades"]
    metrics = result["metrics"]
    equity_df = result["equity_curve"]

    equity_img = _fig_to_data_uri(_equity_drawdown_chart(equity_df))

    monthly_fig = _monthly_returns_chart(equity_df)
    monthly_img = _fig_to_data_uri(monthly_fig) if monthly_fig else None

    r_fig = _r_multiple_histogram(trades)
    r_img = _fig_to_data_uri(r_fig) if r_fig else None

    price_fig = _price_marker_charts(price_data, trades)
    price_img = _fig_to_data_uri(price_fig) if price_fig else None

    sections = [f'<img class="chart" src="{equity_img}" alt="Equity curve and drawdown">']
    if monthly_img:
        sections.append(f'<img class="chart" src="{monthly_img}" alt="Monthly returns">')
    if r_img:
        sections.append(f'<img class="chart" src="{r_img}" alt="R-multiple distribution">')
    if price_img:
        sections.append(f'<img class="chart" src="{price_img}" alt="Price chart with buy/sell markers">')
    rebalance_html = _rebalance_history_html(result.get("rebalance_log") or [])
    if rebalance_html:
        sections.append(rebalance_html)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Backtest report — {run_label}</title>
<style>
  body {{
    margin: 0; padding: 32px 40px 60px;
    background: #f9f9f7; color: {INK_PRIMARY};
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .subtitle {{ color: {INK_SECONDARY}; font-size: 13px; margin-bottom: 24px; }}
  .tiles {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
    margin-bottom: 28px;
  }}
  .tile {{
    background: {SURFACE}; border: 1px solid {GRIDLINE}; border-radius: 8px;
    padding: 14px 16px;
  }}
  .tile-label {{ font-size: 12px; color: {INK_SECONDARY}; margin-bottom: 6px; }}
  .tile-value {{ font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; }}
  .chart {{
    width: 100%; display: block; margin-bottom: 24px;
    background: {SURFACE}; border: 1px solid {GRIDLINE}; border-radius: 8px;
    padding: 8px;
  }}
  .config {{
    font-size: 12px; color: {INK_SECONDARY}; white-space: pre-wrap;
    background: {SURFACE}; border: 1px solid {GRIDLINE}; border-radius: 8px;
    padding: 12px 16px; margin-top: 8px;
  }}
</style>
</head>
<body>
  <h1>Backtest report — {run_label}</h1>
  <div class="subtitle">
    {_universe_subtitle(cfg)} &middot; {cfg['backtest']['start_date']} to {cfg['backtest']['end_date']}
    &middot; sizing: {cfg.get('risk', {}).get('sizing_method', 'pct')}
    &middot; entry: {_entry_rule_subtitle(cfg)}{_exit_rule_subtitle(cfg)}{_pyramiding_subtitle(cfg)}
  </div>
  {_stat_tiles_html(metrics)}
  {''.join(sections)}
</body>
</html>
"""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def generate_blend_html_report(blend_result: dict, run_label: str, out_path: str) -> str:
    """
    Same report shell as generate_html_report, adapted for
    blend_backtest.py's two-sleeve blend (ETF + crypto, fixed weight)
    instead of a single config's run_backtest() result.

    Shows THREE separate stat-tile sections, not one: the ETF sleeve's
    OWN metrics (real trades, real win rate -- it runs its own full
    backtest), the crypto sleeve's OWN metrics (same), and the COMBINED
    blend's metrics last. The combined section's trade-level fields
    (n_trades, win_rate_pct, profit_factor, SQN, best/worst R) are
    genuinely always 0/None -- the blend combines the two sleeves'
    DAILY RETURNS, not their trade histories, so there's no unified
    trade log for it to report on. That's not a bug; it's inherent to
    blending returns instead of merging trade lists (see
    blend_backtest.py's docstring). The per-sleeve sections are where
    the real trade-level numbers live.

    No R-multiple histogram or per-ticker price/marker charts -- those
    need a single sleeve's own trade journal + price data, and showing
    them for one sleeve but not the other would be misleading about
    which one they belong to. Equity curve + drawdown and monthly
    returns are for the BLENDED curve, since that's the actual bottom
    line an investor would experience.

    blend_result: the dict returned by blend_backtest.run_blend()
    """
    metrics = blend_result["metrics"]
    equity_df = blend_result["equity_curve"]
    etf_m = blend_result["etf_result"]["metrics"]
    crypto_m = blend_result["crypto_result"]["metrics"]
    crypto_weight = blend_result["crypto_weight"]
    etf_watchlist = blend_result["etf_cfg"]["watchlist"]

    equity_img = _fig_to_data_uri(_equity_drawdown_chart(equity_df))
    monthly_fig = _monthly_returns_chart(equity_df)
    monthly_img = _fig_to_data_uri(monthly_fig) if monthly_fig else None

    sections = [f'<img class="chart" src="{equity_img}" alt="Blended equity curve and drawdown">']
    if monthly_img:
        sections.append(f'<img class="chart" src="{monthly_img}" alt="Monthly returns">')

    def section(title, subtitle, tile_html):
        return (
            f'<h2 style="font-size:15px; margin: 28px 0 4px;">{title}</h2>'
            f'<div class="subtitle" style="margin-bottom:12px;">{subtitle}</div>'
            f'{tile_html}'
        )

    start = equity_df.index[0].date()
    end = equity_df.index[-1].date()
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Blend report — {run_label}</title>
<style>
  body {{
    margin: 0; padding: 32px 40px 60px;
    background: #f9f9f7; color: {INK_PRIMARY};
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  h2 {{ color: {INK_PRIMARY}; }}
  .subtitle {{ color: {INK_SECONDARY}; font-size: 13px; margin-bottom: 24px; }}
  .tiles {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
    margin-bottom: 28px;
  }}
  .tile {{
    background: {SURFACE}; border: 1px solid {GRIDLINE}; border-radius: 8px;
    padding: 14px 16px;
  }}
  .tile-label {{ font-size: 12px; color: {INK_SECONDARY}; margin-bottom: 6px; }}
  .tile-value {{ font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; }}
  .chart {{
    width: 100%; display: block; margin-bottom: 24px;
    background: {SURFACE}; border: 1px solid {GRIDLINE}; border-radius: 8px;
    padding: 8px;
  }}
</style>
</head>
<body>
  <h1>Blend report — {run_label}</h1>
  <div class="subtitle">
    {1 - crypto_weight:.0%} ETF ({', '.join(etf_watchlist)}) / {crypto_weight:.0%} crypto (fixed weight, not momentum-rotated)
    &middot; {start} to {end}
  </div>

  {section(
      f"ETF sleeve ({', '.join(etf_watchlist)}) — {1 - crypto_weight:.0%} weight",
      "Runs its own full backtest with its own trades — these are real, sleeve-specific numbers.",
      _stat_tiles_html(etf_m),
  )}

  {section(
      f"Crypto sleeve (config/strategy_master.yaml) — {crypto_weight:.0%} weight",
      "Same — its own independent backtest and trade history.",
      _stat_tiles_html(crypto_m),
  )}

  {section(
      "Combined (blended) portfolio",
      "The two sleeves' DAILY RETURNS blended at the weights above, not a merged trade list — "
      "there's no unified trade log to report on, so n_trades/win_rate/profit_factor/SQN are "
      "always 0 or None here by design. Return/drawdown/Sortino/Calmar below are the real "
      "bottom-line numbers for the combined portfolio.",
      _stat_tiles_html(metrics),
  )}

  {''.join(sections)}
</body>
</html>
"""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path
