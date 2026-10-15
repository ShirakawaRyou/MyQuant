#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$Project = Split-Path -Parent $PSScriptRoot
$Service = Join-Path $Project 'services\dashboard'
$Python = Join-Path $Service '.venv\Scripts\python.exe'

function Invoke-MyQuant {
    param([string[]] $Arguments)
    if (-not (Test-Path -LiteralPath $Python)) {
        throw '请先运行 Setup-Windows.cmd 完成安装。'
    }
    & $Python -m myquant_dashboard.local @Arguments
    if ($LASTEXITCODE -ne 0) { throw '操作未完成，请查看上方错误与本机日志。' }
}
