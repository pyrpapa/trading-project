param(
    [string]$command,
    [string]$label = ""
)

function Invoke-Backtest([string]$configPath, [string]$defaultLabel, [switch]$Synthetic) {
    $useLabel = if ($label) { $label } else { $defaultLabel }
    if ($Synthetic) {
        # Synthetic runs don't --save to Supabase, so there's nothing to export.
        $cmd = "python run_backtest.py --config `"$configPath`" --synthetic --chart --label `"$useLabel`""
        Invoke-Expression $cmd
    } else {
        $cmd = "python run_backtest.py --config `"$configPath`" --chart --save --label `"$useLabel`""
        Invoke-Expression $cmd
        python export_run.py --label "$useLabel"
    }
}

function Invoke-BacktestSet([string[]]$configs, [string[]]$labels) {
    for ($i = 0; $i -lt $configs.Length; $i++) {
        Invoke-Backtest $configs[$i] $labels[$i]
    }
}

switch ($command) {
    "install"             { pip install -r requirements.txt }
    "cache"               { python data/fetcher.py }

    "backtest"            { Invoke-Backtest "config/strategy.yaml" "base-run" }
    "backtest-synthetic"  { Invoke-Backtest "config/strategy.yaml" "synthetic-test" -Synthetic }

    "backtest-v4"         { Invoke-Backtest "config/strategy_v4.yaml" "v4-2019-2024" }
    "backtest-v4-earlier" { Invoke-Backtest "config/strategy_v4_earlier.yaml" "v4-earlier" }
    "backtest-v4-crisis"  { Invoke-Backtest "config/strategy_v4_crisis.yaml" "v4-crisis" }
    "backtest-all-v4"     {
        $configs = @("config/strategy_v4.yaml", "config/strategy_v4_earlier.yaml", "config/strategy_v4_crisis.yaml")
        $labels  = @("v4-2019-2024", "v4-earlier", "v4-crisis")
        Invoke-BacktestSet $configs $labels
    }

    "backtest-v5"         { Invoke-Backtest "config/strategy_v5_n_sizing.yaml" "v5-2019-2024" }
    "backtest-v5-earlier" { Invoke-Backtest "config/strategy_v5_earlier.yaml" "v5-earlier" }
    "backtest-v5-crisis"  { Invoke-Backtest "config/strategy_v5_crisis.yaml" "v5-crisis" }
    "backtest-all-v5"     {
        $configs = @("config/strategy_v5_n_sizing.yaml", "config/strategy_v5_earlier.yaml", "config/strategy_v5_crisis.yaml")
        $labels  = @("v5-2019-2024", "v5-earlier", "v5-crisis")
        Invoke-BacktestSet $configs $labels
    }

    "backtest-v6"         { Invoke-Backtest "config/strategy_v6_circuit_breaker.yaml" "v6-2019-2024" }
    "backtest-v7"         { Invoke-Backtest "config/strategy_v7_portfolio_selection.yaml" "v7-2019-2024" }
    "backtest-v8"         { Invoke-Backtest "config/strategy_v8_donchian_breakout.yaml" "v8-2019-2024" }
    "backtest-v9"         { Invoke-Backtest "config/strategy_v9_donchian_portfolio.yaml" "v9-2019-2024" }
    "backtest-v10"        { Invoke-Backtest "config/strategy_v10_pyramiding.yaml" "v10-2019-2024" }
    "backtest-v11"        { Invoke-Backtest "config/strategy_v11_donchian_exit.yaml" "v11-2019-2024" }
    "backtest-v12"        { Invoke-Backtest "config/strategy_v12_pyramid_donchian_exit.yaml" "v12-2019-2024" }
    "backtest-v12-crisis" { Invoke-Backtest "config/strategy_v12_pyramid_donchian_exit_crisis.yaml" "v12-crisis" }

    "backtest-compare"    {
        Invoke-Backtest "config/strategy_v4.yaml" "v4-2019-2024"
        Invoke-Backtest "config/strategy_v5_n_sizing.yaml" "v5-2019-2024"
    }

    "export" {
        # Every backtest-* run already exports itself automatically.
        # This is only for re-exporting a run that was saved earlier.
        if (-not $label) {
            Write-Host "Usage: .\run.ps1 export -label `"run-label`""
        } else {
            python export_run.py --label "$label"
        }
    }

    "dry-run"             { python live/run_live.py --dry-run }
    "live"                { python live/run_live.py }

    default {
        Write-Host "Available commands:"
        Write-Host "  install              Install/update Python dependencies"
        Write-Host "  cache                Pre-populate the local price data cache"
        Write-Host ""
        Write-Host "  backtest             Run the default config (config/strategy.yaml) on real data"
        Write-Host "  backtest-synthetic   Run the default config on offline synthetic data (no internet needed)"
        Write-Host ""
        Write-Host "  backtest-v4          Run v4 (flat % sizing) on 2019-2024"
        Write-Host "  backtest-v4-earlier  Run v4 on 2012-2018"
        Write-Host "  backtest-v4-crisis   Run v4 on 2006-2011"
        Write-Host "  backtest-all-v4      Run all three v4 windows in sequence"
        Write-Host ""
        Write-Host "  backtest-v5          Run v5 (N/ATR-based sizing) on 2019-2024"
        Write-Host "  backtest-v5-earlier  Run v5 on 2012-2018"
        Write-Host "  backtest-v5-crisis   Run v5 on 2006-2011"
        Write-Host "  backtest-all-v5      Run all three v5 windows in sequence"
        Write-Host ""
        Write-Host "  backtest-v6          Run v6 (N-sizing + correlation circuit breaker) on 2019-2024"
        Write-Host ""
        Write-Host "  backtest-v7          Run v7 (N-sizing + portfolio selection) on 2019-2024"
        Write-Host ""
        Write-Host "  backtest-v8          Run v8 (N-sizing + Donchian breakout entries) on 2019-2024"
        Write-Host ""
        Write-Host "  backtest-v9          Run v9 (Donchian breakout entries + portfolio selection) on 2019-2024"
        Write-Host ""
        Write-Host "  backtest-v10         Run v10 (v5 baseline + Turtle-style pyramiding) on 2019-2024"
        Write-Host ""
        Write-Host "  backtest-v11         Run v11 (v5 baseline + Turtle-style Donchian-low exit) on 2019-2024"
        Write-Host ""
        Write-Host "  backtest-v12         Run v12 (v5 baseline + pyramiding + Donchian-low exit) on 2019-2024"
        Write-Host "  backtest-v12-crisis  Run v12 on 2006-2011 (stress-test against a real crash)"
        Write-Host ""
        Write-Host "  backtest-compare     Run v4 and v5 on 2019-2024 back to back, for a quick side-by-side"
        Write-Host ""
        Write-Host "  export               Re-export an already-saved run to CSV + markdown (requires -label)"
        Write-Host "                       (not needed after backtest-* - those export automatically)"
        Write-Host ""
        Write-Host "  dry-run              Run the live/paper check without placing any orders"
        Write-Host "  live                 Run the live/paper check for real (submits orders on your paper account)"
        Write-Host ""
        Write-Host "Every backtest-* command (except -synthetic) saves to Supabase, writes an HTML"
        Write-Host "chart report to results/, and exports a CSV + markdown summary -- all in one go."
        Write-Host "Override the auto-generated label:  .\run.ps1 backtest-v4 -label `"my-custom-label`""
        Write-Host "Example:                             .\run.ps1 backtest-all-v5"
    }
}
