# Backtest run: v5-crisis

Run at: 2026-08-04T02:32:58.753429+00:00

Watchlist: SPY, AAPL, MSFT

Period: 2006-01-01 to 2011-12-31

## Metrics

| Metric | Value |
|---|---|
| n_trades | 173 |
| avg_win_pct | 6.82 |
| final_value | 12970.06 |
| avg_loss_pct | -2.58 |
| win_rate_pct | 36.42 |
| starting_cash | 10000 |
| avg_r_multiple | 0.186 |
| best_r_multiple | 7.464 |
| max_drawdown_pct | -16.19 |
| r_multiple_stdev | 1.465 |
| total_return_pct | 29.7 |
| worst_r_multiple | -4.27 |
| annualized_return_pct | 4.44 |
| longest_losing_streak | 18 |
| system_quality_number | 1.671 |
| trades_with_r_multiple | 173 |

## Config used

```yaml
{
  "exit": {
    "ma_exit": true,
    "stop_loss_pct": 8.0,
    "take_profit_pct": null
  },
  "risk": {
    "atr_period": 20,
    "sizing_method": "atr_unit",
    "max_invested_pct": 60.0,
    "max_position_pct": 20.0,
    "risk_pct_per_unit": 1.0,
    "stop_atr_multiple": 2.0
  },
  "entry": {
    "ma_period": 20,
    "volume_ma_period": 20,
    "volume_confirmation": true
  },
  "backtest": {
    "end_date": "2011-12-31",
    "start_date": "2006-01-01",
    "starting_cash": 10000,
    "commission_pct": 0.0
  },
  "watchlist": [
    "SPY",
    "AAPL",
    "MSFT"
  ]
}
```
