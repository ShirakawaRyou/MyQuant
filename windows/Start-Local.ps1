#requires -Version 5.1
. "$PSScriptRoot\Common.ps1"
Invoke-MyQuant -Arguments @('start', '--open')
Write-Host '后台和看板已独立启动，可以关闭此窗口。关闭浏览器不会停止策略。'
