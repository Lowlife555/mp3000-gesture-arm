# 第二轮：宽概念收割（每条 limit 100），与第一轮 288 条合并
# gh search repos 是 AND 语义、只搜 name/description/topics → 宽单词才出量

$ErrorActionPreference = 'Stop'
$prevFile = Join-Path $env:TEMP 'gh_harvest.json'
$outFile  = Join-Path $env:TEMP 'gh_harvest2.json'
$logFile  = Join-Path $env:TEMP 'gh_harvest2.log'

$queries = @(
  'visual servoing',
  'visual servo',
  'aruco',
  'apriltag',
  'robot arm',
  'robotic arm',
  'manipulator',
  'pick and place',
  'robot vision',
  'robot arm vision',
  'visual servoing robot',
  '机械臂',
  '视觉伺服',
  'robot grasping',
  'object sorting robot',
  'robotic manipulation',
  'hand eye calibration',
  'vision guided robot',
  'robot arm arduino',
  'robot arm python'
)

# 载入第一轮
$store = @{}
if (Test-Path $prevFile) {
    $prev = Get-Content $prevFile -Raw | ConvertFrom-Json
    foreach ($p in $prev) {
        $store[$p.fullName] = [pscustomobject]@{
            fullName = $p.fullName; stars = $p.stars; description = $p.description
            url = $p.url; updatedAt = $p.updatedAt; isArchived = $p.isArchived
            isFork = $p.isFork; hits = $p.hits; viaQueries = @($p.viaQueries)
        }
    }
    Write-Output "载入第一轮: $($store.Count)"
} else {
    Write-Output "⚠️ 第一轮结果不存在，只跑第二轮"
}

"round2 start, base=$($store.Count)" | Out-File $logFile -Encoding utf8
$done = 0
foreach ($q in $queries) {
    $done++
    try {
        $json = gh search repos $q --limit 100 --json fullName,stargazersCount,description,url,updatedAt,isArchived,isFork 2>$null
        $items = if ($json) { $json | ConvertFrom-Json } else { @() }
        $new = 0
        foreach ($it in $items) {
            if (-not $it.fullName) { continue }
            $k = $it.fullName
            if ($store.ContainsKey($k)) {
                $store[$k].hits = $store[$k].hits + 1
            } else {
                $store[$k] = [pscustomobject]@{
                    fullName = $k; stars = [int]$it.stargazersCount; description = $it.description
                    url = $it.url; updatedAt = $it.updatedAt; isArchived = [bool]$it.isArchived
                    isFork = [bool]$it.isFork; hits = 1; viaQueries = @($q)
                }
                $new++
            }
        }
        $line = ("{0,2}/{1}  {2,-24} 返回{3,-4} 新增{4,-4} 累计{5}" -f $done, $queries.Count, $q, $items.Count, $new, $store.Count)
    } catch {
        $line = ("{0,2}/{1}  {2,-24} ERROR {3}" -f $done, $queries.Count, $q, $_.Exception.Message)
    }
    Write-Output $line
    $line | Out-File $logFile -Append -Encoding utf8
    Start-Sleep -Milliseconds 2400
}

$store.Values | Sort-Object @{Expression='hits';Descending=$true}, @{Expression='stars';Descending=$true} |
    ConvertTo-Json -Depth 5 | Out-File $outFile -Encoding utf8

Write-Output ""
Write-Output "==== 第二轮完成 ===="
Write-Output "去重后唯一仓库总数: $($store.Count)"
Write-Output "输出: $outFile"
