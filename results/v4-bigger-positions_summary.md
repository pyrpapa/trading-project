# Backtest run: v4-bigger-positions

Run at: 2026-07-24T21:46:07.878416+00:00

Watchlist: SPY, AAPL, MSFT

Period: 2019-01-01 to 2024-12-31

## Metrics

| Metric | Value |
|---|---|
| n_trades | 152 |
| avg_win_pct | 7.22 |
| final_value | 17596.58 |
| avg_loss_pct | -2.3 |
| win_rate_pct | 44.08 |
| starting_cash | 10000 |
| max_drawdown_pct | -9.58 |
| total_return_pct | 75.97 |
| annualized_return_pct | 9.89 |
| longest_losing_streak | 8 |

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
    "end_date": "2024-12-31",
    "start_date": "2019-01-01",
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
