<#
.SYNOPSIS
  树莓派看门狗（Windows 侧）—— 后台记录树莓派每个端口的生死，写 CSV。

.DESCRIPTION
  为什么要有它：树莓派每次死掉，日志都丢（journald 没落盘），事后完全查不到。
  这个脚本跑在你的笔记本上，**树莓派整个死透它照样在记**。
  它每 N 秒探一次 ICMP + 4 个端口，记下：
    - 精确到秒的死亡时间
    - **哪个端口先死**（这是关键诊断信息）
        所有端口同一秒全死  → 整机断电/硬挂
        8090 先死、22 后死   → 是演示服务的问题，机器还活着
        只有 22 死、其余活   → sshd 的问题
    - 死亡前响应时间有没有变慢（能不能看出"先卡后死"）

  日志：<脚本目录>\..\logs\pi_watch_YYYYMMDD.csv
        每行：时间, ICMP, 22, 8090, 6080, 5900, 延迟ms, 状态变化

.PARAMETER Target
  树莓派 IP，默认 192.168.1.66

.PARAMETER IntervalSec
  探测间隔秒，默认 5

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File watch_pi.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File watch_pi.ps1 -IntervalSec 3
#>
param(
    [string]$Target = "192.168.1.66",
    [int]$IntervalSec = 5
)

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path (Split-Path -Parent $scriptDir) "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$logFile = Join-Path $logDir ("pi_watch_" + (Get-Date -Format "yyyyMMdd") + ".csv")

if (-not (Test-Path $logFile)) {
    "timestamp,icmp,port22,port8090,port6080,port5900,latency_ms,note" |
        Out-File -FilePath $logFile -Encoding utf8
}

function Test-PingFast {
    param([string]$H, [int]$TimeoutMs = 800)
    try {
        $p = New-Object System.Net.NetworkInformation.Ping
        $r = $p.Send($H, $TimeoutMs)
        return ($r.Status -eq [System.Net.NetworkInformation.IPStatus]::Success)
    } catch { return $false }
}

function Test-PortFast {
    param([string]$H, [int]$P, [int]$TimeoutMs = 700)
    $s = $null
    try {
        $s = New-Object System.Net.Sockets.Socket(
            [System.Net.Sockets.AddressFamily]::InterNetwork,
            [System.Net.Sockets.SocketType]::Stream,
            [System.Net.Sockets.ProtocolType]::Tcp)
        $iar = $s.BeginConnect($H, $P, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne($TimeoutMs)) { return $false }
        $s.EndConnect($iar)
        return $true
    } catch {
        return $false
    } finally {
        if ($s) { try { $s.Close() } catch {} }
    }
}

$ports = @(22, 8090, 6080, 5900)
$prevSig = $null
$prevState = $null

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " 树莓派看门狗  ->  $Target   每 $IntervalSec 秒" -ForegroundColor Cyan
Write-Host " 日志: $logFile" -ForegroundColor Cyan
Write-Host " 按 Ctrl+C 停止。这个窗口别关。" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host ("  {0}   {1,-5} {2,-4} {3,-6} {4,-6} {5,-6} {6,8}  {7}" -f `
    "时间", "ICMP", "22", "8090", "6080", "5900", "延迟ms", "事件") -ForegroundColor DarkGray

while ($true) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $icmp = Test-PingFast -H $Target
    $res = @{}
    foreach ($p in $ports) { $res[$p] = Test-PortFast -H $Target -P $p }
    $sw.Stop()
    $lat = [math]::Round($sw.Elapsed.TotalMilliseconds)

    $anyOpen = ($res.Values -contains $true)
    $state = if ($anyOpen) { "UP" } else { "DOWN" }
    $sig = "$icmp|$($res[22])|$($res[8090])|$($res[6080])|$($res[5900])"

    $note = ""
    if ($prevSig -ne $null -and $sig -ne $prevSig) {
        $wentDown = @($ports | Where-Object { -not $res[$_] })
        if (-not $anyOpen) {
            $note = "ALL_DOWN 整机不通"
        } elseif ($wentDown.Count -gt 0) {
            $note = "PARTIAL_DOWN 掉了端口: " + ($wentDown -join "/")
        } else {
            $note = "RECOVERED 全部恢复"
        }
    }

    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "{0},{1},{2},{3},{4},{5},{6},{7}" -f `
        $ts, $icmp, $res[22], $res[8090], $res[6080], $res[5900], $lat, $note
    try { Add-Content -Path $logFile -Value $line -Encoding utf8 } catch {}

    $mark = if ($icmp) { "OK" } else { "--" }
    $c = if (-not $anyOpen) { "Red" } elseif ($note) { "Yellow" } else { "Gray" }
    if ($note -or ($state -ne $prevState)) {
        Write-Host ("  {0}   {1,-5} {2,-4} {3,-6} {4,-6} {5,-6} {6,8}  {7}" -f `
            $ts,
            $mark,
            $(if ($res[22]) { "OK" } else { "--" }),
            $(if ($res[8090]) { "OK" } else { "--" }),
            $(if ($res[6080]) { "OK" } else { "--" }),
            $(if ($res[5900]) { "OK" } else { "--" }),
            $lat, $note) -ForegroundColor $c
        if ($note) {
            Write-Host ("   >>> 状态变化 @ {0}  {1}" -f $ts, $note) -ForegroundColor Yellow
        }
    }

    $prevSig = $sig
    $prevState = $state
    Start-Sleep -Seconds $IntervalSec
}
