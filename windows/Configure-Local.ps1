#requires -Version 5.1
param(
    [ValidateSet(7497, 4002)][int] $ApiPort = 7497,
    [int] $DashboardPort = 8090,
    [string] $Account = '',
    [switch] $EnablePaperOrders
)
. "$PSScriptRoot\Common.ps1"
$Mode = 'disabled'
if ($EnablePaperOrders) { $Mode = 'enabled' }
$Configuration = @('configure', '--api-port', "$ApiPort", '--dashboard-port', "$DashboardPort", '--paper-orders', $Mode)
if ($Account) { $Configuration += @('--account', $Account) }
Invoke-MyQuant -Arguments $Configuration
