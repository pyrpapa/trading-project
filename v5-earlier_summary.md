# Backtest run: v5-earlier

Run at: 2026-08-04T02:39:50.639409+00:00

Watchlist: SPY, AAPL, MSFT

Period: 2012-01-01 to 2018-12-31

## Metrics

| Metric | Value |
|---|---|
| n_trades | 223 |
| avg_win_pct | 4.86 |
| final_value | 12267.51 |
| avg_loss_pct | -1.93 |
| win_rate_pct | 35.43 |
| starting_cash | 10000 |
| avg_r_multiple | 0.204 |
| best_r_multiple | 10.688 |
| max_drawdown_pct | -7.43 |
| r_multiple_stdev | 1.652 |
| total_return_pct | 22.68 |
| worst_r_multiple | -3.043 |
| annualized_return_pct | 2.97 |
| longest_losing_streak | 10 |
| system_quality_number | 1.846 |
| trades_with_r_multiple | 223 |

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
    "end_date": "2018-12-31",
    "start_date": "2012-01-01",
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
