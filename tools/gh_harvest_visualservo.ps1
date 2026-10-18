# GitHub 视觉伺服大范围调研 —— 关键词收割
# 用 gh 官方 search API（authenticated, 30/min），逐条搜、去重、落盘。
# 输出：$env:TEMP\gh_harvest.json

$ErrorActionPreference = 'Stop'
$outFile = Join-Path $env:TEMP 'gh_harvest.json'
$logFile = Join-Path $env:TEMP 'gh_harvest.log'

# ---- 100 个关键词，按设计空间分组 ----
$queries = @(
  # A. 视觉伺服核心方法 (15)
  'visual servoing robot arm',
  'visual servo manipulator',
  'image based visual servoing',
  'position based visual servoing',
  'IBVS robot',
  'PBVS robot',
  'eye in hand calibration',
  'eye to hand calibration',
  'uncalibrated visual servoing',
  'direct visual servoing',
  'visual servoing opencv',
  'visual servoing python',
  'visual feedback robot control',
  'camera guided robot arm',
  'vision guided manipulation',
  # B. ArUco / AprilTag / 基准标记 (15)
  'aruco robot arm',
  'aruco visual servoing',
  'aruco pick and place',
  'aruco gripper',
  'aruco pose estimation robot',
  'aruco marker control',
  'apriltag robot arm',
  'apriltag visual servoing',
  'apriltag tracking robot',
  'fiducial marker robot control',
  'aruco camera calibration robot',
  'opencv aruco tracking',
  'marker based robot positioning',
  'aruco end effector',
  'aruco 6dof pose robot',
  # C. 无编码器 / 开环直流 / 无传感器 (12)
  'robot arm without encoder',
  'encoderless motor control',
  'sensorless position control motor',
  'dc motor position control camera',
  'vision based motor control',
  'open loop dc motor positioning',
  'camera feedback dc motor',
  'stepper camera closed loop',
  'servo motor camera feedback',
  'position control without encoder',
  'visual position sensing motor',
  'camera based motor positioning',
  # D. 平台 (18)
  'raspberry pi robot arm opencv',
  'raspberry pi visual servoing',
  'raspberry pi robot arm camera',
  'raspberry pi pick and place',
  'raspberry pi robotic manipulator',
  'stm32 robot arm',
  'stm32 visual servoing',
  'stm32 camera robot',
  'stm32 robotic arm control',
  'stm32 dc motor control',
  'arduino visual servoing',
  'arduino robot arm camera',
  'arduino robotic arm opencv',
  'esp32 robot arm camera',
  'esp32 visual servoing',
  'jetson robot arm vision',
  'micropython robot arm',
  'openmv robot arm',
  # E. 抓取 / 分拣 / 垃圾 (15)
  'robotic pick and place opencv',
  'robot arm grasping opencv',
  'vision guided pick and place',
  'object sorting robot arm camera',
  'garbage sorting robot arm',
  'waste sorting robot vision',
  'trash classification robot',
  'color sorting robot arm',
  'conveyor belt sorting vision',
  'bin picking robot vision',
  'robot arm object detection grasp',
  'yolo robot arm grasp',
  'yolo visual servoing',
  'grasp detection robot arm',
  'robotic sorting machine learning',
  # F. 机械臂运动学 + 视觉 (10)
  '5 axis robot arm arduino',
  '6 dof robot arm diy',
  'robot arm inverse kinematics python',
  'robot arm forward kinematics opencv',
  'robotic arm kinematics library',
  'servo robot arm library',
  'robot arm trajectory camera',
  'robot arm pose estimation camera',
  'manipulator kinematics vision',
  'robotic arm simulation visual',
  # G. 库 / 框架 (8)
  'visp visual servoing',
  'visp ros',
  'roboticstoolbox python',
  'moveit visual servoing',
  'opencv aruco module',
  'pyrobot arm vision',
  'ros2 robot arm vision',
  'gazebo visual servoing',
  # H. 中文与其他 (7)
  '视觉伺服',
  '机械臂 视觉 抓取',
  '机械臂 opencv',
  '视觉 机械臂 控制',
  '树莓派 机械臂',
  '机械臂 摄像头 定位',
  'visual servoing thesis'
)

"total queries: $($queries.Count)" | Out-File -FilePath $logFile -Encoding utf8
Write-Output "关键词总数: $($queries.Count)"

$store = @{}
$done = 0
$failed = @()

foreach ($q in $queries) {
    $done++
    # 限流保护：每 10 条查一次配额
    if ($done % 10 -eq 1 -and $done -gt 1) {
        try {
            $rl = gh api rate_limit --jq '.resources.search.remaining' 2>$null
            $rem = [int]$rl
            if ($rem -lt 8) {
                Write-Output ("  [限流] 剩余 $rem，等 65 秒")
                Start-Sleep -Seconds 65
            }
        } catch { }
    }

    try {
        $json = gh search repos $q --limit 30 --json fullName,stargazersCount,description,url,updatedAt,isArchived,isFork 2>$null
        if ($json) {
            $items = $json | ConvertFrom-Json
            $new = 0
            foreach ($it in $items) {
                $k = $it.fullName
                if (-not $k) { continue }
                if ($store.ContainsKey($k)) {
                    # 同一个仓库被多个关键词命中 → 累加命中次数（= 相关性信号）
                    $store[$k].hits = $store[$k].hits + 1
                } else {
                    $store[$k] = [pscustomobject]@{
                        fullName    = $k
                        stars       = [int]$it.stargazersCount
                        description = $it.description
                        url         = $it.url
                        updatedAt   = $it.updatedAt
                        isArchived  = [bool]$it.isArchived
                        isFork      = [bool]$it.isFork
                        hits        = 1
                        viaQueries  = @($q)
                    }
                    $new++
                }
            }
            $line = ("{0,3}/{1}  {2,-45} +{3,-3} 累计{4}" -f $done, $queries.Count, $q, $new, $store.Count)
        } else {
            $line = ("{0,3}/{1}  {2,-45}  空" -f $done, $queries.Count, $q)
        }
        Write-Output $line
        $line | Out-File -FilePath $logFile -Append -Encoding utf8
    } catch {
        $failed += $q
        $msg = ("{0,3}/{1}  {2,-45}  ERROR {3}" -f $done, $queries.Count, $q, $_.Exception.Message)
        Write-Output $msg
        $msg | Out-File -FilePath $logFile -Append -Encoding utf8
    }

    Start-Sleep -Milliseconds 2400
}

$arr = $store.Values | Sort-Object -Property @{Expression='hits';Descending=$true}, @{Expression='stars';Descending=$true}
$arr | ConvertTo-Json -Depth 5 | Out-File -FilePath $outFile -Encoding utf8

Write-Output ""
Write-Output "==== 收割完成 ===="
Write-Output "去重后唯一仓库: $($store.Count)"
Write-Output "失败关键词: $($failed.Count)  $($failed -join ', ')"
Write-Output "输出: $outFile"
