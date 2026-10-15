#requires -Version 5.1
param(
    [ValidateSet(7497, 4002)][int] $ApiPort = 7497,
    [int] $DashboardPort = 8090,
    [string] $Account = '',
    [switch] $EnablePaperOrders
)
. "$PSScriptRoot\Common.ps1"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw '请先按 Windows 部署说明安装 uv，然后重新打开此窗口。'
}
Push-Location $Service
try {
    & uv sync --frozen --no-dev --python 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Python 或依赖安装失败；请检查网络与上方错误。' }
} finally { Pop-Location }
$Mode = 'disabled'
if ($EnablePaperOrders) { $Mode = 'enabled' }
$Configuration = @('configure', '--api-port', "$ApiPort", '--dashboard-port', "$DashboardPort", '--paper-orders', $Mode)
if ($Account) { $Configuration += @('--account', $Account) }
Invoke-MyQuant -Arguments $Configuration
Invoke-MyQuant -Arguments @('password')
Write-Host '安装完成。请在官方 TWS/Gateway 登录模拟账户并配置 API，然后运行 Start-Local.cmd。'
