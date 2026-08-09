# Backtest run: v4-crisis-2006-2011

Run at: 2026-07-24T22:11:00.165499+00:00

Watchlist: SPY, AAPL, MSFT

Period: 2006-01-01 to 2011-12-31

## Metrics

| Metric | Value |
|---|---|
| n_trades | 173 |
| avg_win_pct | 6.82 |
| final_value | 13037.37 |
| avg_loss_pct | -2.59 |
| win_rate_pct | 36.42 |
| starting_cash | 10000 |
| max_drawdown_pct | -20.6 |
| total_return_pct | 30.37 |
| annualized_return_pct | 4.53 |
| longest_losing_streak | 18 |

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
