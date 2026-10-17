param(
    [string]$TaskName = "StoryRail Default Model Providers",
    [string]$ComfyTaskName = "StoryRail ComfyUI FL2VA Runtime",
    [string]$BreezeTaskName = "StoryRail Breeze TTS 2",
    [int]$Port = 8791
)

$ErrorActionPreference = "Stop"
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$Info = Get-ScheduledTaskInfo -TaskName $TaskName
$Listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue

[PSCustomObject]@{
    TaskName = $Task.TaskName
    State = $Task.State
    LastRunTime = $Info.LastRunTime
    LastTaskResult = $Info.LastTaskResult
    NextRunTime = $Info.NextRunTime
    ListenerAddress = if ($Listener) { $Listener.LocalAddress } else { $null }
    Port = $Port
    ListenerPid = if ($Listener) { $Listener.OwningProcess } else { $null }
}

$BreezeTask = Get-ScheduledTask -TaskName $BreezeTaskName -ErrorAction SilentlyContinue
$BreezeInfo = if ($BreezeTask) { Get-ScheduledTaskInfo -TaskName $BreezeTaskName } else { $null }
$BreezeListener = Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue
[PSCustomObject]@{
    TaskName = if ($BreezeTask) { $BreezeTask.TaskName } else { $BreezeTaskName }
    State = if ($BreezeTask) { $BreezeTask.State } else { "NotInstalled" }
    LastRunTime = if ($BreezeInfo) { $BreezeInfo.LastRunTime } else { $null }
    LastTaskResult = if ($BreezeInfo) { $BreezeInfo.LastTaskResult } else { $null }
    NextRunTime = if ($BreezeInfo) { $BreezeInfo.NextRunTime } else { $null }
    ListenerAddress = if ($BreezeListener) { $BreezeListener.LocalAddress } else { $null }
    Port = 7860
    ListenerPid = if ($BreezeListener) { $BreezeListener.OwningProcess } else { $null }
}

$ComfyTask = Get-ScheduledTask -TaskName $ComfyTaskName -ErrorAction SilentlyContinue
$ComfyInfo = if ($ComfyTask) { Get-ScheduledTaskInfo -TaskName $ComfyTaskName } else { $null }
$ComfyListener = Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue
[PSCustomObject]@{
    TaskName = if ($ComfyTask) { $ComfyTask.TaskName } else { $ComfyTaskName }
    State = if ($ComfyTask) { $ComfyTask.State } else { "NotInstalled" }
    LastRunTime = if ($ComfyInfo) { $ComfyInfo.LastRunTime } else { $null }
    LastTaskResult = if ($ComfyInfo) { $ComfyInfo.LastTaskResult } else { $null }
    NextRunTime = if ($ComfyInfo) { $ComfyInfo.NextRunTime } else { $null }
    ListenerAddress = if ($ComfyListener) { $ComfyListener.LocalAddress } else { $null }
    Port = 8188
    ListenerPid = if ($ComfyListener) { $ComfyListener.OwningProcess } else { $null }
}
