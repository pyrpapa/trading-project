# Backtest run: v4-earlier-2012-2018

Run at: 2026-07-24T22:06:24.170837+00:00

Watchlist: SPY, AAPL, MSFT

Period: 2012-01-01 to 2018-12-31

## Metrics

| Metric | Value |
|---|---|
| n_trades | 222 |
| avg_win_pct | 4.86 |
| final_value | 12206.6 |
| avg_loss_pct | -1.94 |
| win_rate_pct | 35.59 |
| starting_cash | 10000 |
| max_drawdown_pct | -7.28 |
| total_return_pct | 22.07 |
| annualized_return_pct | 2.9 |
| longest_losing_streak | 10 |

## Config used

```yaml
{
  "exit": {
    "ma_exit": true,
    "stop_loss_pct": 8.0,
    "take_profit_pct": null
  },
  "risk": {
    "max_invested_pct": 60.0,
    "max_position_pct": 20.0
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
