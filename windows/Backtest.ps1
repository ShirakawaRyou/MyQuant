#requires -Version 5.1
param([ValidateSet('development', 'validation', 'holdout')][string] $Stage = 'holdout')
. "$PSScriptRoot\Common.ps1"
Invoke-MyQuant -Arguments @('backtest', '--stage', $Stage)
