// Curated reference list, not exhaustive -- grouped by asset type so a
// long list stays scannable. Draws from tickers this project has
// actually touched (the leveraged-ETF watchlist, the preserved crypto
// track, holdout_test.py's traditional-asset candidates -- see that
// script and config/strategy_master.yaml's history) plus a broader set
// of liquid large-caps so the picker is useful beyond just this
// project's own history. Anything not listed can still be typed into
// the "add custom ticker(s)" field below the grid.
const TICKER_GROUPS = {
  "Leveraged ETFs": ["SPXL", "TQQQ", "SOXL", "FAS", "TNA", "TECL", "ERX", "TMF", "YINN", "DRN", "CURE"],
  "Broad market / sector ETFs": ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLU", "XLY", "XLP", "XLB", "XLRE"],
  "Bonds / commodities / REITs": ["TLT", "AGG", "GLD", "SLV", "DBC", "VNQ", "VEA"],
  "Stocks": ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "NFLX", "JPM", "V", "WMT", "DIS", "BA", "XOM", "UNH", "HD", "PG", "MA", "COST"],
  "Crypto": ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "LINK-USD", "AVAX-USD", "LTC-USD", "ADA-USD", "DOT-USD", "UNI-USD", "BCH-USD", "FIL-USD", "RENDER-USD", "AAVE-USD", "CRV-USD", "LDO-USD"],
};

export default function TickerPicker({ selected, onChange, customText, onCustomTextChange }) {
  function toggle(ticker) {
    onChange(selected.includes(ticker) ? selected.filter((t) => t !== ticker) : [...selected, ticker]);
  }

  return (
    <div>
      {Object.entries(TICKER_GROUPS).map(([group, tickers]) => (
        <div key={group} style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 11, color: "var(--text-faint)", marginBottom: 4 }}>{group}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {tickers.map((t) => {
              const active = selected.includes(t);
              return (
                <button
                  type="button"
                  key={t}
                  onClick={() => toggle(t)}
                  style={{
                    background: active ? "var(--accent)" : "var(--surface-raised)",
                    color: active ? "var(--bg)" : "var(--text-primary)",
                    border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`,
                    borderRadius: 4,
                    padding: "3px 8px",
                    fontSize: 12,
                    fontFamily: "var(--font-mono)",
                    cursor: "pointer",
                  }}
                >
                  {t}
                </button>
              );
            })}
          </div>
        </div>
      ))}
      <label style={{ display: "block", fontSize: 12, color: "var(--text-muted)", marginTop: 8, marginBottom: 6 }}>
        Add custom ticker(s) — comma-separated, for anything not listed above
      </label>
      <input
        type="text"
        value={customText}
        onChange={(e) => onCustomTextChange(e.target.value)}
        placeholder="e.g. IBIT, ARKK"
        style={{
          width: "100%",
          padding: "8px 10px",
          background: "var(--surface-raised)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          color: "var(--text-primary)",
          fontSize: 13,
        }}
      />
      {selected.length > 0 && (
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 8 }}>
          Selected: <span style={{ color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>{selected.join(", ")}</span>
        </div>
      )}
    </div>
  );
}
